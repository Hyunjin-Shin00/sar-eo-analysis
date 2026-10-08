"""
Self-test for the v2 additions.

    python selftest.py

Runs on CPU in a few seconds and needs NO model weights and no DINOv3 support
in `transformers` -- the backbone is stubbed. The point is to catch the errors
that are expensive to find on a GPU eight hours into a run: a loss that is
silently always zero, a tap index off by one, a head whose output is not in
[0, 1], a shape that only breaks on the empty-tile case.

Every check has a KNOWN answer derived from the construction, not a golden
value recorded from a previous run.
"""

import contextlib
import io
import sys
import tempfile
import types

import numpy as np
import torch
import torch.nn as nn

from losses import (boundary_loss, collision_loss, crowd_zone, instances_at,
                    maskiou_targets, semantic_prob)
from heads import MaskIoUHead, _geom

FAIL = []


def check(name, cond, detail=""):
    ok = bool(cond)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))
    if not ok:
        FAIL.append(name)


def out_stub(mask_logits, cls_logits=None):
    """Minimal stand-in for Mask2FormerForUniversalSegmentationOutput."""
    b, q = mask_logits.shape[:2]
    if cls_logits is None:
        # 2 columns = 1 foreground class + no-object. Large positive on the
        # foreground slot so softmax gives cls ~ 1, matching the saturated
        # single-class regime the real model sits in.
        cls_logits = torch.zeros(b, q, 2)
        cls_logits[..., 0] = 8.0
    return types.SimpleNamespace(masks_queries_logits=mask_logits,
                                 class_queries_logits=cls_logits)


def rect(h, w, y0, y1, x0, x1):
    m = torch.zeros(h, w)
    m[y0:y1, x0:x1] = 1.0
    return m


def logit_of(mask, hi=8.0):
    """A confident logit field shaped like `mask`."""
    return mask * hi * 2 - hi


# --------------------------------------------------------------------------
print("\n[1] losses -- semantic_prob / instances_at")
H = W = 64
a = rect(H, W, 8, 24, 8, 24)
b = rect(H, W, 8, 24, 26, 42)          # 2 px gap from `a`
far = rect(H, W, 48, 60, 48, 60)

o = out_stub(torch.stack([logit_of(a), logit_of(b)])[None])   # (1, 2, 64, 64)
sem = semantic_prob(o)
check("semantic_prob shape", sem.shape == (1, H, W), str(tuple(sem.shape)))
check("semantic_prob in [0,1]", float(sem.min()) >= 0 and float(sem.max()) <= 1,
      f"[{float(sem.min()):.3f}, {float(sem.max()):.3f}]")
check("semantic_prob ~1 on a building", float(sem[0, 12, 12]) > 0.99,
      f"{float(sem[0, 12, 12]):.4f}")
check("semantic_prob ~0 on background", float(sem[0, 55, 12]) < 0.01,
      f"{float(sem[0, 55, 12]):.4f}")

# instances_at must survive an empty tile -- interpolate() cannot take N=0
e = instances_at([torch.zeros(0, H, W)], 16, 16)
check("instances_at handles 0 instances", e[0].shape == (0, 16, 16),
      str(tuple(e[0].shape)))
d = instances_at([torch.stack([a, b])], 16, 16)
check("instances_at downsamples", d[0].shape == (2, 16, 16), str(tuple(d[0].shape)))

# --------------------------------------------------------------------------
print("\n[2] crowd_zone -- the narrow-alley detector")
cz_near = crowd_zone(torch.stack([a, b]), gap=3)
cz_far = crowd_zone(torch.stack([a, far]), gap=3)
check("fires in the 2px alley between neighbours", float(cz_near.sum()) > 0,
      f"{int(cz_near.sum())} px")
check("silent for well-separated buildings", float(cz_far.sum()) == 0,
      f"{int(cz_far.sum())} px")
check("alley zone is a small fraction of the tile",
      float(cz_near.sum()) < 0.15 * H * W,
      f"{float(cz_near.sum())/(H*W):.1%} of pixels")
