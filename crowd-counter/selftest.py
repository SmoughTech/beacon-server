"""Offline smoke test: no torch, no network, no image files needed.

Generates a synthetic textured image, runs it through the fallback model +
tiling + pipeline, and checks we get a count and heatmap cells. Verifies the
plumbing end-to-end (minus the Beacon POST).

    python selftest.py
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from fallback import FallbackModel
from pipeline import analyze_image


def synthetic_crowd(w=1600, h=900, blobs=800, seed=0) -> Image.Image:
    rng = np.random.default_rng(seed)
    img = rng.integers(20, 40, size=(h, w, 3), dtype=np.uint8)
    for _ in range(blobs):
        cx, cy = rng.integers(0, w), rng.integers(0, h)
        r = rng.integers(2, 5)
        y0, y1 = max(0, cy - r), min(h, cy + r)
        x0, x1 = max(0, cx - r), min(w, cx + r)
        img[y0:y1, x0:x1] = rng.integers(150, 255, size=3, dtype=np.uint8)
    return Image.fromarray(img, "RGB")


def main() -> int:
    img = synthetic_crowd()
    model = FallbackModel()
    result = analyze_image(model, img, tile_size=512, overlap=64, grid_cols=32, grid_rows=18)

    assert result.count >= 0, "count should be non-negative"
    assert result.cells, "expected some heatmap cells for a textured image"
    for c in result.cells:
        assert 0.0 <= c["x"] <= 1.0 and 0.0 <= c["y"] <= 1.0, "cell coords must be normalized"
        assert c["w"] >= 0.0

    print(f"OK: pseudo-count={result.count}, cells={len(result.cells)} "
          f"(grid {result.grid_cols}x{result.grid_rows})")
    print("Pipeline plumbing works. NOTE: fallback numbers are not accurate -- "
          "train CSRNet (train.py) and pass --weights for real counts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
