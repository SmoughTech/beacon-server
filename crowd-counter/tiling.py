"""Tiled density inference for very large / high-resolution images.

A crowd counter has a floor on how small a head can be before it disappears, so
for gigapixel or panoramic frames you cannot just downscale the whole image. We
split it into overlapping tiles, run the model per tile, and stitch the density
maps back together (blended in the overlaps) into one canvas at 1/8 resolution.
Because density maps are additive, the canvas sum is the total count.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def _aligned(v: int, stride: int) -> int:
    return max(stride, (v // stride) * stride)


def tiled_density(
    model,
    image: Image.Image,
    tile_size: int = 1024,
    overlap: int = 128,
) -> np.ndarray:
    """Run ``model`` over overlapping tiles; return a stitched 1/8-res density map.

    The returned array's ``.sum()`` is the estimated head count.
    """
    stride = getattr(model, "stride", 8)
    image = image.convert("RGB")

    # Align image dimensions to the model stride so tile outputs tessellate.
    W, H = image.size
    W, H = _aligned(W, stride), _aligned(H, stride)
    if (W, H) != image.size:
        image = image.resize((W, H), Image.BILINEAR)

    tile_size = _aligned(tile_size, stride)
    overlap = (overlap // stride) * stride
    step = max(stride, tile_size - overlap)

    ow, oh = W // stride, H // stride
    canvas = np.zeros((oh, ow), dtype=np.float32)
    weight = np.zeros((oh, ow), dtype=np.float32)

    xs = _tile_starts(W, tile_size, step)
    ys = _tile_starts(H, tile_size, step)

    for y0 in ys:
        for x0 in xs:
            x1 = min(x0 + tile_size, W)
            y1 = min(y0 + tile_size, H)
            # Keep tile dims stride-aligned.
            x1 = x0 + _aligned(x1 - x0, stride)
            y1 = y0 + _aligned(y1 - y0, stride)
            tile = image.crop((x0, y0, x1, y1))
            dmap = model.predict(tile)
            dmap = np.atleast_2d(np.asarray(dmap, dtype=np.float32))

            th, tw = dmap.shape
            oy0, ox0 = y0 // stride, x0 // stride
            oy1, ox1 = oy0 + th, ox0 + tw
            # Clip to canvas bounds (rounding safety).
            oy1c, ox1c = min(oy1, oh), min(ox1, ow)
            dh, dw = oy1c - oy0, ox1c - ox0
            if dh <= 0 or dw <= 0:
                continue

            win = _hann2d(th, tw)[:dh, :dw]
            canvas[oy0:oy1c, ox0:ox1c] += dmap[:dh, :dw] * win
            weight[oy0:oy1c, ox0:ox1c] += win

    weight[weight == 0] = 1.0
    return canvas / weight


def _tile_starts(total: int, tile: int, step: int) -> list[int]:
    if total <= tile:
        return [0]
    starts = list(range(0, total - tile + 1, step))
    if starts[-1] != total - tile:
        starts.append(total - tile)
    return starts


def _hann2d(h: int, w: int) -> np.ndarray:
    """2D Hann-ish window (never fully zero) for smooth overlap blending."""
    def w1(n: int) -> np.ndarray:
        if n <= 1:
            return np.ones(1, dtype=np.float32)
        x = np.hanning(n).astype(np.float32)
        return 0.1 + 0.9 * x  # floor so edges still contribute

    return np.outer(w1(h), w1(w)).astype(np.float32)
