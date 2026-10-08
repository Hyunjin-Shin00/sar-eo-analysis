"""
Train the stage-2 polygon network.

SELECTION IS ON CORNER F1 AT 2 SCENE PX, not on val loss and not on recall.

Not loss: it is a weighted sum of four heads and a checkpoint that minimises it
need not be the one that places corners best.

Not recall: recall (GT vertex -> nearest predicted) CANNOT FALL as the head
emits more vertices, so a model that doubles its vertex count scores better
while being worse. That failure has already been paid for once, on a head that
looked like a +2.7% gain while emitting 2.06 vertices per GT vertex and losing
polygon IoU. Precision is measured alongside it from the first epoch.

DISTANCES ARE IN SCENE PIXELS, NOT CELLS. Each crop has its own scale
(0.43-1.45 scene px per cell), so a threshold in cells would mean something
different for every building and would flatter small ones.
"""
import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from tqdm.auto import tqdm

from data import PolyDataset, collate
from losses import PolyLoss
from model import build
from targets import decode, gt_points


def match(pred, gt, px_per_cell, thr):
    """(#gt within thr of a pred, #pred within thr of a gt) in scene px."""
    if len(gt) == 0:
        return 0, 0
    if len(pred) == 0:
        return 0, 0
    d = np.linalg.norm(pred[:, None, :] - gt[None, :, :], axis=2) * px_per_cell
    return int((d.min(0) < thr).sum()), int((d.min(1) < thr).sum())


