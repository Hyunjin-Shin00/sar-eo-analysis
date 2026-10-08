"""`build_model` 의 **오프라인 쌍둥이** — 허깅페이스에 나가지 않고 같은 구조를 세운다.

원본([[train_dinov3_mask2former.py]] `build_model`)은 구조를 세울 때 가중치를 함께 받아 온다.

    Mask2FormerForUniversalSegmentation.from_pretrained("facebook/mask2former-…")
    AutoModel.from_pretrained("facebook/dinov3-vitl16-pretrain-lvd1689m")

학습에서는 그게 맞다 — COCO 로 미리 학습된 머리에서 출발하는 것이 설계의 핵심이고, 동결
백본은 그 가중치가 전부다. 그런데 **추론에서는 그 가중치가 한 줄도 쓰이지 않는다**: 바로
다음 줄에서 체크포인트가 전부 덮어쓴다(`load_state_dict`). 우리 체크포인트는 동결 백본까지
포함한 790개 텐서 1.32 GB 전부를 담고 있다.

그래서 여기서는 **설정만** 읽어 구조를 세우고(`from_config`), 가중치는 체크포인트에서만
가져온다. 얻는 것 둘.

  · **밖으로 나가지 않는다.** DINOv3 저장소는 gated 라 토큰이 있어야 받아지는데, 이 폴더는
    토큰 없이도 돌아야 한다(그것이 벤더링의 이유다).
  · **틀리면 조용히 넘어가지 않는다.** 구조가 학습 때와 한 군데라도 다르면 `strict=True`
    적재가 그 자리에서 터진다 — 이름이든 모양이든. `from_pretrained` 경로는 사전학습
    가중치로 그 자리를 채워 버리므로 같은 실수가 「조금 나쁜 결과」로 나타난다.

설정 두 벌은 `hf/` 에 그대로 담아 두었다(각각 몇 KB · 가중치는 담지 않는다).

**구조를 만드는 순서는 원본과 같다** — 그 순서가 결과를 바꾸는 자리가 있다(질의 확장은
백본 교체 전에, mask-IoU 머리는 맨 뒤에). 원본의 `build_model` 을 옆에 놓고 읽으세요.
"""
from __future__ import annotations

from pathlib import Path

import torch
from transformers import (AutoConfig, AutoModel, Mask2FormerConfig,
                          Mask2FormerForUniversalSegmentation)

from heads import attach_maskiou_head
from train_dinov3_mask2former import (DINOv3ConvNeXtPyramid, DINOv3Pyramid,
                                      expand_queries, resolve_taps)

HERE = Path(__file__).resolve().parent
HF = HERE / "hf"
DINOV3_DIR = HF / "dinov3-vitl16-pretrain-lvd1689m"
M2F_DIR = HF / "mask2former-swin-base-coco-instance"


def _local(model_id, default_dir):
    """모델 id → 담아 둔 설정 폴더. 폴더 경로를 그대로 준 경우도 받는다."""
    p = Path(model_id)
    if p.is_dir():
        return p
    if not default_dir.exists():
        raise FileNotFoundError(
            f"설정을 담아 둔 폴더가 없다: {default_dir}\n"
            f"  hf/<모델>/config.json 이 있어야 구조를 세울 수 있습니다")
    return default_dir