check("single instance never triggers",
      float(crowd_zone(a[None], gap=3).sum()) == 0)

# --------------------------------------------------------------------------
print("\n[3] boundary_loss")
gt = [torch.stack([a, b])]
perfect = out_stub(torch.stack([logit_of(a), logit_of(b)])[None])
# 3 px outward: same area class, wrong edge -- exactly the v1 failure mode
shifted = out_stub(torch.stack([logit_of(rect(H, W, 5, 27, 5, 27)),
                                logit_of(rect(H, W, 5, 27, 23, 45))])[None])
l_perfect = float(boundary_loss(perfect, gt, width=3))
l_shifted = float(boundary_loss(shifted, gt, width=3))
check("~0 for a perfect prediction", l_perfect < 0.05, f"{l_perfect:.5f}")
check("large for a 3px-shifted prediction", l_shifted > 10 * max(l_perfect, 1e-3),
      f"{l_shifted:.5f} vs {l_perfect:.5f}")
lw0 = float(boundary_loss(shifted, gt, width=3, crowd_weight=0.0))
lw3 = float(boundary_loss(shifted, gt, width=3, crowd_weight=3.0))
check("crowd_weight changes the loss", abs(lw3 - lw0) > 1e-4,
      f"w=0 {lw0:.5f}  w=3 {lw3:.5f}")
check("empty tile returns finite 0",
      float(boundary_loss(perfect, [torch.zeros(0, H, W)], width=3)) == 0.0)
# `ignore` must be able to switch the term off entirely
li = float(boundary_loss(shifted, gt, width=3, ignore=torch.ones(1, H, W)))
check("ignore=all suppresses the term", li == 0.0, f"{li:.5f}")

# --------------------------------------------------------------------------
print("\n[4] collision_loss -- the merge penalty")
# one query per building: nothing to charge
clean = out_stub(torch.stack([logit_of(a), logit_of(b)])[None])
# ONE query spanning both buildings: the exact v1 failure
merged = out_stub(torch.stack([logit_of(rect(H, W, 8, 24, 8, 42)),
                               logit_of(torch.zeros(H, W))])[None])
c_clean = float(collision_loss(clean, gt))
c_merged = float(collision_loss(merged, gt))
check("~0 when each query holds one building", c_clean < 0.05, f"{c_clean:.5f}")
check("positive when one query holds two", c_merged > 0.5, f"{c_merged:.5f}")
check("merged is charged far more than clean", c_merged > 10 * max(c_clean, 1e-3),
      f"{c_merged:.4f} vs {c_clean:.4f}")
check("single-instance tile is uncharged",
      float(collision_loss(clean, [a[None]])) == 0.0)
check("empty tile is uncharged",
      float(collision_loss(clean, [torch.zeros(0, H, W)])) == 0.0)
# and it must be differentiable, or it does nothing at all
ml = torch.stack([logit_of(rect(H, W, 8, 24, 8, 42)),
                  logit_of(torch.zeros(H, W))])[None].requires_grad_(True)
collision_loss(out_stub(ml), gt).backward()
check("gradient reaches the mask logits",
      ml.grad is not None and float(ml.grad.abs().sum()) > 0,
      f"|grad| = {float(ml.grad.abs().sum()):.4f}")
# pool= must not change the verdict, only the memory
for pl in (1, 2, 4):
    cm = float(collision_loss(merged, gt, pool=pl))
    cc = float(collision_loss(clean, gt, pool=pl))
    check(f"pool={pl}: merged still charged, clean still not",
          cm > 0.5 and cc < 0.05, f"merged {cm:.4f}  clean {cc:.4f}")

# --------------------------------------------------------------------------
print("\n[5] maskiou_targets")
t_perfect = maskiou_targets(perfect, gt)
check("shape (B, Q)", t_perfect.shape == (1, 2), str(tuple(t_perfect.shape)))
check("1.0 for exact masks", float(t_perfect.min()) > 0.99,
      f"min {float(t_perfect.min()):.4f}")
