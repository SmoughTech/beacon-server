#!/usr/bin/env bash
# RunPod bootstrap + training for the crowd-counter (CSRNet).
#
# Idempotent and spot-safe: re-running after an interruption auto-resumes from
# the checkpoint on your persistent volume. Designed for a RunPod "PyTorch" pod
# template (torch preinstalled with the correct CUDA build) with a persistent
# volume mounted at /workspace.
#
# Quick start (on the pod):
#   cd /workspace
#   git clone <your beacon-server repo>
#   cd beacon-server/crowd-counter
#   DATASET_ROOT=/workspace/ShanghaiTech/part_B/train_data \
#     WORKDIR=/workspace/cc bash cloud/runpod_train.sh
#
# Configuration (env vars; all optional except a dataset source):
#   WORKDIR       base dir for data + checkpoints  (default: the crowd-counter dir)
#   DATASET_ROOT  path to a dataset already on disk (images + matching .mat files)
#   DATASET_URL   if set (and DATASET_ROOT unset), download+extract this archive
#   VAL_FRAC      validation holdout fraction      (default 0.1)
#   EPOCHS        training epochs                  (default 200)
#   CROP          random crop size in px           (default 512; 0 = full image)
#   SIGMA         gaussian target sigma in px      (default 15)
#   LR            learning rate                    (default 1e-5)
#   SEED          RNG seed                         (default 0)
#   OUT           checkpoint path                  (default $WORKDIR/csrnet.pth)
#   SMOKE         run selftest + 1-epoch check first (default 1; set 0 to skip)
#   FORCE         rebuild manifests even if present (default 0)
set -euo pipefail

# Resolve the crowd-counter dir (parent of this script's cloud/ folder) and run
# from there so the sibling module imports (model, pipeline, ...) resolve.
CC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$CC_DIR"

WORKDIR="${WORKDIR:-$CC_DIR}"
DATASET_ROOT="${DATASET_ROOT:-}"
DATASET_URL="${DATASET_URL:-}"
VAL_FRAC="${VAL_FRAC:-0.1}"
EPOCHS="${EPOCHS:-200}"
CROP="${CROP:-512}"
SIGMA="${SIGMA:-15}"
LR="${LR:-1e-5}"
SEED="${SEED:-0}"
OUT="${OUT:-$WORKDIR/csrnet.pth}"
SMOKE="${SMOKE:-1}"
FORCE="${FORCE:-0}"

DATA_DIR="$WORKDIR/data"
TRAIN_JSON="$DATA_DIR/train.json"
VAL_JSON="$DATA_DIR/val.json"
LOG="$WORKDIR/train.log"

log() { printf '\n\033[1;36m[runpod]\033[0m %s\n' "$*"; }

ensure_tool() {
  command -v "$1" >/dev/null 2>&1 || {
    log "installing $1 via apt"
    apt-get update -qq && apt-get install -y -qq "$1"
  }
}

mkdir -p "$DATA_DIR"

# 1) Dependencies. Keep the template's torch/CUDA build; install only the rest,
#    and torch itself only if it's genuinely missing.
log "Installing Python dependencies"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet numpy pillow requests scipy
if ! python -c "import torch" 2>/dev/null; then
  log "torch not found -> installing (prefer a RunPod PyTorch template to get the right CUDA build)"
  python -m pip install --quiet torch torchvision
fi
# torchvision provides the VGG16 frontend CSRNet initializes from; ensure it is
# present even when the base image ships torch without it.
python -c "import torchvision" 2>/dev/null || {
  log "torchvision missing -> installing"
  python -m pip install --quiet torchvision
}
python -c "import torch, torchvision; print('[runpod] torch', torch.__version__, 'torchvision', torchvision.__version__, '| cuda available:', torch.cuda.is_available())"

# 2) Optional dataset download.
if [ -n "$DATASET_URL" ] && [ -z "$DATASET_ROOT" ]; then
  ensure_tool curl
  mkdir -p "$WORKDIR/dataset"
  arch="$WORKDIR/dataset/archive.bin"
  log "Downloading dataset from \$DATASET_URL"
  curl -fL "$DATASET_URL" -o "$arch"
  case "$DATASET_URL" in
    *.zip)          ensure_tool unzip; unzip -q -o "$arch" -d "$WORKDIR/dataset" ;;
    *.tar.gz|*.tgz) tar xzf "$arch" -C "$WORKDIR/dataset" ;;
    *.tar)          tar xf "$arch" -C "$WORKDIR/dataset" ;;
    *) log "Unknown archive type; extract it manually and re-run with DATASET_ROOT set"; exit 2 ;;
  esac
  DATASET_ROOT="$WORKDIR/dataset"
fi

if [ -z "$DATASET_ROOT" ]; then
  echo "ERROR: provide a dataset. Set DATASET_ROOT=/path/to/dataset (images + .mat)," >&2
  echo "       or DATASET_URL=<archive url> to download one. See cloud/RUNPOD.md." >&2
  exit 2
fi

# 3) Build train/val manifests (skip if already built unless FORCE=1).
if [ "$FORCE" = "1" ] || [ ! -f "$TRAIN_JSON" ]; then
  log "Building manifests from $DATASET_ROOT"
  python datasets.py --root "$DATASET_ROOT" --out "$TRAIN_JSON" \
    --val-out "$VAL_JSON" --val-frac "$VAL_FRAC" --seed "$SEED"
else
  log "Manifests already present ($TRAIN_JSON); set FORCE=1 to rebuild"
fi

# 4) Fast smoke tests before the long run.
if [ "$SMOKE" = "1" ]; then
  log "Plumbing self-test (no torch/network)"
  python selftest.py
  log "1-epoch training smoke test (validates the torch path)"
  python train.py --manifest "$TRAIN_JSON" --val "$VAL_JSON" \
    --epochs 1 --crop "$CROP" --sigma "$SIGMA" --lr "$LR" --seed "$SEED" \
    --out "$WORKDIR/csrnet_smoke.pth"
  rm -f "$WORKDIR/csrnet_smoke.pth"
  log "Smoke tests passed"
fi

# 5) Full training. Auto-resume if a checkpoint already exists (spot-safe).
RESUME_ARG=""
if [ -f "$OUT" ]; then
  log "Existing checkpoint found ($OUT) -> resuming / continuing training"
  RESUME_ARG="--resume $OUT"
fi

log "Training: epochs=$EPOCHS crop=$CROP sigma=$SIGMA lr=$LR seed=$SEED -> $OUT"
log "Logging to $LOG  (tip: run under tmux so an SSH drop won't kill it)"
python train.py --manifest "$TRAIN_JSON" --val "$VAL_JSON" \
  --epochs "$EPOCHS" --crop "$CROP" --sigma "$SIGMA" --lr "$LR" --seed "$SEED" \
  $RESUME_ARG --out "$OUT" 2>&1 | tee -a "$LOG"

log "Done. Best checkpoint: $OUT"
log "Retrieve it locally with:  runpodctl receive  OR  scp <pod-ssh>:$OUT ./csrnet.pth"
