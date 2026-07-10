"""Line-crossing counter (detector + tracker + tripwire) -- design + scaffold.

WHY THIS IS SEPARATE FROM CSRNet
--------------------------------
CSRNet (density regression) estimates *how many* people are in a frame and
*where* the crowd is dense. It has no notion of individual identity, so it
cannot tell you that "person #37 walked from outside to inside". Counting people
across a line requires:

  1. DETECT   each person as a box, every frame        (YOLO / RT-DETR class)
  2. TRACK    assign a stable id to each person and     (ByteTrack / OC-SORT)
              follow it frame to frame
  3. TRIPWIRE watch each track's foot/centroid point;   (this file)
              when it moves from one side of a drawn
              line to the other, emit a directional
              crossing (+in or +out)

The tripwire math (step 3) is pure geometry and lives here now, unit-testable
without any model. Steps 1-2 need heavy dependencies (ultralytics / torch) and a
running video source, so they are scaffolded with a clear TODO.

INTEGRATION
-----------
Each crossing is POSTed to beacon-server:
    POST /events/{event_id}/camera-feeds/{feed_id}/lines/{line_id}/crossings
         {"direction": "in"|"out", "track_id": "...", "captured_at": "..."}
which updates the line's in/out ledger (the authoritative occupancy figure).

Lines are defined in the /count panel in frame-normalized coords (0..1):
    A = (ax, ay), B = (bx, by), plus a `flip` flag choosing which side is "in".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def side_of_line(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Signed side of point P relative to directed line A->B.

    Positive on one side, negative on the other, ~0 on the line. Uses the 2D
    cross product of (B-A) x (P-A).
    """
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


@dataclass
class Tripwire:
    """Stateful line-crossing detector for one drawn line.

    Feed it each track's current centroid via ``update``; it remembers the last
    side per track and emits "in"/"out" when the sign flips.
    """

    ax: float
    ay: float
    bx: float
    by: float
    flip: bool = False
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
        # Crossing: moving toward the positive side is "in" unless flipped.
        entering = s > 0
        if self.flip:
            entering = not entering
        if entering:
            self.cumulative_in += 1
            return "in"
        self.cumulative_out += 1
        return "out"

    def forget(self, track_id) -> None:
        self._last_side.pop(track_id, None)


# --------------------------------------------------------------------------- #
# Full pipeline scaffold (NOT yet implemented -- needs detector + tracker deps)
# --------------------------------------------------------------------------- #
def run_line_counter(*args, **kwargs):  # pragma: no cover - scaffold
    """Planned implementation:

    deps:  pip install ultralytics   (bundles a YOLO detector + ByteTrack)
           pip install opencv-python (video capture, incl. RTSP)

    sketch:
        from ultralytics import YOLO
        model = YOLO("yolo11n.pt")            # person detector + tracker
        wires = [Tripwire(**line) for line in lines_from_beacon]
        for result in model.track(source=rtsp_url, classes=[0], stream=True,
                                   tracker="bytetrack.yaml", persist=True):
            for box, tid in zip(result.boxes.xywhn, result.boxes.id):
                cx, cy = float(box[0]), float(box[1] + box[3] / 2)   # foot point
                for wire in wires:
                    d = wire.update(int(tid), cx, cy)
                    if d:
                        post_crossing(event_id, feed_id, wire.line_id, d, tid)

    This runs on the same box as server.py (a GPU helps but yolo11n is fine on
    CPU for a single feed). It pulls RTSP directly, so IP cameras that the
    browser cannot open are handled here server-side.
    """
    raise NotImplementedError(
        "Line-crossing pipeline not implemented yet. Install ultralytics + "
        "opencv-python and wire YOLO.track() into the Tripwire helper above."
    )
