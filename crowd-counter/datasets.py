"""Convert point-annotation crowd datasets into the train.py manifest format.

Supports the two most common public dense-crowd datasets, whose head points ship
as MATLAB ``.mat`` files:

* **ShanghaiTech** (Part A / Part B): images in ``.../images/IMG_<n>.jpg`` with
  annotations in ``.../ground-truth/GT_IMG_<n>.mat`` (points under
  ``image_info[0,0][0,0][0]``).
* **UCF-QNRF**: images ``img_<nnnn>.jpg`` alongside ``img_<nnnn>_ann.mat``
  (points under ``annPoints``).

It scans a root folder, pairs each image with its annotation, reads the head
points, and writes a manifest whose ``image`` paths are relative to the output
file (so train.py resolves them correctly regardless of where it runs).

Usage:
    python datasets.py --root path/to/ShanghaiTech/part_A/train_data --out data/train.json
    python datasets.py --root path/to/UCF-QNRF/Train --out data/train.json
    # carve a validation split off the same source (deterministic):
    python datasets.py --root .../train_data --out data/train.json \
        --val-out data/val.json --val-frac 0.1 --seed 0

Requires scipy (pip install scipy) to read the .mat files.
"""

from __future__ import annotations

import argparse
import json
import os

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def _load_points(mat_path: str):
    """Read an (N, 2) array of [x, y] head points from a dataset .mat file."""
    import numpy as np
    from scipy.io import loadmat

    m = loadmat(mat_path)
    if "annPoints" in m:  # UCF-QNRF
        pts = m["annPoints"]
    elif "image_info" in m:  # ShanghaiTech
        pts = m["image_info"][0][0][0][0][0]
    else:
        raise ValueError(
            f"Unrecognized annotation keys in {mat_path}: "
            f"{[k for k in m.keys() if not k.startswith('__')]}"
        )
    arr = np.asarray(pts, dtype=float)
    if arr.ndim != 2 or arr.shape[1] < 2:
        raise ValueError(f"Unexpected point array shape {arr.shape} in {mat_path}")
    return arr[:, :2]


def _find_annotation(image_path: str) -> str | None:
    """Locate the .mat annotation for an image across the known dataset layouts."""
    d = os.path.dirname(image_path)
    stem = os.path.splitext(os.path.basename(image_path))[0]

    candidates = [
        os.path.join(d, f"{stem}_ann.mat"),  # UCF-QNRF
        os.path.join(d, f"{stem}.mat"),
    ]
    # ShanghaiTech: sibling ground-truth folder, GT_ prefix.
    parent = os.path.dirname(d)
    for gt_dir in ("ground-truth", "ground_truth", "gt"):
        candidates.append(os.path.join(parent, gt_dir, f"GT_{stem}.mat"))
        candidates.append(os.path.join(d, gt_dir, f"GT_{stem}.mat"))

    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _iter_images(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                yield os.path.join(dirpath, name)


def build_records(root: str, verbose: bool = True) -> list[dict]:
    """Return records with absolute image paths and pixel head points.

    Kept path-agnostic (absolute ``_abs``) so each output manifest can store
    paths relative to its own location.
    """
    records: list[dict] = []
    missing = 0
    for img_path in _iter_images(root):
        ann = _find_annotation(img_path)
        if ann is None:
            missing += 1
            if verbose:
                print(f"[no-ann] {img_path}")
            continue
        try:
            pts = _load_points(ann)
        except Exception as exc:
            print(f"[skip] {ann}: {exc}")
            continue
        records.append(
            {
                "_abs": os.path.abspath(img_path),
                "points": [[float(x), float(y)] for x, y in pts],
            }
        )
    if verbose:
        total_heads = sum(len(r["points"]) for r in records)
        print(f"[datasets] {len(records)} images, {total_heads} heads, {missing} without annotations")
    return records


def _write(records: list[dict], out_path: str) -> None:
    out_dir = os.path.dirname(os.path.abspath(out_path)) or "."
    os.makedirs(out_dir, exist_ok=True)
    entries = [
        {
            "image": os.path.relpath(r["_abs"], out_dir).replace(os.sep, "/"),
            "points": r["points"],
        }
        for r in records
    ]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(entries, f)
    print(f"[datasets] wrote {len(entries)} entries -> {out_path}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build a train.py manifest from a crowd dataset")
    p.add_argument("--root", required=True, help="Dataset folder to scan (recursively)")
    p.add_argument("--out", required=True, help="Output manifest JSON (training split)")
    p.add_argument("--val-out", default=None, help="Optional output manifest for a validation split")
    p.add_argument("--val-frac", type=float, default=0.0, help="Fraction of images held out for --val-out")
    p.add_argument("--seed", type=int, default=0, help="Shuffle seed for the val split")
    args = p.parse_args(argv)

    if not os.path.isdir(args.root):
        print(f"--root not found: {args.root}")
        return 2

    records = build_records(args.root)
    if not records:
        print("[datasets] no annotated images found; check --root and dataset layout")
        return 1

    if args.val_out and args.val_frac > 0:
        import random

        idx = list(range(len(records)))
        random.Random(args.seed).shuffle(idx)
        n_val = max(1, int(round(len(records) * args.val_frac)))
        val_idx = set(idx[:n_val])
        train_records = [r for i, r in enumerate(records) if i not in val_idx]
        val_records = [r for i, r in enumerate(records) if i in val_idx]
        _write(train_records, args.out)
        _write(val_records, args.val_out)
    else:
        _write(records, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
