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

Paths in "image" are resolved relative to the manifest file's directory. Use
``datasets.py`` to generate this manifest from ShanghaiTech / UCF-QNRF ``.mat``
annotations.

Usage:
    python train.py --manifest data/train.json --epochs 100 --out csrnet.pth
    python train.py --manifest data/train.json --val data/val.json --out csrnet.pth
    python train.py --manifest data/train.json --resume csrnet.pth --lr 1e-6  # fine-tune
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
    try:
        from scipy.ndimage import gaussian_filter
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "scipy is required to build density targets for training "
            "(pip install scipy)."
        ) from exc

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


def random_crop_flip(
    x: np.ndarray,
    target: np.ndarray,
    stride: int,
    crop: int,
    rng: np.random.Generator,
    flip_prob: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Sample an aligned random crop (+ optional h-flip) of the image/target pair.

    ``x`` is ``(3, H, W)`` and ``target`` is ``(H//stride, W//stride)``. The crop
    is aligned to ``stride`` so the density target stays consistent (its sum over
    the crop equals the head count inside the crop). ``crop <= 0`` disables
    cropping (full image). Returns contiguous float32 arrays (torch cannot take
    the negative strides a flipped view produces).
    """
    _, H, W = x.shape
    ch = cw = max(stride, (int(crop) // stride) * stride) if crop and crop > 0 else 0

    if ch and cw and ch < H and cw < W:
        oy = int(rng.integers(0, (H - ch) // stride + 1))
        ox = int(rng.integers(0, (W - cw) // stride + 1))
        y0, x0 = oy * stride, ox * stride
        xc = x[:, y0 : y0 + ch, x0 : x0 + cw]
        tc = target[oy : oy + ch // stride, ox : ox + cw // stride]
    else:
        xc, tc = x, target

    if flip_prob and rng.random() < flip_prob:
        xc = xc[:, :, ::-1]
        tc = tc[:, ::-1]

    return (
        np.ascontiguousarray(xc, dtype=np.float32),
        np.ascontiguousarray(tc, dtype=np.float32),
    )


def iterate(manifest, sigma, stride):
    """Yield (preprocessed_image, density_target, gt_count) for full images."""
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
    p.add_argument(
        "--crop",
        type=int,
        default=512,
        help="Random crop size in px per training step (0 = full image). "
        "Smaller crops cut VRAM and add augmentation; aligned to model stride.",
    )
    p.add_argument(
        "--crops-per-image",
        type=int,
        default=1,
        help="Random crops sampled from each image per epoch",
    )
    p.add_argument(
        "--flip-prob",
        type=float,
        default=0.5,
        help="Horizontal-flip augmentation probability (0 disables)",
    )
    p.add_argument("--seed", type=int, default=0, help="RNG seed for reproducibility")
    p.add_argument(
        "--resume",
        default=None,
        help="Resume/fine-tune from an existing .pth (skips VGG frontend download)",
    )
    args = p.parse_args(argv)

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    stride = OUTPUT_STRIDE

    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)

    train = load_manifest(args.manifest)
    val = load_manifest(args.val) if args.val else None
    print(
        f"[train] {len(train)} images on {device} "
        f"(crop={args.crop or 'full'}, crops/img={max(1, args.crops_per_image)}, "
        f"flip_p={args.flip_prob}, seed={args.seed})"
    )

    net = build_csrnet()(load_vgg_frontend=args.resume is None).to(device)
    if args.resume:
        state = torch.load(args.resume, map_location="cpu")
        if isinstance(state, dict) and "state_dict" in state:
            state = state["state_dict"]
        net.load_state_dict(state, strict=False)
        print(f"[train] resumed weights from {args.resume}")

    optim = torch.optim.Adam(net.parameters(), lr=args.lr)
    loss_fn = nn.MSELoss(reduction="sum")

    # Density targets are small (stride-res) and expensive to build (Gaussian on
    # full-res points), so cache them across epochs; images are reloaded per epoch.
    target_cache: dict[str, np.ndarray] = {}

    best = float("inf")
    for epoch in range(1, args.epochs + 1):
        net.train()
        order = list(range(len(train)))
        rng.shuffle(order)
        running = 0.0
        count = 0
        for idx in order:
            item = train[idx]
            try:
                img = Image.open(item["_abs"]).convert("RGB")
            except Exception as exc:
                print(f"[skip] {item['_abs']}: {exc}")
                continue
            x = preprocess_image(img)
            key = item["_abs"]
            target = target_cache.get(key)
            if target is None:
                target = make_density_target(img.size, item.get("points", []), args.sigma, stride)
                target_cache[key] = target

            for _ in range(max(1, args.crops_per_image)):
                xc, tc = random_crop_flip(x, target, stride, args.crop, rng, args.flip_prob)
                xt = torch.from_numpy(xc).unsqueeze(0).to(device)
                tt = torch.from_numpy(tc).unsqueeze(0).unsqueeze(0).to(device)
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
