"""HTTP inference service for the Beacon /count panel.

The panel captures frames in the browser and POSTs them here; this service runs
the density model (CSRNet, or the heuristic fallback if torch/weights are absent)
and returns a headcount plus a frame-normalized heatmap. It is intentionally
separate from beacon-server: Beacon stores/serves results, this box does the CV.

Endpoints
---------
GET  /health              -> {ok, model, device, tracker}
POST /infer/density       -> multipart 'image' -> {count, cells, grid_cols, grid_rows}
POST /infer/track         -> line-crossing (detector+tracker). Not implemented yet;
                             returns 501 with the plan. See tracker.py.

Run
---
    pip install -r requirements-server.txt
    python server.py --weights csrnet.pth --host 0.0.0.0 --port 8100

CORS is open so the browser panel (served from beacon-server on another origin)
can call it directly.
"""

from __future__ import annotations

import argparse
import io
import sys

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from model import load_model
from pipeline import analyze_image

# Configured in main() before uvicorn starts.
_CONFIG = {
    "weights": None,
    "device": None,
    "tile_size": 1024,
    "overlap": 128,
    "grid_cols": 48,
    "grid_rows": 27,
    "confidence": None,
}
_MODEL = None
_MODEL_TAG = "unloaded"


def get_model():
    global _MODEL, _MODEL_TAG
    if _MODEL is None:
        _MODEL = load_model(weights_path=_CONFIG["weights"], device=_CONFIG["device"])
        _MODEL_TAG = type(_MODEL).__name__
    return _MODEL


app = FastAPI(title="Crowd-counter inference service", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {
        "ok": True,
        "model": _MODEL_TAG,
        "device": getattr(_MODEL, "device", None) and str(_MODEL.device),
        "weights": _CONFIG["weights"],
        "tracker": "not_implemented",
    }


@app.post("/infer/density")
async def infer_density(image: UploadFile = File(...)):
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty image")
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"bad image: {exc}")

    result = analyze_image(
        get_model(),
        img,
        tile_size=_CONFIG["tile_size"],
        overlap=_CONFIG["overlap"],
        grid_cols=_CONFIG["grid_cols"],
        grid_rows=_CONFIG["grid_rows"],
    )
    return {
        "count": result.count,
        "raw_count": round(result.raw_count, 3),
        "cells": result.cells,
        "grid_cols": result.grid_cols,
        "grid_rows": result.grid_rows,
        "confidence": _CONFIG["confidence"],
        "model": _MODEL_TAG,
    }


@app.post("/infer/track")
async def infer_track(image: UploadFile = File(...)):
    """Line-crossing detection+tracking. Not implemented yet.

    See tracker.py for the design. Requires a person detector + multi-object
    tracker, which is a separate model from the CSRNet density estimator.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Line-crossing tracking is not implemented. It needs a person "
            "detector + tracker (e.g. YOLO + ByteTrack), not the density model. "
            "See crowd-counter/tracker.py for the plan."
        ),
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Crowd-counter inference HTTP service")
    p.add_argument("--weights", default=None, help="Path to trained CSRNet weights (.pth)")
    p.add_argument("--device", default=None, help="torch device, e.g. cuda or cpu")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--tile-size", type=int, default=1024)
    p.add_argument("--overlap", type=int, default=128)
    p.add_argument("--grid-cols", type=int, default=48)
    p.add_argument("--grid-rows", type=int, default=27)
    p.add_argument("--confidence", type=float, default=None)
    p.add_argument("--preload", action="store_true", help="Load the model at startup instead of first request")
    args = p.parse_args(argv)

    _CONFIG.update(
        weights=args.weights,
        device=args.device,
        tile_size=args.tile_size,
        overlap=args.overlap,
        grid_cols=args.grid_cols,
        grid_rows=args.grid_rows,
        confidence=args.confidence,
    )
    if args.preload:
        get_model()

    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed. `pip install -r requirements-server.txt`", file=sys.stderr)
        return 2
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
