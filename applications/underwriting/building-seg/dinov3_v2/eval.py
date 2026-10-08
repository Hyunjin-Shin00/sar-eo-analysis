"""
eval_masks.py -- instance-segmentation metrics for building masks.

Compares predictions against COCO ground truth from tile_to_coco_v2.py.
Accepts two prediction formats so different models can be scored identically:

  --npz  DIR    folder of *_masks.npz from infer_dinov3_mask2former.py
                (boxes / scores / shape / m0..mN cropped boolean masks)
  --json FILE   COCO-results list, RLE segmentation, string image_id
                (SAMPolyBuild output)

    python eval_masks.py --gt data/val/annotations.json \\
        --npz preds_convnext/ --name convnext \\
        --json sampoly_results.json --name sampoly

Metrics:
  COCO mask AP          the standard for instance segmentation. Integrates over
                        confidence, so it penalises BOTH missed buildings and
                        false positives -- which an IoU-on-matched-pairs number
                        cannot do.
  Boundary IoU          IoU restricted to a band around each contour. Mask IoU
                        is nearly blind to the errors that matter here: a 2 px
                        inward shift scores 0.98 mask IoU but 0.33 boundary IoU,
                        and boundary IoU is size-invariant where mask IoU is not.
  size buckets          both COCO's (32^2 / 96^2) and custom ones, because the
                        COCO cut lumps 100 px slivers together with 1000 px
                        workshops.
  P / R / F1 @ 0.5      separates "misses buildings" from "invents buildings".
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from pycocotools import mask as maskutil
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def stem_to_id(coco):
    """GT file_name stem -> COCO image id, for string-keyed predictions."""
    return {Path(v["file_name"]).stem: k for k, v in coco.imgs.items()}


def rle_of(mask):
    r = maskutil.encode(np.asfortranarray(mask.astype(np.uint8)))
    r["counts"] = r["counts"].decode("ascii")
    return r


def load_npz(folder, s2i, score_key="scores"):
    """
    infer.py --save-masks -> COCO results.

    `score_key` picks which stored component ranks the predictions, so a
    ranking can be A/B'd without re-running the model: "scores" (whatever
    --score-mode produced), "pred_iou" (the v2 head alone), "cls_scores",
    "mask_quality". AP is a function of the RANKING, so this is not cosmetic --
    on the v1 model the same masks scored AP 0.378 by cls x mq, 0.364 by cls
    alone, and 0.508 by true IoU.

    A missing key is fatal rather than a silent fall back to "scores": that
    fallback would report v1's ranking under a v2 label, and the numbers look
    perfectly plausible either way.
    """
    out, skipped = [], []
    files = sorted(Path(folder).glob("*.npz"))
    if files and score_key != "scores":
        have = np.load(files[0]).files
        if score_key not in have:
            raise SystemExit(
                f"--score-key '{score_key}' not in {files[0].name}; "
                f"available: {[k for k in have if not k.startswith('m')]}")
    for f in files:
        stem = f.stem[:-6] if f.stem.endswith("_masks") else f.stem
        if stem not in s2i:
            skipped.append(stem)
            continue
        iid = s2i[stem]
        z = np.load(f)
        H, W = (int(v) for v in z["shape"])
        b = z["boxes"]
        sc = z[score_key] if score_key in z.files else z["scores"]
        for i in range(len(sc)):
            m = np.zeros((H, W), np.uint8)
            m[int(b[i][1]):int(b[i][3]), int(b[i][0]):int(b[i][2])] = z[f"m{i}"]
            if m.sum() == 0:
                continue
            x, y, w, h = maskutil.toBbox(rle_of(m)).tolist()
            out.append({"image_id": iid, "category_id": 1,
                        "segmentation": rle_of(m), "score": float(sc[i]),
                        "bbox": [x, y, w, h], "area": int(m.sum())})
    return out, skipped


def load_json(path, s2i, score_key="score"):
    """
    SAMPolyBuild-style COCO results. image_id is a filename stem, so it has to
    be remapped to the GT integer id -- pycocotools matches on id, and a
    mismatch silently yields AP 0 rather than an error.
    """
    raw = json.loads(Path(path).read_text())
    if isinstance(raw, dict) and "annotations" in raw:
        raw = raw["annotations"]
    out, skipped = [], []
    for d in raw:
        key = d["image_id"]
        iid = key if isinstance(key, int) and key in s2i.values() else \
            s2i.get(str(key), s2i.get(Path(str(key)).stem))
        if iid is None:
            skipped.append(str(key))
            continue
        seg = d["segmentation"]
        if isinstance(seg, dict) and isinstance(seg.get("counts"), list):
            seg = maskutil.frPyObjects(seg, seg["size"][0], seg["size"][1])
        e = {"image_id": iid, "category_id": 1, "segmentation": seg,
             "score": float(d.get(score_key, d.get("score", 1.0)))}
        if "bbox" in d:
            e["bbox"] = [float(v) for v in d["bbox"]]
        out.append(e)
    return out, sorted(set(skipped))


def decode(seg, H, W):
    if isinstance(seg, dict):
        s = dict(seg)
        if isinstance(s.get("counts"), str):
            s["counts"] = s["counts"].encode("ascii")
        return maskutil.decode(s).astype(bool)
    rles = maskutil.frPyObjects(seg, H, W)
    return maskutil.decode(maskutil.merge(rles)).astype(bool)


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def boundary_d(shape, dilation_ratio=0.02, abs_d=None):
    """
    Band half-width. The paper scales it to the image diagonal (ratio 0.02),
    NOT a fixed pixel count -- on a 512 tile that is 14 px, and the score is
    extremely sensitive to it: the same 3 px inward shift scores 0.000 at d=3
    and 0.647 at d=14. A Boundary IoU without its d is not comparable to
    anything.
    """
    if abs_d:
        return max(int(abs_d), 1)
    h, w = shape[:2]
    return max(int(round(dilation_ratio * float(np.sqrt(h * h + w * w)))), 1)


def boundary_band(mask, d):
    """
    G_d intersect G, i.e. mask minus its erosion.

    The 1 px zero-pad before eroding is the reference implementation's, and it
    matters here: without it cv2.erode treats outside the array as foreground,
    so a building CLIPPED BY THE TILE EDGE does not get that edge counted as
    boundary. Measured on a border-touching mask: 6608 px without the pad vs
    9016 px with it. tile_to_coco_v2 clips at tile boundaries, so a real
    fraction of instances are affected.
    """
    m = mask.astype(np.uint8)
    h, w = m.shape
    p = cv2.copyMakeBorder(m, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    er = cv2.erode(p, np.ones((3, 3), np.uint8), iterations=d)[1:h + 1, 1:w + 1]
    return (m - er).astype(bool)


def boundary_iou(gt, pr, d):
    g, p = boundary_band(gt, d), boundary_band(pr, d)
    u = np.logical_or(g, p).sum()
    return float(np.logical_and(g, p).sum() / u) if u else 0.0


def mask_iou(a, b):
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 0.0


def match_and_score(coco, preds, iou_thr=0.5, dilation_ratio=0.02,
                    abs_d=None, score_thr=0.0, crowd_ios_thr=0.5,
                    buckets=((0, 800), (800, 2000), (2000, 5000), (2000 ** 2, ))):
    """
    Greedy matching at iou_thr, highest score first, then per-pair Boundary IoU
    and counts. Separate from COCOeval because AP integrates over confidence
    and cannot report a boundary number or a plain P/R at one threshold.
    """
    by_img = defaultdict(list)
    for p in preds:
        if p["score"] >= score_thr:
            by_img[p["image_id"]].append(p)

    tp = fp = fn = ign = 0
    m_ious, b_ious, areas = [], [], []
    for iid, info in coco.imgs.items():
        H, W = info["height"], info["width"]
        gts = [decode(a["segmentation"], H, W)
               for a in coco.loadAnns(coco.getAnnIds(iid, iscrowd=False))
               if a.get("segmentation")]
        # TIER 0. Crowd regions are IGNORE regions, not background. Without
        # this, a prediction landing on one is charged as a false positive even
        # though the GT deliberately declines to say what is there -- which is
        # exactly what COCOeval does NOT do, so the AP above and the precision
        # below were measuring different things. Measured on the v1 model: 138
        # of 706 "false positives" (20%) were this, and precision was
        # understated at 0.615 against a true ~0.66.
        crowd = [decode(a["segmentation"], H, W)
                 for a in coco.loadAnns(coco.getAnnIds(iid, iscrowd=True))
                 if a.get("segmentation")]
        ps = sorted(by_img.get(iid, []), key=lambda d: -d["score"])
        pm = [decode(p["segmentation"], H, W) for p in ps]
        used = set()
        for k, pmask in enumerate(pm):
            best, bi = 0.0, -1
            for j, g in enumerate(gts):
                if j in used:
                    continue
                v = mask_iou(g, pmask)
                if v > best:
                    best, bi = v, j
            if best >= iou_thr:
                used.add(bi)
                tp += 1
                m_ious.append(best)
                b_ious.append(boundary_iou(gts[bi], pmask,
                                           boundary_d((H, W), dilation_ratio, abs_d)))
                areas.append(int(gts[bi].sum()))
            else:
                # Intersection over the PREDICTION's own area, not IoU: a
                # crowd region is typically far larger than one building, so
                # IoU stays low even when the prediction is entirely inside it.
                a_p = max(int(pmask.sum()), 1)
                if crowd and max(int(np.logical_and(pmask, c).sum())
                                 for c in crowd) / a_p >= crowd_ios_thr:
                    ign += 1
                else:
                    fp += 1
        fn += len(gts) - len(used)

    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    res = {"TP": tp, "FP": fp, "FN": fn, "ignored_crowd": ign,
           "precision": prec, "recall": rec,
           "f1": 2 * prec * rec / max(prec + rec, 1e-9),
           "mask_iou": float(np.mean(m_ious)) if m_ious else 0.0,
           "boundary_iou": float(np.mean(b_ious)) if b_ious else 0.0}

    areas = np.array(areas)
    b = np.array(b_ious)
    mi = np.array(m_ious)
    res["by_size"] = []
    for k, rng in enumerate(buckets):
        lo = rng[0] if len(rng) > 1 else buckets[k - 1][1]
        hi = rng[1] if len(rng) > 1 else 10 ** 12
        sel = (areas >= lo) & (areas < hi)
        res["by_size"].append({
            "range": f"{lo}-{hi if hi < 10**11 else 'inf'}",
            "n": int(sel.sum()),
            "mask_iou": float(mi[sel].mean()) if sel.any() else 0.0,
            "boundary_iou": float(b[sel].mean()) if sel.any() else 0.0})
    return res


def boundary_ap(coco, preds, dilation_ratio=0.02, abs_d=None,
                area_rng=None, labels=None):
    """
    Boundary AP: AP with Boundary IoU as the matching criterion.

    This is the publishable form. The matched-pair Boundary IoU average
    reported alongside is conditioned on a successful match, so it ignores
    misses and false positives entirely -- two models can tie on it while one
    finds half the buildings.

    Implemented by overriding COCOeval.computeIoU, which is the single place
    the IoU matrix is produced. The paper's own release does the same.
    """
    if not preds:
        return {}
    dt = coco.loadRes([dict(p) for p in preds])
    e = COCOeval(coco, dt, iouType="segm")
    if area_rng is not None:
        e.params.areaRng = area_rng
        e.params.areaRngLbl = labels

    def compute_boundary_iou(imgId, catId):
        p = e.params
        gt = e._gts[imgId, catId]
        d_ = e._dts[imgId, catId]
        if len(gt) == 0 or len(d_) == 0:
            return []
        inds = np.argsort([-x["score"] for x in d_], kind="mergesort")
        d_ = [d_[i] for i in inds][:p.maxDets[-1]]
        info = coco.imgs[imgId]
        H, W = info["height"], info["width"]
        dd = boundary_d((H, W), dilation_ratio, abs_d)
        gm = [boundary_band(decode(g["segmentation"], H, W), dd) for g in gt]
        dm = [boundary_band(decode(x["segmentation"], H, W), dd) for x in d_]
        out = np.zeros((len(dm), len(gm)))
        for i, a in enumerate(dm):
            for j, b in enumerate(gm):
                u = np.logical_or(a, b).sum()
                out[i, j] = np.logical_and(a, b).sum() / u if u else 0.0
        return out

    e.computeIoU = compute_boundary_iou
    e.evaluate(); e.accumulate()
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        e.summarize()
    ks = ["BAP", "BAP50", "BAP75", "BAP_S", "BAP_M", "BAP_L",
          "BAR1", "BAR10", "BAR100", "BAR_S", "BAR_M", "BAR_L"]
    return {k: float(v) for k, v in zip(ks, e.stats)}


def coco_ap(coco, preds, area_rng=None, labels=None):
    if not preds:
        return {}
    dt = coco.loadRes([dict(p) for p in preds])
    e = COCOeval(coco, dt, iouType="segm")
    if area_rng is not None:
        e.params.areaRng = area_rng
        e.params.areaRngLbl = labels
    e.evaluate(); e.accumulate()
    import io, contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        e.summarize()
    s = e.stats
    keys = ["AP", "AP50", "AP75", f"AP_{labels[1]}" if labels else "AP_S",
            f"AP_{labels[2]}" if labels else "AP_M",
            f"AP_{labels[3]}" if labels else "AP_L",
            "AR1", "AR10", "AR100",
            f"AR_{labels[1]}" if labels else "AR_S",
            f"AR_{labels[2]}" if labels else "AR_M",
            f"AR_{labels[3]}" if labels else "AR_L"]
    return {k: float(v) for k, v in zip(keys, s)}


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", required=True, help="COCO annotations.json")
    ap.add_argument("--npz", action="append", default=[],
                    help="repeatable: folder of *_masks.npz")
    ap.add_argument("--json", action="append", default=[],
                    help="repeatable: COCO-results json (SAMPolyBuild style)")
    ap.add_argument("--name", action="append", default=[],
                    help="label per prediction source, in the order given "
                         "(--npz first, then --json)")
    ap.add_argument("--iou-thr", type=float, default=0.5)
    ap.add_argument("--crowd-ios-thr", type=float, default=0.5,
                    help="TIER 0. An unmatched prediction whose own area is at "
                         "least this fraction inside an iscrowd region is "
                         "IGNORED rather than counted as a false positive -- "
                         "COCOeval's semantics, which the P/R/F1 block did not "
                         "previously follow. 1.1 restores the old behaviour.")
    ap.add_argument("--dilation-ratio", type=float, default=0.02,
                    help="boundary band width as a fraction of the image "
                         "diagonal, per Cheng et al. 0.02 -> 14px on a 512 "
                         "tile. Always state this alongside any Boundary "
                         "number; the score is very sensitive to it.")
    ap.add_argument("--boundary-px", type=int, default=None,
                    help="override the band with an absolute pixel width. "
                         "Diagnostic only -- not comparable to published values.")
    ap.add_argument("--score-thr", type=float, default=0.0,
                    help="for P/R/F1 only; AP always integrates all scores")
    ap.add_argument("--score-key", action="append", default=[],
                    help="REPEATABLE, paired with the sources in order exactly "
                         "like --name. Which stored field ranks the "
                         "predictions: npz -> scores (default) | pred_iou | "
                         "cls_scores | mask_quality; json -> score. Give one "
                         "key to apply it to every source, or one per source "
                         "to compare rankings over the SAME masks. AP is a "
                         "function of the ranking, so this changes AP a lot.")
    ap.add_argument("--out", default=None, help="write results as json")
    a = ap.parse_args()

    coco = COCO(a.gt)
    s2i = stem_to_id(coco)
    n_gt = sum(len(coco.getAnnIds(i, iscrowd=False)) for i in coco.imgs)
    print(f"[gt] {len(coco.imgs)} images, {n_gt} annotations")

    sources = [("npz", p) for p in a.npz] + [("json", p) for p in a.json]
    names = list(a.name) + [Path(p).name for _, p in sources[len(a.name):]]

    # --score-key is paired with the sources IN ORDER, like --name. It used to
    # be a single value, which made the obvious head-to-head command silently
    # meaningless: two --score-key flags left only the last one, both sources
    # were ranked identically, and all 14 metrics came out byte-identical --
    # which reads as "the ranking does not matter" rather than "the comparison
    # never happened".
    keys = list(a.score_key)
    if len(keys) > 1 and len(keys) != len(sources):
        raise SystemExit(
            f"[fatal] {len(keys)} --score-key values for {len(sources)} "
            f"sources. Give one (applied to all) or one per source, in order.")

    def key_for(i, kind):
        if not keys:
            return "scores" if kind == "npz" else "score"
        return keys[i] if len(keys) == len(sources) else keys[0]

    all_res = {}
    for i, ((kind, path), name) in enumerate(zip(sources, names)):
        key = key_for(i, kind)
        if kind == "npz":
            preds, skipped = load_npz(path, s2i, key)
        else:
            preds, skipped = load_json(path, s2i, key)
        imgs = {p["image_id"] for p in preds}
        print(f"\n=== {name}  ({kind}: {path}) ===")
        # the key is printed because two sources can now legitimately be the
        # SAME folder, and then it is the only thing telling them apart
        print(f"  ranked by: {key}")
        print(f"  {len(preds)} predictions over {len(imgs)}/{len(coco.imgs)} GT images")
        if skipped:
            print(f"  [warn] {len(skipped)} unmatched image keys, e.g. {skipped[:3]}")
        if len(imgs) < len(coco.imgs):
            print(f"  [warn] {len(coco.imgs)-len(imgs)} GT images have NO prediction; "
                  f"they count against recall")
        if not preds:
            print("  no usable predictions, skipping")
            continue

        std = coco_ap(coco, preds)
        # COCOeval.summarize() looks up area ranges by the LABEL STRINGS
        # 'small'/'medium'/'large'. Renaming them makes every custom bucket
        # report -1. So keep the labels and change only the boundaries.
        custom = coco_ap(
            coco, preds,
            area_rng=[[0, 1e10], [0, 800], [800, 5000], [5000, 1e10]],
            labels=["all", "small", "medium", "large"])
        det = match_and_score(coco, preds, a.iou_thr, a.dilation_ratio,
                              a.boundary_px, a.score_thr, a.crowd_ios_thr)
        bap = boundary_ap(coco, preds, a.dilation_ratio, a.boundary_px)

        print(f"  COCO mask AP   {std.get('AP',0):.4f}  "
              f"AP50 {std.get('AP50',0):.4f}  AP75 {std.get('AP75',0):.4f}")
        def _f(v):
            return "n/a" if v is None or v < 0 else f"{v:.4f}"
        print(f"  COCO buckets   AP_S {_f(std.get('AP_S'))}  "
              f"AP_M {_f(std.get('AP_M'))}  AP_L {_f(std.get('AP_L'))}")
        print(f"  custom buckets <800px {_f(custom.get('AP_small'))}  "
              f"800-5000 {_f(custom.get('AP_medium'))}  "
              f">5000 {_f(custom.get('AP_large'))}")
        print(f"  AR100          {std.get('AR100',0):.4f}")
        print(f"  Boundary AP    {bap.get('BAP',0):.4f}  "
              f"BAP50 {bap.get('BAP50',0):.4f}  BAP75 {bap.get('BAP75',0):.4f}"
              f"   (d = {boundary_d((512,512), a.dilation_ratio, a.boundary_px)}px on a 512 tile)")
        print(f"  @IoU {a.iou_thr}: P {det['precision']:.4f}  R {det['recall']:.4f}  "
              f"F1 {det['f1']:.4f}   TP {det['TP']} FP {det['FP']} FN {det['FN']}"
              f"  (+{det['ignored_crowd']} ignored on crowd)")
        print(f"  matched pairs: mask IoU {det['mask_iou']:.4f}  "
              f"Boundary IoU {det['boundary_iou']:.4f}")
        print(f"  {'GT area':>14s} {'n':>6s} {'maskIoU':>9s} {'bndIoU':>9s}")
        for r in det["by_size"]:
            print(f"  {r['range']:>14s} {r['n']:6d} {r['mask_iou']:9.4f} "
                  f"{r['boundary_iou']:9.4f}")
        all_res[name] = {"coco": std, "coco_custom": custom,
                         "boundary": bap, "detection": det}

    if len(all_res) > 1:
        print("\n=== head to head ===")
        ns = list(all_res)
        rows = [("AP", lambda r: r["coco"].get("AP", 0)),
                ("AP50", lambda r: r["coco"].get("AP50", 0)),
                ("AP75", lambda r: r["coco"].get("AP75", 0)),
                ("AP <800px", lambda r: r["coco_custom"].get("AP_small", 0)),
                ("AP 800-5000px", lambda r: r["coco_custom"].get("AP_medium", 0)),
                ("AP >5000px", lambda r: r["coco_custom"].get("AP_large", 0)),
                ("AR100", lambda r: r["coco"].get("AR100", 0)),
                ("Boundary AP", lambda r: r["boundary"].get("BAP", 0)),
                ("Boundary AP50", lambda r: r["boundary"].get("BAP50", 0)),
                ("precision", lambda r: r["detection"]["precision"]),
                ("recall", lambda r: r["detection"]["recall"]),
                ("F1", lambda r: r["detection"]["f1"]),
                ("mask IoU", lambda r: r["detection"]["mask_iou"]),
                ("Boundary IoU", lambda r: r["detection"]["boundary_iou"])]
        w = max(len(n) for n in ns) + 2
        print("  " + f"{'metric':>18s}" + "".join(f"{n:>{w}s}" for n in ns))
        for lbl, fn in rows:
            vals = [fn(all_res[n]) for n in ns]
            # COCOeval returns -1 for a bucket with no ground truth; printing it
            # as a score invites reading "-1.0000" as a result.
            if all(v < 0 for v in vals):
                print(f"  {lbl:>18s}" + "".join(f"{'n/a':>{w}s}" for _ in vals))
                continue
            best = max(range(len(vals)), key=lambda i: vals[i])
            cells = "".join(f"{v:>{w}.4f}" if i != best else
                            f"{('*%.4f' % v):>{w}s}" for i, v in enumerate(vals))
            print(f"  {lbl:>18s}{cells}")
        print("  (* = better; note AP and recall can disagree -- a model may "
              "localise well and still miss buildings)")

    if a.out:
        Path(a.out).write_text(json.dumps(all_res, indent=1))
        print(f"\n[save] {a.out}")


if __name__ == "__main__":
    main()