"""Line-crossing counter: person detector + tracker + tripwire.

WHY THIS IS SEPARATE FROM CSRNet
--------------------------------
CSRNet (density regression) estimates *how many* people are in a frame and
*where* the crowd is dense. It has no notion of individual identity, so it
cannot tell you that "person #37 walked from outside to inside". Counting people
across a line requires:

  1. DETECT   each person as a box, every frame        (YOLO / RT-DETR class)
  2. TRACK    assign a stable id to each person and     (ByteTrack / OC-SORT)
              follow it frame to frame
  3. TRIPWIRE watch each track's foot point; when it    (this file)
              moves from one side of a drawn line to the
              other, emit a directional crossing

Steps 1-2 are provided by Ultralytics YOLO (``model.track(...)`` runs a detector
with ByteTrack built in). Step 3 (the tripwire math) is pure geometry and lives
here, unit-testable without any model. ``track_runner.py`` wires them together
against a live video source and posts crossings to beacon-server.

RECOMMENDED MODEL
-----------------
Ultralytics **YOLO11**, person class only (class 0):
  * ``yolo11n.pt`` - nano: fast, CPU-friendly, good for a single feed. Default.
  * ``yolo11s.pt`` - small: better recall in crowds; light GPU recommended.
  * ``yolo11m.pt`` - medium: busy entrances / higher mounts; GPU recommended.
Detectors saturate in very dense crowds -- use tripwires at *entrances* (sparse,
countable flow) and keep CSRNet density for the packed interior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple


# --------------------------------------------------------------------------- #
# Geometry (pure, unit-testable)
# --------------------------------------------------------------------------- #
def side_of_line(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Signed side of point P relative to directed line A->B.

    Positive on one side, negative on the other, ~0 on the line. Uses the 2D
    cross product of (B-A) x (P-A).
    """
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def foot_point_norm(x1: float, y1: float, x2: float, y2: float, w: float, h: float) -> Tuple[float, float]:
    """Normalized (0..1) foot point of a pixel bbox (bottom-center = where feet are)."""
    cx = (x1 + x2) / 2.0
    fy = max(y1, y2)
    return (cx / max(w, 1.0), fy / max(h, 1.0))


@dataclass
class Tripwire:
    """Stateful line-crossing detector for one drawn line (frame-normalized).

    Feed it each track's current foot point via ``update``; it remembers the last
    side per track and emits "in"/"out" when the sign flips.
    """

    ax: float
    ay: float
    bx: float
    by: float
    flip: bool = False
    line_id: Optional[str] = None
    _last_side: dict = field(default_factory=dict)
    cumulative_in: int = 0
    cumulative_out: int = 0

    def update(self, track_id, px: float, py: float) -> Optional[str]:
        """Return 'in', 'out', or None for this track's new position."""
        s = side_of_line(px, py, self.ax, self.ay, self.bx, self.by)
        prev = self._last_side.get(track_id)
        self._last_side[track_id] = s
        if prev is None or s == 0 or prev == 0:
            return None
        if (prev < 0) == (s < 0):
            return None  # same side, no crossing
        entering = s > 0  # moving toward the positive side is "in" ...
        if self.flip:
            entering = not entering  # ... unless the operator flipped it
        if entering:
            self.cumulative_in += 1
            return "in"
        self.cumulative_out += 1
        return "out"

    def forget(self, track_id) -> None:
        self._last_side.pop(track_id, None)


class TripwireSet:
    """Manages several tripwires for one feed and processes per-frame detections."""

    def __init__(self, lines: Iterable[dict]):
        """``lines`` are Beacon line dicts: {id, ax, ay, bx, by, flip, ...}."""
        self.wires: List[Tripwire] = []
        for ln in lines:
            self.wires.append(
                Tripwire(
                    ax=float(ln["ax"]), ay=float(ln["ay"]),
                    bx=float(ln["bx"]), by=float(ln["by"]),
                    flip=bool(ln.get("flip", False)),
                    line_id=ln.get("id"),
                )
            )

    def process(self, detections: Iterable[Tuple[object, float, float]]) -> List[Tuple[Optional[str], str, object]]:
        """Feed ``(track_id, x_norm, y_norm)`` detections for one frame.

        Returns a list of ``(line_id, direction, track_id)`` for crossings this
        frame.
        """
        events: List[Tuple[Optional[str], str, object]] = []
        dets = list(detections)
        for wire in self.wires:
            for track_id, x, y in dets:
                d = wire.update(track_id, x, y)
                if d:
                    events.append((wire.line_id, d, track_id))
        return events

    def totals(self) -> dict:
        return {
            w.line_id: {"in": w.cumulative_in, "out": w.cumulative_out}
            for w in self.wires
        }


# --------------------------------------------------------------------------- #
# Live pipeline (needs ultralytics + opencv; imported lazily)
# --------------------------------------------------------------------------- #
def _parse_source(source: str):
    """Webcam index like '0' -> int; otherwise pass through (file path / RTSP URL)."""
    s = str(source).strip()
    return int(s) if s.isdigit() else s


def run_line_counter(
    beacon_url: str,
    event_id: str,
    feed_id: str,
    source: str,
    model_path: str = "yolo11n.pt",
    conf: float = 0.3,
    device: Optional[str] = None,
    imgsz: int = 640,
    person_class: int = 0,
    refresh_lines_every: float = 30.0,
    on_event=None,
):
    """Run YOLO+ByteTrack over ``source`` and post line crossings to Beacon.

    Blocks, streaming frames until the source ends or Ctrl+C. Lines are loaded
    from Beacon for ``feed_id`` and refreshed periodically so edits in the
    /count panel take effect without a restart.
    """
    import time

    from ultralytics import YOLO  # heavy; imported only when actually tracking

    from beacon_client import BeaconClient

    client = BeaconClient(beacon_url, event_id)

    def load_wires() -> TripwireSet:
        lines = client.list_lines(feed_id)
        print(f"[tracker] loaded {len(lines)} tripwire line(s) for feed {feed_id}")
        return TripwireSet(lines)

    wires = load_wires()
    if not wires.wires:
        print("[tracker] no lines defined yet; draw a threshold line in the /count panel.")

    model = YOLO(model_path)
    last_refresh = time.time()

    stream = model.track(
        source=_parse_source(source),
        stream=True,
        persist=True,
        classes=[person_class],
        conf=conf,
        imgsz=imgsz,
        device=device,
        tracker="bytetrack.yaml",
        verbose=False,
    )

    for result in stream:
        # Refresh line definitions occasionally (picks up panel edits).
        if refresh_lines_every and (time.time() - last_refresh) > refresh_lines_every:
            try:
                wires = load_wires()
            except Exception as exc:  # pragma: no cover - network dependent
                print(f"[tracker] line refresh failed: {exc}")
            last_refresh = time.time()

        boxes = getattr(result, "boxes", None)
        if boxes is None or boxes.id is None:
            continue
        h, w = result.orig_shape  # (height, width)
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.int().cpu().tolist()

        dets = []
        for (x1, y1, x2, y2), tid in zip(xyxy, ids):
            fx, fy = foot_point_norm(float(x1), float(y1), float(x2), float(y2), w, h)
            dets.append((tid, fx, fy))

        for line_id, direction, track_id in wires.process(dets):
            try:
                client.post_crossing(feed_id, line_id, direction, track_id=track_id)
            except Exception as exc:  # pragma: no cover - network dependent
                print(f"[tracker] post_crossing failed: {exc}")
            if on_event:
                on_event(line_id, direction, track_id)
            else:
                print(f"[tracker] {direction.upper()} line={line_id} track={track_id}")