half = out_stub(torch.stack([logit_of(rect(H, W, 8, 24, 8, 16)),
                             logit_of(a)])[None])
t_half = maskiou_targets(half, gt)
check("~0.5 for a half-covering mask", 0.4 < float(t_half[0, 0]) < 0.6,
      f"{float(t_half[0, 0]):.4f}")
junk = out_stub(torch.stack([logit_of(far), logit_of(far)])[None])
check("~0 for a mask on nothing", float(maskiou_targets(junk, gt).max()) < 0.05,
      f"{float(maskiou_targets(junk, gt).max()):.4f}")
check("0 when there is no GT",
      float(maskiou_targets(perfect, [torch.zeros(0, H, W)]).abs().max()) == 0.0)

# --------------------------------------------------------------------------
print("\n[6] MaskIoUHead")
torch.manual_seed(0)
Bq, Q, Cq, Cm, h = 2, 7, 256, 256, 64
head = MaskIoUHead(Cq, Cm, hidden=64, pool_size=32)
qe = torch.randn(Bq, Q, Cq)
mf = torch.randn(Bq, Cm, h, h)
mlg = torch.randn(Bq, Q, h, h) * 4
with torch.no_grad():
    p = head(qe, mf, mlg)
check("shape (B, Q)", p.shape == (Bq, Q), str(tuple(p.shape)))
check("output in [0,1]", float(p.min()) >= 0 and float(p.max()) <= 1,
      f"[{float(p.min()):.4f}, {float(p.max()):.4f}]")
# zero BIAS (not zero weight -- see heads.py) so this starts near 0.5 but the
# input gradient is live from step 0
check("starts near 0.5 (zero-init final bias)", abs(float(p.mean()) - 0.5) < 0.1,
      f"mean {float(p.mean()):.6f}")
# detach must actually detach: no grad may reach the inputs
qe2 = qe.clone().requires_grad_(True)
mf2 = mf.clone().requires_grad_(True)
head(qe2, mf2, mlg, detach=True).sum().backward()
check("detach=True blocks grad to query embeddings", qe2.grad is None)
check("detach=True blocks grad to mask features", mf2.grad is None)
qe3 = qe.clone().requires_grad_(True)
head(qe3, mf2.detach(), mlg, detach=False).sum().backward()
check("detach=False lets grad through",
      qe3.grad is not None and float(qe3.grad.abs().sum()) > 0)
# the head must be trainable at all: overfit 32 fixed samples
opt = torch.optim.Adam(head.parameters(), lr=3e-3)
tgt = torch.rand(Bq, Q)
for _ in range(300):
    opt.zero_grad()
    loss = ((head(qe, mf, mlg) - tgt) ** 2).mean()
    loss.backward()
    opt.step()
check("can fit a fixed target (learns at all)", float(loss) < 1e-3,
      f"final MSE {float(loss):.6f}")

g = _geom(torch.stack([a, b, torch.zeros(H, W)])[None])
check("_geom shape", g.shape == (1, 3, 3), str(tuple(g.shape)))
check("_geom zeroes an empty mask", float(g[0, 2, 0]) == 0.0 and float(g[0, 2, 2]) == 0.0,
      f"mq {float(g[0,2,0]):.3f} soft {float(g[0,2,2]):.3f}")
check("_geom mq ~1 for a crisp mask", float(g[0, 0, 0]) > 0.99,
      f"{float(g[0,0,0]):.4f}")
check("_geom is finite", bool(torch.isfinite(g).all()))

# --------------------------------------------------------------------------
print("\n[7] score modes")
from infer import SCORE_MODES, combine_score
cs = torch.tensor([0.99, 0.90, 0.99])
mq = torch.tensor([0.97, 0.97, 0.97])
pi = torch.tensor([0.85, 0.80, 0.20])
check("cls_iou demotes a confident bad mask",
      int(torch.argmin(combine_score(cs, mq, pi, "cls_iou"))) == 2)
