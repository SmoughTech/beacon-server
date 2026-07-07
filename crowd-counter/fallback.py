"""Heuristic density estimator that needs no trained weights.

This is a PLACEHOLDER so the whole pipeline (tiling -> heatmap -> POST to Beacon)
runs end-to-end with zero setup. It approximates "crowd texture" from local
high-frequency edge energy and scales it to a pseudo-count. It is NOT a real
crowd counter and its absolute numbers should not be trusted -- swap in a
trained CSRNet (see model.py / train.py) for real results.

It implements the same interface as CSRNet: predict() returns a density map at
1/8 resolution whose sum is the (pseudo) count.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

OUTPUT_STRIDE = 8

# Rough tuning so a dense-looking crowd tile lands in a plausible range. This is
# a knob, not science.
PSEUDO_DENSITY_GAIN = 0.02


class FallbackModel:
    stride = OUTPUT_STRIDE

    def predict(self, tile_rgb: Image.Image) -> np.ndarray:
        gray = tile_rgb.convert("L")
        # High-frequency energy: crowds are visually busy/textured.
        edges = gray.filter(ImageFilter.FIND_EDGES)
        w, h = gray.size
        ow, oh = max(1, w // OUTPUT_STRIDE), max(1, h // OUTPUT_STRIDE)
        small = edges.resize((ow, oh), Image.BILINEAR)
        e = np.asarray(small, dtype=np.float32) / 255.0
        # Suppress low-texture background, emphasize busy regions.
        e = np.clip(e - 0.12, 0.0, None) ** 1.5
        density = e * PSEUDO_DENSITY_GAIN
        return density.astype(np.float32)
