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