check("cls_mq cannot tell them apart (the v1 problem)",
      float(combine_score(cs, mq, pi, "cls_mq")[0]
            - combine_score(cs, mq, pi, "cls_mq")[2]) == 0.0)
check("all modes are implemented",
      all(combine_score(cs, mq, pi, m) is not None for m in SCORE_MODES))
try:
    combine_score(cs, mq, None, "cls_iou")
    check("cls_iou without a head raises", False)
except SystemExit:
    check("cls_iou without a head raises", True)

# --------------------------------------------------------------------------
print("\n[8] Tier 3 pyramid taps (stubbed backbone)")
from train_dinov3_mask2former import DINOv3Pyramid, resolve_taps

DEPTH, EMB, PATCH = 12, 256, 16


class StubViT(nn.Module):
    """Mimics only what DINOv3Pyramid touches: 1 prefix token, N blocks."""

    def __init__(self):
        super().__init__()
        self.config = types.SimpleNamespace(hidden_size=EMB, patch_size=PATCH,
                                            num_hidden_layers=DEPTH)
        self.blocks = nn.ModuleList([nn.Linear(EMB, EMB) for _ in range(DEPTH)])
        self.proj = nn.Conv2d(3, EMB, PATCH, PATCH)

    def forward(self, px, output_hidden_states=False, **kw):
        t = self.proj(px).flatten(2).transpose(1, 2)
        t = torch.cat([t[:, :1] * 0, t], 1)              # 1 prefix token
        hs = [t]
        for blk in self.blocks:
            t = blk(t)
            hs.append(t)
        o = types.SimpleNamespace(last_hidden_state=t)
        if output_hidden_states:
            o.hidden_states = tuple(hs)
        return o


vit = StubViT()
taps = resolve_taps(vit, "auto")
check("auto taps -> 4 indices", taps is not None and len(taps) == 4, str(taps))
check("taps are 1-based into hidden_states, last == depth",
      taps[-1] == DEPTH, f"{taps[-1]} vs depth {DEPTH}")
check("taps strictly increasing", all(x < y for x, y in zip(taps, taps[1:])), str(taps))
check("'off' disables", resolve_taps(vit, "off") is None)
check("explicit list is honoured", resolve_taps(vit, "0,3,7,11") == [1, 4, 8, 12])

OUT_CH = [128, 256, 512, 1024]
img = torch.randn(2, 3, 256, 256)
for spec in ("off", "auto"):
    pyr = DINOv3Pyramid(StubViT(), OUT_CH, EMB, patch_size=PATCH,
                        freeze_vit=True, use_stem=True,
                        taps=resolve_taps(vit, spec))
    fm = pyr(img).feature_maps
    shapes = [tuple(f.shape) for f in fm]
    check(f"taps={spec}: 4 maps", len(fm) == 4)
    check(f"taps={spec}: channels match the pixel decoder",
          [f.shape[1] for f in fm] == OUT_CH, str([f.shape[1] for f in fm]))
    check(f"taps={spec}: strides 4/8/16/32",
          [f.shape[-1] for f in fm] == [64, 32, 16, 8], str([f.shape[-1] for f in fm]))
    check(f"taps={spec}: finite", all(bool(torch.isfinite(f).all()) for f in fm))

pyr_on = DINOv3Pyramid(StubViT(), OUT_CH, EMB, patch_size=PATCH,
                       taps=resolve_taps(vit, "auto"))
check("tap_norm exists only with taps on", pyr_on.tap_norm is not None)
check("tap_norm has one norm per level", len(pyr_on.tap_norm) == 4)
pyr_off = DINOv3Pyramid(StubViT(), OUT_CH, EMB, patch_size=PATCH, taps=None)
check("tap_norm absent with taps off", pyr_off.tap_norm is None)
# taps must be trainable even though the ViT is frozen
n_tr = sum(p.numel() for n, p in pyr_on.named_parameters()
           if p.requires_grad and "tap_norm" in n)
