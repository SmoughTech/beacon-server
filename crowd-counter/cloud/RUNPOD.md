# Training CSRNet on RunPod

CSRNet is a light workload — a single mid-range GPU trains it in a few hours for
well under ~$10 total. This guide provisions a pod, gets your dataset on it, and
runs [`runpod_train.sh`](./runpod_train.sh), which bootstraps deps, builds the
manifest, smoke-tests, and trains (auto-resuming if interrupted).

## 1. Create the pod

On <https://runpod.io> → **Deploy**:

- **GPU:** RTX 4090 or A10 / L4 (16–24GB). Even a T4 works. **Don't** rent an
  A100/H100 — wasted money for CSRNet.
- **Template:** an official **PyTorch** image (torch + CUDA preinstalled). The
  script won't clobber it.
- **Volume:** attach a **persistent volume mounted at `/workspace`** (~20–50GB;
  holds the dataset + checkpoints and survives restarts). This is what makes
  cheap/interruptible instances safe.
- Enable **SSH** (and Jupyter if you like).

## 2. Get the code + dataset onto the pod

SSH in, then:

```bash
cd /workspace
git clone <your beacon-server repo>
cd beacon-server/crowd-counter
```

Get a point-annotated dataset. **ShanghaiTech Part B** is the closest public
analog to fixed festival CCTV. Easiest is Kaggle:

```bash
pip install -q kaggle
# New-style Kaggle token: set it as an env var (ideally a RunPod Secret, so it
# is never written to disk or committed). Do NOT paste it into a tracked file.
export KAGGLE_API_TOKEN=<your-token>
kaggle datasets download -d tthien/shanghaitech -p /workspace --unzip
# -> /workspace/ShanghaiTech/part_B/train_data/{images,ground-truth}
```

If you have the older `kaggle.json` (username + key) instead, use
`mkdir -p ~/.kaggle && cp kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json`.
Either way, treat the token like a password — rotate it if it ever leaks. Any
other point-annotated dataset works too; see the layout notes in `datasets.py`.

## 3. Train

```bash
# recommended: run inside tmux so an SSH disconnect won't kill training
tmux new -s train

DATASET_ROOT=/workspace/ShanghaiTech/part_B/train_data \
WORKDIR=/workspace/cc \
EPOCHS=200 CROP=512 \
bash cloud/runpod_train.sh
```

The script will:
1. install `numpy pillow requests scipy` (and torch only if missing),
2. build `data/train.json` + `data/val.json` (10% val by default),
3. run `selftest.py` and a **1-epoch smoke test**,
4. train for `EPOCHS`, saving the **best-by-MAE** checkpoint to
   `$WORKDIR/csrnet.pth` and streaming logs to `$WORKDIR/train.log`.

Detach from tmux with `Ctrl-b d`; reattach with `tmux attach -t train`.

### If the pod restarts (spot reclaim, etc.)

Just re-run the same command. Because the checkpoint lives on `/workspace`, the
script detects it and **resumes** via `--resume` automatically.

## 4. Bring the model home

```bash
# from the pod:
runpodctl send /workspace/cc/csrnet.pth
# or from your PC:
scp <pod-ssh-host>:/workspace/cc/csrnet.pth ./csrnet.pth
```

Then run inference locally (CPU is fine):

```bash
python run.py --image crowd.jpg --weights csrnet.pth --no-push
```

## Knobs (env vars for `runpod_train.sh`)

| Var | Default | Notes |
|-----|---------|-------|
| `DATASET_ROOT` | — | Path to images + `.mat` (required unless `DATASET_URL`) |
| `DATASET_URL` | — | Archive to download+extract instead |
| `WORKDIR` | crowd-counter dir | Put this on `/workspace` for persistence |
| `EPOCHS` | 200 | ShanghaiTech-scale trains fine at 100–400 |
| `CROP` | 512 | Random crop px (0 = full image); lower to cut VRAM |
| `SIGMA` | 15 | Gaussian target sigma (px) |
| `LR` | 1e-5 | Use `1e-6` when fine-tuning via `--resume` |
| `VAL_FRAC` | 0.1 | Validation holdout fraction |
| `SMOKE` | 1 | Set `0` to skip the pre-run checks |
| `FORCE` | 0 | Set `1` to rebuild manifests |

## Fine-tuning to your actual cameras

Once you have festival frames annotated (a few hundred is plenty), fine-tune the
public-data model instead of training from scratch:

```bash
DATASET_ROOT=/workspace/festival_frames WORKDIR=/workspace/cc \
OUT=/workspace/cc/csrnet_festival.pth LR=1e-6 EPOCHS=40 \
bash cloud/runpod_train.sh
# (place the base csrnet.pth at $OUT first so the script resumes from it)
```

> Cost/time: expect a few hours and a few dollars for a full run. The script is
> written but not yet runtime-tested from this workstation — the built-in smoke
> tests (step 3) are your first real validation on the pod.
