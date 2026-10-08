"""
Run artefacts shared by both trainers: the config record, and checkpoint
naming/resolution.

`<out>/run_config.json` answers the question you actually have three months
later, which is not "what architecture was this" (the checkpoint's own `cfg`
covers that, because infer.py needs it to rebuild the model) but "what was this
run DOING, and how did it differ from the other one".

`save_ckpt` / `resolve_ckpt` keep two rolling checkpoints per run with the
epoch in the filename, and let any `--ckpt` argument accept the run directory
instead of a filename that changes every time the best moves.

Lives in its own module rather than in the segmenter's trainer so that
`vertex.py` -- which deliberately never touches the ViT and runs in a plain
torch + cv2 environment -- does not acquire a transformers dependency just to
write a JSON file.

EPOCH NUMBERING IS 1-BASED throughout v2: the filename, the `epoch` field
inside the .pth, and the `[ep 12/60]` log line all agree. v1 stored a 0-based
`epoch`, so a v1 checkpoint reports one less than the log line that produced it.
"""

import datetime
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path

import torch


def cli_flags(argv=None):
    """
    Which --flags were given ON THE COMMAND LINE, as opposed to defaulted.

    This is the difference between "the run used --taps auto" and "the run used
    --taps auto because that happened to be the default at the time". Defaults
    move between versions, so months later only the first is reproducible.
    Same normalisation infer.py uses to decide whether a CLI flag overrides the
    checkpoint config.
    """
    return sorted({a.split("=")[0] for a in (argv or sys.argv)
                   if a.startswith("--")})


def save_run_config(out_dir, args, derived=None, result=None,
                    name="run_config.json"):
    """
    Write/merge the run record. Safe to call repeatedly.

    Call it BEFORE building the model (so a run that dies inside
    from_pretrained still leaves a record of what it was trying to do), again
    once the model exists (to add resolved settings), and once per epoch (to
    add results).

    MERGES rather than overwrites: `derived` is added by the second call and
    must survive the per-epoch `result` calls. `started` and `env` are likewise
    set once and kept.

    ATOMIC: rewritten every epoch, so a kill landing mid-write would otherwise
    destroy the record of a run that had already completed 40 of them.

    Returns the path.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name

    prev = {}
    if path.exists():
        try:
            prev = json.loads(path.read_text())
        except (ValueError, OSError):
            prev = {}          # corrupt or truncated: start over, do not crash

    rec = dict(prev)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    rec.setdefault("started", now)
    rec["updated"] = now
    rec["command"] = " ".join([Path(sys.argv[0]).name] + sys.argv[1:])
    rec["cwd"] = os.getcwd()
    # every argument, including the ones left at their defaults -- the whole
    # point is that "not mentioned" and "explicitly set to the default" are
    # different things, and `args_from_cli` is what distinguishes them
    rec["args"] = {k: v for k, v in sorted(vars(args).items())
                   if not callable(v)}
    rec["args_from_cli"] = cli_flags()

    if "env" not in rec:
        env = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "host": platform.node(),
            "torch": torch.__version__,
        }
        try:
            import transformers
            env["transformers"] = transformers.__version__
        except Exception:
            env["transformers"] = None
        if torch.cuda.is_available():
            env["cuda"] = torch.version.cuda
            env["gpu"] = torch.cuda.get_device_name(0)
            env["gpu_count"] = torch.cuda.device_count()
        else:
            env["gpu"] = None
        rec["env"] = env

    if derived:
        rec.setdefault("derived", {}).update(derived)
    if result:
        rec.setdefault("result", {}).update(result)

    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=2, default=str))
    tmp.replace(path)
    return path


# --------------------------------------------------------------------------
# checkpoints
# --------------------------------------------------------------------------
CKPT_RE = re.compile(r"^(best|last|snap)_ep(\d+)\.pth$")


def save_ckpt(out_dir, tag, epoch, payload, roll=True):
    """
    Write `<tag>_ep<N>.pth`, and with roll=True delete any older
    `<tag>_ep*.pth`.

    roll=False keeps every checkpoint under that tag. Used by --ckpt-every for
    the `snap` tag, because the selection criterion is not always right in
    advance: run4 selected best_ep06 on val loss, while its IoU head -- the
    thing AP actually ranks on -- did not peak until ep12 (auc 0.9136 against
    0.9426). The ep12 weights were unrecoverable, because only best and last
    were ever on disk. Periodic snapshots cost ~1.6 GB each and make that
    class of mistake survivable rather than terminal.

    Two rolling checkpoints per run -- `best_ep12.pth` and `last_ep37.pth` --
    so the filename says which epoch it came from without opening it, while
    still only ever occupying two files' worth of disk.

    NEW FILE FIRST, then delete the old one. The reverse loses both if the save
    raises or the disk fills partway through, and at ~1.6 GB per checkpoint
    (the frozen backbone is in the state_dict too) filling the disk is a real
    possibility rather than a theoretical one.

    `epoch` is 1-based, matching the log line.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{tag}_ep{epoch:02d}.pth"
    torch.save(payload, path)
    if roll:
        for old in out_dir.glob(f"{tag}_ep*.pth"):
            if old.resolve() != path.resolve():
                try:
                    old.unlink()
                except OSError:
                    pass      # a stale handle is not worth failing a run over
    return path


