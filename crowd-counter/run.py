"""CLI: count people in image(s) and push results to beacon-server.

Examples
--------
One image, print only (no push):
    python run.py --image crowd.jpg --no-push

One image -> Beacon:
    python run.py --image crowd.jpg \
        --beacon-url http://localhost:8000 --event-id test_fest \
        --source-name "North overview" --weights csrnet.pth

Watch a folder, pushing each new frame every 5s:
    python run.py --dir ./frames --interval 5 \
        --beacon-url http://localhost:8000 --event-id test_fest \
        --source-name "North overview"

Repeat on a single grabbed frame (e.g. a file an RTSP grabber keeps overwriting):
    python run.py --image latest.jpg --interval 2 ...
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from beacon_client import BeaconClient
from model import load_model
from pipeline import analyze_image, load_image

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Crowd density counter -> beacon-server")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", help="Path to a single image")
    src.add_argument("--dir", help="Folder of images to process")

    p.add_argument("--beacon-url", default="http://localhost:8000")
    p.add_argument("--event-id", help="Beacon event id (required unless --no-push)")
    p.add_argument("--source-id", help="Existing count-source id to push to")
    p.add_argument("--source-name", default="Density camera", help="Source name (created if missing)")
    p.add_argument("--zone-id", default=None, help="Optional access-zone id to tag the source")
    p.add_argument("--no-push", action="store_true", help="Only print results; do not POST")

    p.add_argument("--weights", default=None, help="Path to trained CSRNet weights (.pth)")
    p.add_argument("--device", default=None, help="torch device, e.g. cuda or cpu")
    p.add_argument("--tile-size", type=int, default=1024)
    p.add_argument("--overlap", type=int, default=128)
    p.add_argument("--grid-cols", type=int, default=48)
    p.add_argument("--grid-rows", type=int, default=27)
    p.add_argument("--confidence", type=float, default=None, help="0..1 confidence to report")

    p.add_argument("--interval", type=float, default=0.0, help="Seconds between repeats (0 = once)")
    return p.parse_args(argv)


def list_images(folder: str) -> list[str]:
    out = []
    for name in sorted(os.listdir(folder)):
        if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
            out.append(os.path.join(folder, name))
    return out


def process_one(model, client, source_id, path, args) -> None:
    try:
        image = load_image(path)
    except Exception as exc:
        print(f"[skip] {path}: {exc}", file=sys.stderr)
        return
    result = analyze_image(
        model,
        image,
        tile_size=args.tile_size,
        overlap=args.overlap,
        grid_cols=args.grid_cols,
        grid_rows=args.grid_rows,
    )
    print(f"{os.path.basename(path)}: count={result.count} cells={len(result.cells)}")
    if args.no_push:
        return
    client.push_density(source_id, result.count, confidence=args.confidence)
    client.push_heatmap(source_id, result.cells)


def main(argv=None) -> int:
    args = parse_args(argv)

    if not args.no_push and not args.event_id:
        print("--event-id is required unless --no-push", file=sys.stderr)
        return 2

    model = load_model(weights_path=args.weights, device=args.device)

    client = None
    source_id = args.source_id
    if not args.no_push:
        client = BeaconClient(args.beacon_url, args.event_id)
        if not source_id:
            source_id = client.ensure_source(args.source_name, "density", args.zone_id)
            print(f"[beacon] using source {source_id} ({args.source_name})", file=sys.stderr)

    def run_pass():
        if args.image:
            process_one(model, client, source_id, args.image, args)
        else:
            imgs = list_images(args.dir)
            if not imgs:
                print(f"No images in {args.dir}", file=sys.stderr)
            for path in imgs:
                process_one(model, client, source_id, path, args)

    if args.interval and args.interval > 0:
        print(f"[loop] every {args.interval}s (Ctrl+C to stop)", file=sys.stderr)
        try:
            while True:
                run_pass()
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[loop] stopped", file=sys.stderr)
    else:
        run_pass()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