check("tap_norm params are trainable", n_tr == 4 * 2 * EMB, f"{n_tr} params")

# --------------------------------------------------------------------------
print("\n[9] Tier 0 crowd handling")
from pycocotools.coco import COCO
import contextlib
import io
import json
import tempfile
from pathlib import Path

tiny = {"images": [{"id": 0, "file_name": "t.png", "height": 32, "width": 32}],
        "categories": [{"id": 1, "name": "building"}],
        "annotations": [
            {"id": 0, "image_id": 0, "category_id": 1, "iscrowd": 0,
             "area": 64, "bbox": [0, 0, 8, 8],
             "segmentation": [[0, 0, 8, 0, 8, 8, 0, 8]]},
            {"id": 1, "image_id": 0, "category_id": 1, "iscrowd": 1,
             "area": 64, "bbox": [16, 16, 8, 8],
             "segmentation": [[16, 16, 24, 16, 24, 24, 16, 24]]}]}
tf = Path(tempfile.mkdtemp()) / "a.json"
tf.write_text(json.dumps(tiny))
with contextlib.redirect_stdout(io.StringIO()):
    c = COCO(str(tf))
check("getAnnIds() with no kwarg returns crowd too (crowd='instance')",
      len(c.getAnnIds(0)) == 2, f"{len(c.getAnnIds(0))} anns")
check("iscrowd=False excludes it (crowd='background')",
      len(c.getAnnIds(0, iscrowd=False)) == 1)
check("iscrowd=True selects only crowd",
      len(c.getAnnIds(0, iscrowd=True)) == 1)

# --------------------------------------------------------------------------
print("\n[10] runlog -- checkpoint rotation and resolution")
import tempfile
from runlog import resolve_ckpt, save_ckpt

d = Path(tempfile.mkdtemp())
for ep in (1, 5, 12):
    save_ckpt(d, "last", ep, {"e": ep})
    if ep != 5:                       # epoch 5 was not an improvement
        save_ckpt(d, "best", ep, {"e": ep})
names = sorted(f.name for f in d.glob("*.pth"))
check("exactly two .pth after 3 epochs", len(names) == 2, str(names))
check("best kept its own epoch, not last's",
      "best_ep12.pth" in names and "last_ep12.pth" in names, str(names))
save_ckpt(d, "last", 13, {"e": 13})
names = sorted(f.name for f in d.glob("*.pth"))
check("saving last leaves best alone",
      "best_ep12.pth" in names and "last_ep13.pth" in names, str(names))
check("still exactly two", len(names) == 2, str(names))

with contextlib.redirect_stdout(io.StringIO()):
    r_best = resolve_ckpt(d).name
    r_last = resolve_ckpt(d, prefer="last").name
    r_file = resolve_ckpt(d / "last_ep13.pth").name
check("directory resolves to the newest best", r_best == "best_ep12.pth", r_best)
check("prefer=last resolves to the newest last", r_last == "last_ep13.pth", r_last)
check("an explicit file passes through", r_file == "last_ep13.pth", r_file)

# ep9 sorts AFTER ep100 lexically, so a string max returns the wrong file
d2 = Path(tempfile.mkdtemp())
for ep in (9, 100):
    torch.save({"e": ep}, d2 / f"best_ep{ep:02d}.pth")
with contextlib.redirect_stdout(io.StringIO()):
    got = resolve_ckpt(d2).name
check("resolves numerically, not lexically (ep100 > ep09)",
      got == "best_ep100.pth", got)

d3 = Path(tempfile.mkdtemp())
save_ckpt(d3, "last", 7, {"e": 7})
with contextlib.redirect_stdout(io.StringIO()):
    got = resolve_ckpt(d3).name
check("no best -> falls back to last", got == "last_ep07.pth", got)

d4 = Path(tempfile.mkdtemp())
torch.save({"e": 0}, d4 / "best.pth")
with contextlib.redirect_stdout(io.StringIO()):
    got = resolve_ckpt(d4).name
