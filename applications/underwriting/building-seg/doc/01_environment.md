# 1. Environment setup

Everything needed to run this project on a fresh machine. Follow the steps in
order; each one ends with a check so you know it worked before moving on.

**What you need before starting**

- A Linux machine with an NVIDIA GPU (the project was developed on an RTX A6000,
  48 GB). Stage 1 training needs roughly 40 GB of VRAM at the default settings;
  stage 2 needs about 6 GB.
- Roughly 60 GB of free disk (datasets, checkpoints, and prediction outputs).
- A HuggingFace account. One of the model weights is behind a licence click.

---

## Step 1 — Install Miniconda

Skip if `conda --version` already works.

```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p $HOME/miniconda3
$HOME/miniconda3/bin/conda init bash
exec bash
```

**Check:** `conda --version` prints a version number.

---

## Step 2 — Create the environment

```bash
conda create -n bldseg python=3.10 -y
conda activate bldseg
```

Python **3.10** specifically — the reference environment is 3.10.20, and some
of the pinned packages below have no wheels for newer Pythons.

**Check:** `python --version` prints `Python 3.10.x`.

> From here on, every command assumes `conda activate bldseg` has been run.

---

## Step 3 — Find your CUDA version

```bash
nvidia-smi
```

The top-right of the output says `CUDA Version: 12.x` or similar. Note it —
the next step depends on it.

---

## Step 4 — Install PyTorch

Pick the line matching the CUDA version from step 3:

```bash
# CUDA 12.1
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

```bash
# CUDA 12.4
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
```

```bash
# CPU only -- inference will work but training is impractically slow
pip install torch torchvision
```

The reference environment used torch 2.13.0+cu130. Any torch ≥ 2.0 should work;
match the CUDA build to your driver rather than chasing the exact version.

**Check:**

```bash
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

It must print `True` and your GPU's name. If it prints `False`, the CUDA build
does not match your driver — go back to step 4 and pick a different one.

---

## Step 5 — Install everything else

```bash
pip install "transformers>=4.40" opencv-python pycocotools numpy scipy pillow tqdm
```

What each is for:

| package | used by |
|---|---|
| `transformers` | Mask2Former and DINOv3 model definitions (stage 1) |
| `opencv-python` | contours, polygon rasterisation, all image I/O in the polygon code |
| `pycocotools` | reading and writing COCO annotation files |
| `scipy` | a few geometric helpers in the rule-based polygonizer |
| `pillow` | loading large scene images |
| `tqdm` | progress bars |

**Check:**

```bash
python -c "import cv2, transformers, pycocotools, scipy; print('all imports OK')"
```

> If `pycocotools` fails to build, install the compiler toolchain first:
> `sudo apt-get install -y build-essential python3-dev`, then retry.

---

## Step 6 — Log in to HuggingFace

The DINOv3 backbone is a **gated** model: you must accept its licence on the
web once before any machine can download it.

1. Open <https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m> and
   click to accept the licence.
2. Create a token at <https://huggingface.co/settings/tokens> (read access is
   enough).
3. Log in:

```bash
huggingface-cli login
```

Paste the token when prompted.

**Check:**

```bash
python -c "
from transformers import AutoModel
AutoModel.from_pretrained('facebook/dinov3-vitl16-pretrain-lvd1689m')
print('DINOv3 downloaded OK')"
```

The first run downloads about 1.2 GB and takes a few minutes. Later runs read
from the cache (`~/.cache/huggingface`) and are instant.

---

## Step 7 — Pre-download the other weights

Not strictly required — they download on first use — but doing it now means a
training run does not fail twenty minutes in because the machine was offline.

```bash
python -c "
from transformers import Mask2FormerForUniversalSegmentation
Mask2FormerForUniversalSegmentation.from_pretrained('facebook/mask2former-swin-base-coco-instance')
from torchvision.models import resnet18
resnet18(weights='IMAGENET1K_V1')
print('all weights cached')"
```

Three sets of pretrained weights are used in total:

| weights | role |
|---|---|
| `facebook/dinov3-vitl16-pretrain-lvd1689m` | stage-1 image backbone |
| `facebook/mask2former-swin-base-coco-instance` | stage-1 segmentation head, warm-started from COCO |
| torchvision `resnet18` (ImageNet) | stage-2 crop encoder |

---

## Step 8 — Verify the project itself

```bash
cd /path/to/building_seg/dinov3_poly && python selftest.py
```

Should end with `0 failures`. This needs no GPU, no dataset and no checkpoint —
it is pure geometry and model-shape checking, and it is the fastest way to
confirm the install is sound.

```bash
cd /path/to/building_seg/dinov3_v2 && python selftest.py
```

Same for stage 1.

---

## Step 9 — Check the data is in place

```bash
ls /path/to/building_seg/dataset/refined_data/scenes
```

You should see ten scene folders, each containing one `.png` and one
`annotations.json`. See `02_dataset.md` for what they are and how the training
tiles are generated from them.

---

## Directory layout

```
building_seg/
├── dataset/
│   └── refined_data/
│       ├── scenes/              10 source scenes + refined labels
│       ├── data_stride128_rot/  generated training tiles (train/ and val/)
│       └── tile_to_coco_multi_rot.py
├── dinov3_v2/                   STAGE 1 -- instance segmentation
├── dinov3_poly/                 STAGE 2 -- polygon / vertex head
├── labeler/labeler.html         annotation tool (runs in a browser, no install)
├── SAMPolyBuild/                reference implementation, not used at runtime
└── report/                      this documentation
```

---

## Troubleshooting

**`CUDA out of memory` during stage-1 training.** Lower `--batch-size` to 2, or
`--image-size` to 768. Stage 1 at the defaults wants ~40 GB.

**`torch.cuda.is_available()` is False.** The torch CUDA build does not match
the driver. Reinstall from step 4 using the CUDA version `nvidia-smi` reported.

**`OSError: You are trying to access a gated repo`.** Step 6 was skipped, or the
licence was never accepted on the website. Both are required.

**Training is far slower than expected.** Check `nvidia-smi` for another process
sharing the GPU, and confirm `--workers` is at least 4 so data loading is not
the bottleneck.

**`ModuleNotFoundError` on something that installed fine.** The environment is
not active. Run `conda activate bldseg`.