def resolve_ckpt(spec, prefer="best"):
    """
    Accept either a checkpoint file or a RUN DIRECTORY.

    Given a directory, pick `<prefer>_ep*.pth` with the highest epoch, falling
    back to the other tag and then to a legacy `best.pth` / `last.pth`. Without
    this, every command in the pipeline would embed an epoch number that
    changes on the next run -- `--ckpt runs/v2` stays correct forever.

    Sorted by the PARSED integer, not lexically: `ep9` sorts after `ep100` as a
    string, so a lexical max silently returns an early checkpoint once a run
    passes 100 epochs.
    """
    p = Path(spec)
    if p.is_file():
        # An explicit file wins, but say so when it disagrees with the
        # requested tag -- `--ckpt runs/v2/best_ep52.pth --ckpt-tag last` would
        # otherwise silently evaluate the checkpoint you were trying to avoid.
        m = CKPT_RE.match(p.name)
        if m and m.group(1) != prefer:
            print(f"[warn] --ckpt names {p.name} explicitly, so --ckpt-tag "
                  f"{prefer} is ignored. Pass the run DIRECTORY to use the tag.")
        return p
    if not p.is_dir():
        raise SystemExit(f"[fatal] --ckpt {spec} is neither a file nor a directory")

    found = {}
    for f in p.glob("*.pth"):
        m = CKPT_RE.match(f.name)
        if m:
            found.setdefault(m.group(1), []).append((int(m.group(2)), f))
    for tag in (prefer, "best", "last"):
        if found.get(tag):
            ep, f = max(found[tag], key=lambda t: t[0])
            print(f"[load] {p} -> {f.name} (epoch {ep})")
            return f
    for legacy in (f"{prefer}.pth", "best.pth", "last.pth"):
        if (p / legacy).is_file():
            print(f"[load] {p} -> {legacy} (legacy name)")
            return p / legacy
    raise SystemExit(
        f"[fatal] no checkpoint in {p}. Expected best_ep*.pth / last_ep*.pth")


# --------------------------------------------------------------------------
# per-epoch loss log
# --------------------------------------------------------------------------
def append_loss_row(out_dir, row, name="loss_log.csv"):
    """
    Append one epoch to `<out>/loss_log.csv`, creating it with a header.

    CSV rather than JSON lines because the thing you do with a loss curve is
    plot it or diff two runs, and every tool already reads CSV.

    Appended, not rewritten: the file is the one artefact that must survive a
    kill with its full history intact, and rewriting it each epoch would put
    the whole run at risk of a single bad write. The trade-off is that a
    RESUMED run appends a second header -- handled by writing the header only
    when the file does not yet exist, and by including `epoch` so duplicate or
    restarted epochs are visible rather than silently interleaved.

    Column order is fixed by the first row written; later rows are aligned to
    that header by key, and any key not in it is dropped (with one warning) so
    an added metric mid-run cannot shift every subsequent column.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name

    def fmt(v):
        if v is None:
            return ""
        if isinstance(v, bool):
            return "1" if v else "0"
        if isinstance(v, float):
            return f"{v:.6g}"
        return str(v)

    if not path.exists():
        header = list(row)
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write(",".join(header) + "\n")
            f.write(",".join(fmt(row[k]) for k in header) + "\n")
        return path

    with path.open("r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    extra = [k for k in row if k not in header]
    if extra:
        print(f"[warn] loss_log.csv has no column for {extra}; not logged. "
              f"Delete the file to start a new schema.")
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write(",".join(fmt(row.get(k)) for k in header) + "\n")
    return path


# --------------------------------------------------------------------------
# fresh output directory (TRAINING ONLY)
# --------------------------------------------------------------------------
RUN_ARTEFACTS = ("run_config.json", "loss_log.csv")


def fresh_run_dir(out_dir):
    """
    Wipe `out_dir` and recreate it empty. TRAINING ONLY -- inference and
    polygonization write alongside existing outputs on purpose.

    Why wipe at all: a re-launch into an existing directory used to leave the
    previous run's artefacts in place, and `loss_log.csv` is APPENDED. A run3
    that was killed at epoch 9 and relaunched produced one CSV holding two runs
    back to back, with the epoch column restarting at 1 -- which plots as a
    sudden jump in the loss and reads exactly like divergence. Starting clean
    removes the whole class of confusion.

    THE GUARD IS THE POINT. `shutil.rmtree` on a mistyped --out is
    irreversible, and the plausible typo here is `--out ./runs` instead of
    `--out ./runs/run4`, which would take every run with it. So a non-empty
    directory is only removed when it actually looks like a run output: it
    holds a run_config.json, a loss_log.csv, or a .pth. Anything else stops the
    launch and asks you to clear it yourself.
    """
    p = Path(out_dir)
    if p.exists():
        if not p.is_dir():
            raise SystemExit(f"[fatal] --out {p} exists and is not a directory")
        entries = list(p.iterdir())
        if entries:
            looks_like_run = (any((p / n).exists() for n in RUN_ARTEFACTS)
                              or any(f.suffix == ".pth" for f in entries))
            if not looks_like_run:
                listing = ", ".join(sorted(f.name for f in entries)[:6])
                raise SystemExit(
                    f"[fatal] --out {p} is not empty and does not look like a "
                    f"run directory (no run_config.json / loss_log.csv / .pth).\n"
                    f"        It holds: {listing}"
                    f"{' ...' if len(entries) > 6 else ''}\n"
                    f"        Refusing to delete it. Point --out somewhere else, "
                    f"or remove it yourself.")
            mb = sum(f.stat().st_size for f in entries if f.is_file()) / 1e6
            shutil.rmtree(p)
            print(f"[run] removed existing {p} "
                  f"({len(entries)} entries, {mb:.0f} MB)")
    p.mkdir(parents=True, exist_ok=True)
    return p