check("a legacy v1 best.pth still loads", got == "best.pth", got)

d5 = Path(tempfile.mkdtemp())
for label, arg in (("an empty run dir", d5), ("a nonexistent path", d5 / "nope")):
    try:
        resolve_ckpt(arg)
        check(f"{label} raises rather than returning None", False)
    except SystemExit:
        check(f"{label} raises rather than returning None", True)


# --------------------------------------------------------------------------
print("\n[11] runlog -- per-epoch loss log")
import csv as _csv
from runlog import append_loss_row

ld = Path(tempfile.mkdtemp())
append_loss_row(ld, {"epoch": 1, "train": 35.5845, "val": 29.4832,
                     "bnd": 0.6958, "col": 0.285, "iou_auc": None,
                     "is_best": True, "secs": 61.3})
append_loss_row(ld, {"epoch": 2, "train": 24.6146, "val": 26.3098,
                     "bnd": 0.5903, "col": 0.1274, "iou_auc": 0.71,
                     "is_best": True, "secs": 59.8})
append_loss_row(ld, {"epoch": 3, "train": 22.6715, "val": 27.1994,
                     "bnd": 0.5896, "col": 0.0985, "iou_auc": 0.74,
                     "is_best": False, "secs": 60.1})
rows = (ld / "loss_log.csv").read_text().strip().split("\n")
check("header plus one row per epoch", len(rows) == 4, f"{len(rows)} lines")
check("header written exactly once", rows[0].startswith("epoch,train,val"),
      rows[0])
check("None becomes an empty field, not the string 'None'",
      "None" not in rows[1], rows[1])
check("bool logs as 1/0", rows[3].split(",")[6] == "0", rows[3])

# a metric added mid-run must not shift every later column
with contextlib.redirect_stdout(io.StringIO()):
    append_loss_row(ld, {"epoch": 4, "train": 22.5, "val": 24.4, "bnd": 0.58,
                         "col": 0.097, "iou_auc": 0.76, "is_best": True,
                         "secs": 60, "ADDED_LATER": 1.23})
rows = (ld / "loss_log.csv").read_text().strip().split("\n")
check("an unknown key is dropped, columns stay aligned",
      len(rows[-1].split(",")) == len(rows[0].split(",")),
      f"{len(rows[-1].split(','))} vs {len(rows[0].split(','))} fields")
# and a MISSING key must blank its field rather than shift the rest
append_loss_row(ld, {"epoch": 5, "train": 22.0, "val": 24.0})
rows = (ld / "loss_log.csv").read_text().strip().split("\n")
check("a missing key blanks its field, columns stay aligned",
      len(rows[-1].split(",")) == len(rows[0].split(",")), rows[-1])

parsed = list(_csv.DictReader(io.StringIO((ld / "loss_log.csv").read_text())))
check("parses as CSV", len(parsed) == 5, f"{len(parsed)} rows")
check("values round-trip exactly", parsed[0]["val"] == "29.4832",
      parsed[0]["val"])

print("\n[12] iou_head_stats -- AUC is readable where MAE is not")
from heads import iou_head_stats
# the real query distribution: ~26 matched of 200, the rest parked at 0
_t = torch.cat([torch.full((26,), 0.8), torch.zeros(174)])
s_perfect = iou_head_stats(_t.clone(), _t)
s_const = iou_head_stats(torch.full((200,), 0.5), _t)
s_rev = iou_head_stats(1 - _t, _t)
check("perfect ranker -> auc 1.0", abs(s_perfect["auc"] - 1.0) < 1e-6,
      f"{s_perfect['auc']:.3f}")
check("constant -> auc 0.5 (chance)", abs(s_const["auc"] - 0.5) < 1e-6,
      f"{s_const['auc']:.3f}")
check("reversed -> auc 0.0", s_rev["auc"] < 1e-6, f"{s_rev['auc']:.3f}")
# THE POINT: a useless constant predictor scores a mid-range MAE, so MAE alone
# cannot tell "learning" from "not learning" on this distribution
check("a constant predictor still scores a mid-range MAE (why MAE misleads)",
      0.3 < s_const["mae"] < 0.6, f"mae {s_const['mae']:.3f}")