@torch.no_grad()
def validate(model, dl, dev, vthr, merge, crit):
    model.eval()
    acc = {2: [0, 0], 4: [0, 0]}
    n_gt = n_pred = 0
    iou_n = iou_d = 0.0
    bias_sum, bias_n = 0.0, 0
    loss_sum, parts_sum, nb = 0.0, {}, 0
    for b in tqdm(dl, desc="val", leave=False):
        x = b["x"].to(dev)
        t = {k: v.to(dev) for k, v in b["t"].items()}
        out = model(x)
        L, parts = crit(out, t)
        loss_sum += float(L)
        for k, v in parts.items():
            parts_sum[k] = parts_sum.get(k, 0.0) + v
        nb += 1

        pm = (torch.sigmoid(out["mask"]) > 0.5).float()
        gm = t["mask"]
        iou_n += float((pm * gm).sum())
        iou_d += float(((pm + gm) > 0).float().sum())
        # SIGNED MASK BIAS, in scene px. Area difference over GT perimeter is
        # the mean outward offset of the boundary. connect.fit_edges puts
        # corners on the fitted mask walls, so it inherits this bias directly
        # and is only worth using while |bias| stays under about 2 px.
        ar_p = pm.sum((1, 2, 3))
        ar_g = gm.sum((1, 2, 3))
        per = (gm - torch.nn.functional.avg_pool2d(gm, 3, 1, 1)).abs().sum((1, 2, 3))
        ppc_b = torch.as_tensor(b["frame"][:, 2] / out["mask"].shape[-1],
                                dtype=ar_p.dtype, device=ar_p.device)
        ok_b = per > 1
        if bool(ok_b.any()):
            bias_sum += float((((ar_p - ar_g) / per.clamp(min=1.0))
                               * ppc_b)[ok_b].sum())
            bias_n += int(ok_b.sum())

        vmap = torch.sigmoid(out["vmap"])[:, 0].cpu().numpy()
        voff = torch.sigmoid(out["voff"]).cpu().numpy()
        vmk = t["vmask"].cpu().numpy()
        vof = t["voff"].cpu().numpy()
        out_sz = vmap.shape[-1]
        for i in range(len(vmap)):
            p, _ = decode(vmap[i], voff[i], thr=vthr, merge=merge)
            g = gt_points(vmk[i], vof[i])
            ppc = b["frame"][i][2] / out_sz          # scene px per cell
            n_gt += len(g)
            n_pred += len(p)
            for thr in (2, 4):
                r, q = match(p, g, ppc, thr)
                acc[thr][0] += r
                acc[thr][1] += q
    m = {}
    for thr in (2, 4):
        rc = acc[thr][0] / max(n_gt, 1)
        pr = acc[thr][1] / max(n_pred, 1)
        m[f"rec{thr}"] = rc
        m[f"prc{thr}"] = pr
        m[f"f1_{thr}"] = 2 * rc * pr / max(rc + pr, 1e-9)
    m["mask_iou"] = iou_n / max(iou_d, 1e-9)
    m["mask_bias_px"] = bias_sum / max(bias_n, 1)
    m["v_per_gt"] = n_pred / max(n_gt, 1)
    m["loss"] = loss_sum / max(nb, 1)
    for k, v in parts_sum.items():
        m["l_" + k] = v / max(nb, 1)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default="../dataset/refined_data/scenes")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=60)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--crop", type=int, default=256)
    ap.add_argument("--out-size", type=int, default=128)
    ap.add_argument("--val-width", type=int, default=725,
                    help="MUST match the tiler's, or stage-1 training pixels "
                         "leak into stage-2 validation")
    ap.add_argument("--encoder", default="resnet18", choices=["resnet18", "simple"])
    ap.add_argument("--no-pretrained", action="store_true")
    ap.add_argument("--dim", type=int, default=128)
    ap.add_argument("--no-edge", action="store_true")
    ap.add_argument("--w-mask", type=float, default=1.0)
    ap.add_argument("--w-vmap", type=float, default=1.0)
    ap.add_argument("--w-voff", type=float, default=1.0)
    ap.add_argument("--w-edge", type=float, default=1.0)
    ap.add_argument("--vertex-thr", type=float, default=0.3)
    ap.add_argument("--merge", type=float, default=1.0,
                    help="collapse decoded peaks closer than this many cells")
    ap.add_argument("--eval-ckpt", metavar="PTH",
                    help="load this checkpoint, run validation once, print the "
                         "metrics and exit. The point is mask_bias_px: it "
                         "decides whether connect.fit_edges is safe (it wins "
                         "under ~2px of systematic bias and loses beyond), and "
                         "otherwise it would only appear on a fresh training "
                         "run.")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    np.random.seed(a.seed)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(vars(a), indent=1))

    edge = not a.no_edge
    tr = PolyDataset(a.data_root, "train", crop=a.crop, out=a.out_size,
                     val_width=a.val_width, augment=True, edge=edge)
    va = PolyDataset(a.data_root, "val", crop=a.crop, out=a.out_size,
                     val_width=a.val_width, augment=False, edge=edge)
    tl = DataLoader(tr, batch_size=a.batch_size, shuffle=True, drop_last=True,
                    num_workers=a.workers, collate_fn=collate,
                    persistent_workers=a.workers > 0)
    vl = DataLoader(va, batch_size=a.batch_size, shuffle=False,
                    num_workers=a.workers, collate_fn=collate,
                    persistent_workers=a.workers > 0)

    model = build(cin=4, dim=a.dim, encoder=a.encoder,
                  pretrained=not a.no_pretrained, edge=edge).to(dev)
    crit = PolyLoss(a.w_mask, a.w_vmap, a.w_voff, a.w_edge).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=a.lr, total_steps=a.epochs * max(len(tl), 1), pct_start=0.1)

    if a.eval_ckpt:
        blob = torch.load(a.eval_ckpt, map_location="cpu", weights_only=False)
        model.load_state_dict(blob["model"])
        m = validate(model, vl, dev, a.vertex_thr, a.merge, crit)
        print(f"[eval] {a.eval_ckpt}  epoch {blob.get('epoch','?')}")
        for k in sorted(m):
            print(f"    {k:14s} {m[k]:.4f}")
        b = m["mask_bias_px"]
        verdict = ("fit_edges is safe" if abs(b) < 1.5 else
                   "fit_edges is marginal -- A/B it" if abs(b) < 2.5 else
                   "run infer.py with --no-fit-edges")
        print()
        print(f"  mask bias {b:+.2f} px  ->  {verdict}")
        return

    best = -1.0
    for ep in range(a.epochs):
        t0 = time.time()
        model.train()
        run, runp, nb = 0.0, {}, 0
        bar = tqdm(tl, desc=f"ep {ep+1}/{a.epochs}", leave=False, dynamic_ncols=True)
        for b in bar:
            x = b["x"].to(dev, non_blocking=True)
            t = {k: v.to(dev, non_blocking=True) for k, v in b["t"].items()}
            L, parts = crit(model(x), t)
            opt.zero_grad(set_to_none=True)
            L.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            sched.step()
            run += float(L)
            nb += 1
            for k, v in parts.items():
                runp[k] = runp.get(k, 0.0) + v
            bar.set_postfix(loss=f"{run/nb:.3f}", refresh=False)
        bar.close()

        m = validate(model, vl, dev, a.vertex_thr, a.merge, crit)
        good = m["f1_2"] > best
        if good:
            best = m["f1_2"]
        print(f"[ep {ep+1}/{a.epochs}] train {run/max(nb,1):.4f} "
              f"({' '.join(f'{k} {v/max(nb,1):.3f}' for k,v in runp.items())}) "
              f"| val {m['loss']:.4f} | F1@2px {m['f1_2']:.4f} "
              f"(rec {m['rec2']:.3f} prc {m['prc2']:.3f}) F1@4px {m['f1_4']:.4f} "
              f"| v/GT {m['v_per_gt']:.2f} | maskIoU {m['mask_iou']:.4f} "
              f"bias {m['mask_bias_px']:+.2f}px "
              f"| {time.time()-t0:.0f}s" + ("  *" if good else ""))

        row = dict(epoch=ep + 1, train=run / max(nb, 1),
                   **{("tr_" + k): v / max(nb, 1) for k, v in runp.items()},
                   **m, is_best=int(good), secs=round(time.time() - t0, 1))
        f = out / "log.csv"
        w_hdr = not f.exists()
        with f.open("a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(row))
            if w_hdr:
                w.writeheader()
            w.writerow(row)

        blob = {"model": model.state_dict(), "cfg": vars(a), "epoch": ep + 1,
                "metrics": m}
        torch.save(blob, out / "last.pth")
        if good:
            torch.save(blob, out / "best.pth")
    print(f"[done] best F1@2px {best:.4f}")


if __name__ == "__main__":
    main()
