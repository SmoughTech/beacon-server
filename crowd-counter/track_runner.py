"""CLI: run line-crossing (in/out) counting on a video source and push to Beacon.

This is the authoritative occupancy counter: a YOLO person detector + ByteTrack
tracker follow each individual, and when a track's foot point crosses a threshold
line drawn in the /count panel, a directional crossing is recorded on Beacon.

Setup
-----
    pip install -r requirements-tracker.txt      # ultralytics + opencv

Examples
--------
Local webcam 0, against feed "feed_..." in event "test_fest":
    python track_runner.py --event-id test_fest --feed-id feed_abc123 --source 0

RTSP IP camera (pulled server-side; browsers can't do this):
    python track_runner.py --event-id test_fest --feed-id feed_abc123 \
        --source "rtsp://user:pass@192.168.1.50:554/stream1" --model yolo11s.pt

A recorded clip, on GPU:
    python track_runner.py --event-id test_fest --feed-id feed_abc123 \
        --source gate.mp4 --model yolo11m.pt --device cuda

Notes
-----
* Draw the threshold line(s) first in the /count panel for this feed; the runner
  loads them from Beacon and refreshes every ``--refresh`` seconds.
* Model recommendation: yolo11n.pt (CPU/light), yolo11s.pt or yolo11m.pt (GPU,
  busier entrances). Person class only.
"""

from __future__ import annotations

import argparse
import os
import sys

# On Windows the default OpenCV camera backend (MSMF) frequently opens a webcam
# but fails to read frames. Prefer DirectShow, which is reliable for USB/laptop
# cams. Set before OpenCV is imported (ultralytics pulls it in). Harmless on
# non-Windows. Override by exporting OPENCV_VIDEOIO_PRIORITY_MSMF yourself.
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "0")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="YOLO+ByteTrack line-crossing counter -> beacon-server")
    p.add_argument("--beacon-url", default="http://localhost:8000")
    p.add_argument("--event-id", required=True, help="Beacon event id")
    p.add_argument("--feed-id", required=True, help="Camera feed id (from the /count panel)")
    p.add_argument("--source", required=True, help="Webcam index (0), file path, or RTSP/HTTP URL")

    p.add_argument("--model", default="yolo11n.pt", help="Ultralytics model weights")
    p.add_argument("--device", default=None, help="torch device, e.g. cuda or cpu")
    p.add_argument("--conf", type=float, default=0.3, help="Detection confidence threshold")
    p.add_argument("--imgsz", type=int, default=640, help="Inference image size")
    p.add_argument("--person-class", type=int, default=0, help="COCO class id for person")
    p.add_argument("--refresh", type=float, default=30.0, help="Seconds between line-definition reloads")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        from tracker import run_line_counter
    except Exception as exc:  # pragma: no cover
        print(f"[tracker] import failed: {exc}", file=sys.stderr)
        return 2

    try:
        run_line_counter(
            beacon_url=args.beacon_url,
            event_id=args.event_id,
            feed_id=args.feed_id,
            source=args.source,
            model_path=args.model,
            conf=args.conf,
            device=args.device,
            imgsz=args.imgsz,
            person_class=args.person_class,
            refresh_lines_every=args.refresh,
        )
    except ImportError as exc:
        print(
            f"[tracker] missing dependency: {exc}\n"
            "Install the tracker extras:  pip install -r requirements-tracker.txt",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print("\n[tracker] stopped.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
