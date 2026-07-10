"""Thin client that pushes crowd-count results into beacon-server.

Speaks the camera_counting.py contract:
  POST /events/{event}/count-sources                       (register)
  POST /events/{event}/count-sources/{id}/samples          (density: {heads})
  PUT  /events/{event}/count-sources/{id}/heatmap          ({cells:[{x,y,w}]})
"""

from __future__ import annotations

from typing import Optional

import requests


class BeaconClient:
    def __init__(self, base_url: str, event_id: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.event_id = event_id
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}/events/{self.event_id}{path}"

    def ensure_source(
        self,
        name: str,
        kind: str = "density",
        zone_id: Optional[str] = None,
    ) -> str:
        """Return the source id, creating it (by name) if it doesn't exist."""
        resp = requests.get(self._url("/count-sources"), timeout=self.timeout)
        resp.raise_for_status()
        for src in resp.json():
            if src.get("name") == name and src.get("kind") == kind:
                return src["id"]
        resp = requests.post(
            self._url("/count-sources"),
            json={"name": name, "kind": kind, "zone_id": zone_id},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def push_density(self, source_id: str, heads: int, confidence: Optional[float] = None) -> dict:
        body = {"heads": int(heads)}
        if confidence is not None:
            body["confidence"] = float(confidence)
        resp = requests.post(
            self._url(f"/count-sources/{source_id}/samples"),
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def push_heatmap(self, source_id: str, cells: list[dict]) -> dict:
        resp = requests.put(
            self._url(f"/count-sources/{source_id}/heatmap"),
            json={"cells": cells},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    # ----- camera feeds / tripwire lines (camera_feeds.py contract) -------- #
    def list_feeds(self) -> list[dict]:
        resp = requests.get(self._url("/camera-feeds"), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def list_lines(self, feed_id: str) -> list[dict]:
        """Tripwire lines defined for a feed (frame-normalized endpoints)."""
        resp = requests.get(
            self._url(f"/camera-feeds/{feed_id}/lines"), timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def post_crossing(
        self,
        feed_id: str,
        line_id: str,
        direction: str,
        track_id: Optional[str] = None,
        captured_at: Optional[str] = None,
    ) -> dict:
        """Record one directional line crossing; updates the line's in/out ledger."""
        body: dict = {"direction": direction}
        if track_id is not None:
            body["track_id"] = str(track_id)
        if captured_at is not None:
            body["captured_at"] = captured_at
        resp = requests.post(
            self._url(f"/camera-feeds/{feed_id}/lines/{line_id}/crossings"),
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def push_feed_density(
        self,
        feed_id: str,
        heads: int,
        cells: Optional[list[dict]] = None,
        confidence: Optional[float] = None,
    ) -> dict:
        """Push a live density result onto a camera feed (for the /count panel)."""
        body: dict = {"heads": int(heads), "cells": cells or []}
        if confidence is not None:
            body["confidence"] = float(confidence)
        resp = requests.put(
            self._url(f"/camera-feeds/{feed_id}/density"),
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
