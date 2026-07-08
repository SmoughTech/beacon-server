# crowd-counter

A standalone crowd-density counter that estimates how many people are in an
image (works up to very dense crowds via tiling) and **pushes the count + a
heatmap into beacon-server**. This runs *separately* from the server — Beacon
only stores and displays what this sends.

It uses **density-map regression (CSRNet)**, not object detection, because
detectors collapse past a few hundred people. For tens of thousands of people in
one high-resolution frame, inference is **tiled**: the image is split into
overlapping patches, each is counted, and the density maps are stitched back
together (the sum is the total).

## Layout

| File | Purpose |
|------|---------|
| `model.py` | `DensityModel` interface + **CSRNet** implementation + weight loader |
| `fallback.py` | Heuristic estimator that runs with **no weights** (placeholder) |
| `tiling.py` | Overlapping-tile inference + density stitching |
| `pipeline.py` | Image → `count` + normalized heatmap `cells` |
| `beacon_client.py` | Pushes results to beacon-server's contract |
| `run.py` | CLI (single image / folder / repeating interval) |
| `train.py` | Train CSRNet on your point-annotated images |
| `datasets.py` | Convert ShanghaiTech / UCF-QNRF `.mat` annotations into a manifest |
| `selftest.py` | Offline smoke test (no torch, no network) |

## Quick start

```bash
cd crowd-counter
python -m venv .venv && . .venv/Scripts/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 1) Verify the plumbing with zero setup (uses the fallback estimator):
python selftest.py

# 2) Count a real image and print only (no server needed):
python run.py --image crowd.jpg --no-push

# 3) Count and push to Beacon (creates a density source named "North overview"):
python run.py --image crowd.jpg \
  --beacon-url http://localhost:8000 --event-id test_fest \
  --source-name "North overview" --weights csrnet.pth
```

Then open Beacon Dash → **Live Counts**: the density number and heatmap overlay
should appear.

> Without `--weights`, CSRNet runs with only an ImageNet-initialized frontend
> and an **untrained** counting head, so the numbers are meaningless. Either pass
> trained weights, or (with no torch installed) the **fallback** estimator runs —
> also not accurate. Real numbers require training (below).

## Live video / repeating frames

This tool is per-frame; video = run it on frames. Point an RTSP/webcam grabber
(ffmpeg, OpenCV) at a file it overwrites, then:

```bash
python run.py --image latest.jpg --interval 2 \
  --beacon-url http://localhost:8000 --event-id test_fest --source-name "North overview"
```

or process a folder of dumped frames with `--dir ./frames --interval 5`.

## The Beacon contract (what gets sent)

```
POST /events/{event}/count-sources             {"name","kind":"density","zone_id"?}
POST /events/{event}/count-sources/{id}/samples {"heads": <int>, "confidence"?: 0..1}
PUT  /events/{event}/count-sources/{id}/heatmap {"cells":[{"x":0..1,"y":0..1,"w":>=0}, ...]}
```

`x`/`y` are normalized to the image frame. For a fixed overhead camera the frame
*is* the mapped region. For oblique cameras, apply a homography to the cells
before sending so they land correctly on the site map.

## Training on your annotated data

> Training needs an NVIDIA GPU (≥8GB VRAM) to be practical; CPU training is not
> viable. Inference (`run.py`) runs fine on CPU. A common workflow is to train
> in the cloud (Colab/RunPod/Vast/Lambda) or on a desktop GPU, then run inference
> locally.

Density counters are trained on **head-point annotations** (one dot per person).
Put your labels in a JSON manifest (paths are relative to the manifest file):

```json
[
  {"image": "images/frame001.jpg", "points": [[x1, y1], [x2, y2]]},
  {"image": "images/frame002.jpg", "points": [[x, y]]}
]
```

### Building a manifest from a public dataset

`datasets.py` converts ShanghaiTech / UCF-QNRF `.mat` annotations into the
manifest above (and can carve off a deterministic validation split):

```bash
# ShanghaiTech Part B train split, hold out 10% for validation:
python datasets.py --root path/to/ShanghaiTech/part_B/train_data \
  --out data/train.json --val-out data/val.json --val-frac 0.1 --seed 0

# UCF-QNRF:
python datasets.py --root path/to/UCF-QNRF/Train --out data/train.json
```

### Running training

```bash
python train.py --manifest data/train.json --val data/val.json \
  --epochs 100 --sigma 15 --crop 512 --out csrnet.pth

# Fine-tune an existing checkpoint on in-domain frames (lower LR):
python train.py --manifest data/festival.json --resume csrnet.pth \
  --lr 1e-6 --epochs 30 --out csrnet_festival.pth
```

`train.py` builds Gaussian density targets, shuffles each epoch, augments with
random `--crop`-sized patches (aligned to the model stride; `--crop 0` = full
image) and horizontal flips (`--flip-prob`), trains CSRNet, and (with `--val`)
saves the best model by MAE. `--seed` makes runs reproducible; `--resume` loads
weights to continue/fine-tune.

### Training in the cloud (RunPod)

No local GPU? [`cloud/RUNPOD.md`](cloud/RUNPOD.md) is a step-by-step guide, and
[`cloud/runpod_train.sh`](cloud/runpod_train.sh) is a one-command, spot-safe
bootstrap that installs deps, builds the manifest, smoke-tests, and trains
(auto-resuming if the pod restarts). A full run is a few hours for a few dollars.

Tips:
- **Match the deployment domain.** Fine-tune on frames that look like the CCTV
  you'll run on (angle, resolution, lighting). A few hundred in-domain frames
  beat thousands of mismatched ones.
- Pre-train on a public dense set (NWPU-Crowd, UCF-QNRF) then fine-tune on yours
  for best accuracy at extreme density.
- If your labels are ShanghaiTech `.mat`, convert head coords into the manifest
  format above.

## Tuning inference

- `--tile-size` / `--overlap`: smaller tiles resolve smaller heads (denser
  crowds) at the cost of speed. Start 1024 / 128.
- `--grid-cols` / `--grid-rows`: heatmap resolution sent to Beacon (default
  48×27, i.e. 16:9).
- `--device cuda` for GPU.

## Limitations

- Stitching holds a full 1/8-resolution canvas in memory — fine for normal and
  4K frames; true gigapixel input would want streamed tiles.
- Expect ±5–15% error at extreme density even when well trained. Great for
  safety/operations, not ticket-grade headcounts — which is why Beacon treats
  this as a **cross-check** against the auditable gate ledger.