check("n_pos counts only matched queries", s_const["n_pos"] == 26,
      str(s_const["n_pos"]))
check("mae_pos ignores the parked queries",
      abs(s_const["mae_pos"] - 0.3) < 1e-6, f"{s_const['mae_pos']:.3f}")
check("no positives -> auc is None rather than a fabricated number",
      iou_head_stats(torch.zeros(10), torch.zeros(10))["auc"] is None)


# --------------------------------------------------------------------------
print("\n[13] infer.py scoring is safe at the numpy boundary")
from infer import _post_from_prob, combine_score as _cs

# The exact shape of the bug that reached a real run: MaskIoUHead(detach=True)
# detaches its INPUTS, but its own parameters still require grad, so a
# pred_iou produced outside torch.no_grad() carries requires_grad -- and then
# `score = cls * pred_iou` did too, and .numpy() raised.
_head = MaskIoUHead(32, 32, hidden=16, pool_size=8)
_qe = torch.randn(1, 4, 32)
_mf = torch.randn(1, 32, 16, 16)
_ml = torch.randn(1, 4, 16, 16) * 3
_pi_grad = _head(_qe, _mf, _ml)[0]          # NOT under no_grad, on purpose
check("head output requires grad outside no_grad (the trap)",
      _pi_grad.requires_grad)
with torch.no_grad():
    _pi_nograd = _head(_qe, _mf, _ml)[0]
check("head output is grad-free inside no_grad (the fix in _forward_probs)",
      not _pi_nograd.requires_grad)

_prob = torch.rand(4, 24, 24)
_clsz = torch.rand(4) * 0.2 + 0.8
for _tag, _pi in (("grad-carrying", _pi_grad), ("detached", _pi_nograd)):
    try:
        _res = _post_from_prob(_prob, _clsz, score_thr=0.0, min_area=1,
                               pred_iou=_pi, score_mode="cls_iou")
        ok = all(isinstance(r[1], float) for r in _res)
        check(f"_post_from_prob survives a {_tag} pred_iou", ok,
              f"{len(_res)} instances")
    except RuntimeError as e:
        check(f"_post_from_prob survives a {_tag} pred_iou", False, str(e)[:70])

# and every score mode must reach numpy, not just the default one
for _m in ("cls_iou", "iou", "cls_mq", "cls"):
    try:
        _r = _post_from_prob(_prob, _clsz, score_thr=0.0, min_area=1,
                             pred_iou=_pi_grad, score_mode=_m)
        check(f"score_mode={_m} converts to numpy", True, f"{len(_r)} inst")
    except RuntimeError as e:
        check(f"score_mode={_m} converts to numpy", False, str(e)[:70])


# --------------------------------------------------------------------------
print("\n[14] fragmentation_loss -- the mirror of collision_loss")
from losses import fragmentation_loss

one = [a[None]]                       # a single GT building
q_own = out_stub(torch.stack([logit_of(a)])[None])
q_2eq = out_stub(torch.stack([logit_of(rect(H, W, 8, 24, 8, 16)),
                              logit_of(rect(H, W, 8, 24, 16, 24))])[None])
q_2sk = out_stub(torch.stack([logit_of(rect(H, W, 8, 24, 8, 20)),
                              logit_of(rect(H, W, 8, 24, 20, 24))])[None])

# CLOSED FORM: when the claimants cover the instance once between them, the
# term is 1 - (largest claimant's share). These are not recorded values.
f_own = float(fragmentation_loss(q_own, one))
f_2eq = float(fragmentation_loss(q_2eq, one))
f_2sk = float(fragmentation_loss(q_2sk, one))
check("one query owns it -> 0", f_own < 0.01, f"{f_own:.4f}")
check("even 2-way split -> 1-1/2 = 0.50", abs(f_2eq - 0.50) < 0.01, f"{f_2eq:.4f}")
check("75/25 split -> 1-0.75 = 0.25", abs(f_2sk - 0.25) < 0.02, f"{f_2sk:.4f}")

