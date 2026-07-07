"""Train CSRNet on your annotated crowd images.

This is the path from "thousands of annotated stills" to a real, accurate model.
It expects a JSON manifest of head-point annotations (the crowd-counting gold
standard -- one dot per head), builds Gaussian density-map targets, and trains
CSRNet to regress them.

Manifest format (points are pixel coords in the original image):
    [
      {"image": "images/frame001.jpg", "points": [[x1, y1], [x2, y2], ...]},
      {"image": "images/frame002.jpg", "points": [...]},
      ...
    ]

Paths in "image" are resolved relative to the manifest file's directory.

Usage:
    python train.py --manifest data/train.json --epochs 100 --out csrnet.pth
    python train.py --manifest data/train.json --val data/val.json --out csrnet.pth
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np
from PIL import Image

from model import IMAGENET_MEAN, IMAGENET_STD, OUTPUT_STRIDE, build_csrnet


def load_manifest(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    base = os.path.dirname(os.path.abspath(path))
    for item in data:
        item["_abs"] = os.path.join(base, item["image"])
    return data


def make_density_target(size_wh, points, sigma: float, stride: int) -> np.ndarray:
    """Full-res Gaussian density, then block-summed to 1/stride resolution."""
    from scipy.ndimage import gaussian_filter

    w, h = size_wh
    pts = np.zeros((h, w), dtype=np.float32)
    for x, y in points:
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < w and 0 <= yi < h:
            pts[yi, xi] += 1.0
    density = gaussian_filter(pts, sigma=sigma, mode="constant")
    # Downsample to stride resolution by summation (preserves total count).
    oh, ow = h // stride, w // stride
    density = density[: oh * stride, : ow * stride]
    density = density.reshape(oh, stride, ow, stride).sum(axis=(1, 3))
    return density.astype(np.float32)


def preprocess_image(img: Image.Image) -> np.ndarray:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    arr = (arr - IMAGENET_MEAN) / IMAGENET_STD
    return arr.transpose(2, 0, 1)


def iterate(manifest, sigma, stride):
    for item in manifest:
        try:
            img = Image.open(item["_abs"]).convert("RGB")
        except Exception as exc:
            print(f"[skip] {item['_abs']}: {exc}")
            continue
        target = make_density_target(img.size, item.get("points", []), sigma, stride)
        yield preprocess_image(img), target, len(item.get("points", []))


def evaluate(net, manifest, sigma, stride, device):
    import torch

    net.eval()
    abs_err = 0.0
    n = 0
    with torch.no_grad():
        for x, _target, gt in iterate(manifest, sigma, stride):
            t = torch.from_numpy(x).unsqueeze(0).to(device)
            pred = float(net(t).sum().item())
            abs_err += abs(pred - gt)
            n += 1
    return abs_err / max(1, n)


def main(argv=None) -> int:
    import torch
    import torch.nn as nn

    p = argparse.ArgumentParser(description="Train CSRNet on annotated crowd images")
    p.add_argument("--manifest", required=True, help="Training manifest JSON")
    p.add_argument("--val", default=None, help="Optional validation manifest JSON")
    p.add_argument("--out", default="csrnet.pth", help="Output weights path")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--sigma", type=float, default=15.0, help="Gaussian kernel sigma (px)")
    p.add_argument("--device", default=None)
    args = p.parse_args(argv)

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    stride = OUTPUT_STRIDE
    train = load_manifest(args.manifest)
    val = load_manifest(args.val) if args.val else None
    print(f"[train] {len(train)} images on {device}")

    net = build_csrnet()(load_vgg_frontend=True).to(device)
    optim = torch.optim.Adam(net.parameters(), lr=args.lr)
    loss_fn = nn.MSELoss(reduction="sum")

    best = float("inf")
    for epoch in range(1, args.epochs + 1):
        net.train()
        running = 0.0
        count = 0
        for x, target, _gt in iterate(train, args.sigma, stride):
            xt = torch.from_numpy(x).unsqueeze(0).to(device)
            tt = torch.from_numpy(target).unsqueeze(0).unsqueeze(0).to(device)
            pred = net(xt)
            # Align spatial dims (rounding can differ by 1).
            th = min(pred.shape[2], tt.shape[2])
            tw = min(pred.shape[3], tt.shape[3])
            loss = loss_fn(pred[:, :, :th, :tw], tt[:, :, :th, :tw])
            optim.zero_grad()
            loss.backward()
            optim.step()
            running += float(loss.item())
            count += 1

        msg = f"[epoch {epoch}/{args.epochs}] loss={running / max(1, count):.2f}"
        if val:
            mae = evaluate(net, val, args.sigma, stride, device)
            msg += f" val_MAE={mae:.1f}"
            if mae < best:
                best = mae
                torch.save(net.state_dict(), args.out)
                msg += " (saved best)"
        else:
            torch.save(net.state_dict(), args.out)
        print(msg)

    if not val:
        torch.save(net.state_dict(), args.out)
    print(f"[train] done -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