def build_model(dinov3_id, m2f_id, num_labels=1, image_size=512,
                backbone="auto", use_stem=True, num_queries=None,
                unfreeze_last=0, taps="off", maskiou=True,
                maskiou_hidden=256):
    """원본 `build_model` 과 **같은 구조**를 세운다. 가중치는 넣지 않는다(무작위 초기값).

    인자는 원본과 한 글자도 다르지 않다 — `infer.py` 가 체크포인트의 `cfg` 를 그대로 넘겨
    부르므로 서명이 갈리면 그 자리에서 어긋난다.
    """
    m2f_cfg = Mask2FormerConfig.from_pretrained(_local(m2f_id, M2F_DIR),
                                                num_labels=num_labels)
    model = Mask2FormerForUniversalSegmentation(m2f_cfg)

    # 미리 학습된 픽셀 디코더가 몇 채널을 기다리는지 — **모양만** 보는 것이라 무작위
    # 가중치로도 같은 답이 나온다(Swin-B → [128, 256, 512, 1024]).
    probe = torch.randn(1, 3, image_size, image_size)
    with torch.no_grad():
        ch = [f.shape[1]
              for f in model.model.pixel_level_module.encoder(probe).feature_maps]
    print(f"[build] pixel decoder expects channels {ch}")

    if num_queries and num_queries != model.config.num_queries:
        expand_queries(model, num_queries)

    if backbone == "auto":
        backbone = "convnext" if "convnext" in str(dinov3_id).lower() else "vit"
    print(f"[build] backbone type: {backbone}")

    net = AutoModel.from_config(AutoConfig.from_pretrained(_local(dinov3_id, DINOV3_DIR)))

    if backbone == "convnext":
        dims = list(net.config.hidden_sizes)
        print(f"[build] ConvNeXt stage dims {dims} -> strides 4/8/16/32")
        if taps not in (None, "off"):
            print("[warn] --taps is ViT-only; ignored for a ConvNeXt backbone")
        model.model.pixel_level_module.encoder = DINOv3ConvNeXtPyramid(
            net, ch, freeze=True)
    else:
        embed_dim = net.config.hidden_size
        patch = getattr(net.config, "patch_size", 16)
        print(f"[build] ViT hidden={embed_dim} patch={patch} "
              f"stem={'on' if use_stem else 'off'}")
        model.model.pixel_level_module.encoder = DINOv3Pyramid(
            net, ch, embed_dim, patch_size=patch, freeze_vit=True,
            use_stem=use_stem, unfreeze_last=unfreeze_last,
            taps=resolve_taps(net, taps))

    if maskiou:
        attach_maskiou_head(model, hidden=maskiou_hidden)
    return model


def load(ckpt_path, device="cuda", verbose=True):
    """체크포인트 → (model, cfg). **적재는 엄격하게 한다.**

    `infer.py main()` 은 `strict=False` 로 적재한 뒤 백본(`…encoder.vit.`)만 빼고 어긋난
    이름이 있으면 터뜨린다 — 백본을 예외로 두는 이유는 그 경로에서는 백본이 이미
    `from_pretrained` 로 채워져 있어 체크포인트에 없어도 되기 때문이다.

    여기서는 **백본도 체크포인트에서 온다.** 그러니 예외를 둘 이유가 없고, 두면 안 된다 —
    동결 백본이 무작위 초기값으로 남아도 「어긋난 이름 0개」로 보이기 때문이다. 그래서
    `strict=True` 다. 이 한 줄이 오프라인으로 세운 구조가 학습 때와 같다는 증명이다.
    """
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    cfg = ck.get("cfg") or {}
    if not cfg:
        raise SystemExit(f"체크포인트에 'cfg' 가 없다: {ckpt_path} — 구조를 알 수 없다")
    model = build_model(cfg.get("dinov3", str(DINOV3_DIR)),
                        cfg.get("m2f", str(M2F_DIR)),
                        num_labels=1,
                        image_size=cfg.get("image_size", 512),
                        backbone=cfg.get("backbone", "auto"),
                        use_stem=cfg.get("use_stem", True),
                        num_queries=cfg.get("num_queries"),
                        taps=cfg.get("taps", "off"),
                        maskiou=cfg.get("maskiou", False),
                        maskiou_hidden=cfg.get("maskiou_hidden", 256))
    model.load_state_dict(ck.get("model", ck), strict=True)
    if verbose:
        print(f"[load] {Path(ckpt_path).name} epoch={ck.get('epoch', '?')} "
              f"val={ck.get('val', '?')} val_ap={ck.get('val_ap', '?')} "
              f"· 가중치 {len(ck.get('model', ck))}개 전부 일치")
    return model.to(device).eval(), cfg