# the two terms must be COMPLEMENTARY: each blind to the other's failure
f_merged = float(fragmentation_loss(merged, gt))
c_split = float(collision_loss(q_2eq, one))
check("fragmentation ignores a merge (collision's job)", f_merged < 0.05,
      f"{f_merged:.4f}")
check("collision ignores a split (fragmentation's job)", c_split < 0.05,
      f"{c_split:.4f}")
check("so the two terms are not redundant",
      c_merged > 0.5 and f_2eq > 0.4 and f_merged < 0.05 and c_split < 0.05)

check("empty tile uncharged",
      float(fragmentation_loss(q_own, [torch.zeros(0, H, W)])) == 0.0)
mlf = torch.stack([logit_of(rect(H, W, 8, 24, 8, 16)),
                   logit_of(rect(H, W, 8, 24, 16, 24))])[None].requires_grad_(True)
fragmentation_loss(out_stub(mlf), one).backward()
check("gradient reaches the mask logits",
      mlf.grad is not None and float(mlf.grad.abs().sum()) > 0,
      f"|grad| {float(mlf.grad.abs().sum()):.4f}")
for pl in (1, 2, 4):
    v = float(fragmentation_loss(q_2eq, one, pool=pl))
    check(f"pool={pl} preserves the 2-way verdict", 0.4 < v < 0.6, f"{v:.4f}")


# --------------------------------------------------------------------------
print("\n[15] runlog -- fresh_run_dir (TRAINING ONLY)")
from runlog import fresh_run_dir

_root = Path(tempfile.mkdtemp())

fresh_run_dir(_root / "new")
check("a nonexistent --out is created",
      (_root / "new").is_dir() and not list((_root / "new").iterdir()))

(_root / "empty").mkdir()
fresh_run_dir(_root / "empty")
check("an empty --out is left alone", (_root / "empty").is_dir())

# a directory that looks like a run gets wiped: stale checkpoints and an
# APPENDED loss_log.csv from a killed attempt are what produced a CSV holding
# two runs back to back, with the epoch column restarting at 1
_run = _root / "run"; _run.mkdir()
(_run / "run_config.json").write_text("{}")
(_run / "loss_log.csv").write_text("epoch\n1\n")
torch.save({"x": 1}, _run / "best_ep07.pth")
with contextlib.redirect_stdout(io.StringIO()):
    fresh_run_dir(_run)
check("a run directory is wiped clean", not list(_run.iterdir()))

_only = _root / "onlypth"; _only.mkdir()
torch.save({"x": 1}, _only / "last_ep60.pth")
with contextlib.redirect_stdout(io.StringIO()):
    fresh_run_dir(_only)
check("a directory holding only a .pth counts as a run", not list(_only.iterdir()))

# THE GUARD: the plausible typo is `--out ./runs` for `--out ./runs/run4`,
# which without this would delete every run at once.
_runs = _root / "runs"; _runs.mkdir()
(_runs / "run1").mkdir(); (_runs / "run2").mkdir()
(_runs / "notes.txt").write_text("keep me")
try:
    fresh_run_dir(_runs)
    check("a non-run directory is REFUSED, not deleted", False)
except SystemExit:
    check("a non-run directory is REFUSED, not deleted", True)
check("  and its contents survive the refusal",
      (_runs / "run1").is_dir() and (_runs / "run2").is_dir()
      and (_runs / "notes.txt").is_file())

_f = _root / "afile"; _f.write_text("x")
try:
    fresh_run_dir(_f)
    check("--out pointing at a FILE raises", False)
except SystemExit:
    check("--out pointing at a FILE raises", True)


# --------------------------------------------------------------------------
print("\n" + "=" * 62)
if FAIL:
    print(f"{len(FAIL)} FAILED: {FAIL}")
    sys.exit(1)
print("all checks passed")
