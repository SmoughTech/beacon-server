"""Turn an image into (count, heatmap cells) ready to POST to Beacon.

The heatmap is delivered in Beacon's contract: a list of cells ``{x, y, w}`` with
``x``/``y`` as map-normalized coordinates in [0, 1] and ``w`` a density weight.
Here that means image-normalized coordinates; the external side is responsible
for projecting camera view -> site map, but for a single fixed overhead camera
the image frame *is* the map region, so this is already usable.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from tiling import tiled_density


@dataclass
class CountResult:
    count: int
    raw_count: float
    cells: list[dict]
    grid_cols: int
    grid_rows: int


def _downsample_sum(density: np.ndarray, cols: int, rows: int) -> np.ndarray:
    """Aggregate a density map into a coarse cols x rows grid by summation."""
    h, w = density.shape
    out = np.zeros((rows, cols), dtype=np.float32)
    ys = np.linspace(0, h, rows + 1).astype(int)
    xs = np.linspace(0, w, cols + 1).astype(int)
    for r in range(rows):
        for c in range(cols):
            block = density[ys[r]:ys[r + 1], xs[c]:xs[c + 1]]
            if block.size:
                out[r, c] = float(block.sum())
    return out


def analyze_image(
    model,
    image: Image.Image,
    tile_size: int = 1024,
    overlap: int = 128,
    grid_cols: int = 48,
    grid_rows: int = 27,
    min_cell_frac: float = 0.01,
) -> CountResult:
    density = tiled_density(model, image, tile_size=tile_size, overlap=overlap)
    density = np.clip(density, 0.0, None)
    raw_count = float(density.sum())

    grid = _downsample_sum(density, grid_cols, grid_rows)
    max_w = float(grid.max()) if grid.size else 0.0
    threshold = max_w * min_cell_frac

    cells: list[dict] = []
    for r in range(grid_rows):
        for c in range(grid_cols):
            w = float(grid[r, c])
            if w <= threshold:
                continue
            cells.append(
                {
                    "x": round((c + 0.5) / grid_cols, 5),
                    "y": round((r + 0.5) / grid_rows, 5),
                    "w": round(w, 4),
                }
            )

    return CountResult(
        count=int(round(raw_count)),
        raw_count=raw_count,
        cells=cells,
        grid_cols=grid_cols,
        grid_rows=grid_rows,
    )


def load_image(path: str) -> Image.Image:
    return Image.open(path).convert("RGB")
