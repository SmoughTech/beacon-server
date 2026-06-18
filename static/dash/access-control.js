(function () {
  const SVG_W = 1000;
  const SVG_H = 562.5;
  const GRID_W = 400;
  const GRID_H = 225;
  const PORTAL_SNAP_DIST = 0.011;
  const PORTAL_SNAP_RADIUS = 0.014;
  const BARRIER_ENDPOINT_SNAP_RADIUS = 0.014;
  const BARRIER_SEGMENT_SNAP_RADIUS = 0.012;
  const PORTAL_GAP_HALF_WIDTH = 0.014;

  const ZONE_COLORS = {
    ga: "rgba(76,175,80,0.38)",
    vip: "rgba(255,193,7,0.40)",
    staff: "rgba(66,165,245,0.40)",
    backstage: "rgba(171,71,188,0.40)",
    vendor: "rgba(255,152,0,0.38)",
  };

  const ZONE_PRESETS = [
    { name: "GA Green", color: "#4caf50", opacity: 38 },
    { name: "VIP Gold", color: "#ffc107", opacity: 40 },
    { name: "Staff Blue", color: "#42a5f5", opacity: 40 },
    { name: "Backstage Purple", color: "#ab47bc", opacity: 40 },
    { name: "Vendor Orange", color: "#ff9800", opacity: 38 },
    { name: "Red Alert", color: "#ef5350", opacity: 42 },
    { name: "Teal", color: "#26a69a", opacity: 40 },
    { name: "Pink", color: "#ec407a", opacity: 40 },
  ];

  let accessBarriers = [];
  let accessZones = [];
  let accessTool = "select";
  let draftBarrierPoints = [];
  let draftBarrierClosed = false;
  let selectedBarrierId = null;
  let selectedZoneId = null;
  let fillZoneClass = "ga";
  let portalHeadingPreview = null;
  let portalFlowFlipPreview = null;
  const ACCESS_LAYER_KEY = "beacon_access_layers";
  const SCANNER_SCALE_KEY = "beacon_dash_scanner_scale";
  const SIM_LOCATION_META = {
    food_tent: { label: "Food Tent", target: "vendor", icon: "F", marker: "vendor" },
    food_trailer: { label: "Food Trailer", target: "vendor", icon: "F", marker: "vendor" },
    staff_spot: { label: "Staff Spot", target: "staff", icon: "W", marker: "staff" },
    staff_trailer: { label: "Staff Trailer", target: "staff", icon: "W", marker: "staff" },
    staff_tent: { label: "Staff Tent", target: "staff", icon: "W", marker: "staff" },
  };
  let accessLayers = {
    snapPoints: true,
    barriers: true,
    zones: true,
    gates: true,
    pois: true,
    anchors: true,
    workLocations: true,
  };
  let accessSimLocations = [];
  let selectedSimLocationId = null;
  let placeSimLocationType = "staff_spot";

  function getScannerMarkerScale() {
    const raw = Number(localStorage.getItem(SCANNER_SCALE_KEY));
    if (!Number.isFinite(raw)) return 0.72;
    return Math.max(0.5, Math.min(1.3, raw / 100));
  }

  function applyScannerMarkerScale(pct) {
    const scale = Math.max(0.5, Math.min(1.3, (Number(pct) || 72) / 100));
    document.documentElement.style.setProperty("--dash-scanner-scale", String(scale));
    const label = document.getElementById("dashScannerScaleValue");
    if (label) label.textContent = `${Math.round(scale * 100)}%`;
    const slider = document.getElementById("dashScannerScale");
    if (slider && document.activeElement !== slider) slider.value = String(Math.round(scale * 100));
  }

  function refreshGateSnapGraphics() {
    if (typeof drawAccessLayers === "function") drawAccessLayers();
    if (typeof decorateGateMarkers === "function") decorateGateMarkers();
  }

  function loadAccessLayerPrefs() {
    try {
      const raw = localStorage.getItem(ACCESS_LAYER_KEY);
      if (raw) accessLayers = { ...accessLayers, ...JSON.parse(raw) };
    } catch {
      /* ignore */
    }
  }

  function saveAccessLayerPrefs() {
    localStorage.setItem(ACCESS_LAYER_KEY, JSON.stringify(accessLayers));
  }

  function syncAccessLayerCheckboxes() {
    const map = {
      accessLayerSnap: "snapPoints",
      accessLayerBarriers: "barriers",
      accessLayerZones: "zones",
      accessLayerGates: "gates",
      accessLayerPois: "pois",
      accessLayerAnchors: "anchors",
      accessLayerWorkLocs: "workLocations",
    };
    Object.entries(map).forEach(([id, key]) => {
      const el = document.getElementById(id);
      if (el) el.checked = !!accessLayers[key];
    });
  }

  function applyAccessLayerVisibility() {
    document.querySelectorAll(".marker.gate").forEach((el) => {
      el.style.display = accessLayers.gates ? "" : "none";
    });
    document.querySelectorAll(".marker.poi").forEach((el) => {
      el.style.display = accessLayers.pois ? "" : "none";
    });
    document.querySelectorAll(".marker.anchor").forEach((el) => {
      el.style.display = accessLayers.anchors ? "" : "none";
    });
    document.querySelectorAll(".marker.simLoc").forEach((el) => {
      el.style.display = accessLayers.workLocations ? "" : "none";
    });
  }

  function simLocationMeta(loc) {
    const t = String(loc?.location_type || loc?.locationType || "staff_spot").toLowerCase();
    return SIM_LOCATION_META[t] || SIM_LOCATION_META.staff_spot;
  }

  function drawSimLocationMarkers() {
    if (!accessLayers.workLocations) return;
    if (typeof marker !== "function" || typeof getMapStage !== "function") return;
    accessSimLocations.forEach((loc) => {
      const meta = simLocationMeta(loc);
      const el = marker(
        loc.map_x,
        loc.map_y,
        `simLoc ${meta.marker}${selectedSimLocationId === loc.id ? " selected" : ""}`,
        `${loc.name} (${meta.label})`,
        () => selectSimLocation(loc.id)
      );
      el.dataset.simLocId = loc.id;
      el.dataset.simLocIcon = meta.icon;
      el.setAttribute("data-sim-loc-icon", meta.icon);
    });
  }

  function updateWorkLocationSectionVisibility() {
    const section = document.getElementById("accessWorkLocationSection");
    if (section) section.classList.toggle("hidden", accessTool !== "workLocations");
  }

  function renderWorkLocationSection() {
    const section = document.getElementById("accessWorkLocationSection");
    if (!section) return;
    updateWorkLocationSectionVisibility();
    if (accessTool !== "workLocations") {
      section.innerHTML = "";
      return;
    }

    const typeOptions = Object.entries(SIM_LOCATION_META)
      .map(
        ([value, meta]) =>
          `<option value="${value}" ${placeSimLocationType === value ? "selected" : ""}>${meta.label} (${meta.target})</option>`
      )
      .join("");

    const cards = accessSimLocations
      .map((loc) => {
        const meta = simLocationMeta(loc);
        const sel = selectedSimLocationId === loc.id;
        const editor = sel
          ? `<label>Name</label><input id="editSimLocName" value="${escapeHtml(loc.name)}" onclick="event.stopPropagation()" onmousedown="event.stopPropagation()"><label>Type</label><select id="editSimLocType" onclick="event.stopPropagation()" onmousedown="event.stopPropagation()">${Object.entries(
              SIM_LOCATION_META
            )
              .map(
                ([value, m]) =>
                  `<option value="${value}" ${loc.location_type === value ? "selected" : ""}>${m.label}</option>`
              )
              .join("")}</select><div class="row"><div><label>Map X</label><input id="editSimLocMapX" value="${Number(loc.map_x).toFixed(4)}" onclick="event.stopPropagation()" onmousedown="event.stopPropagation()"></div><div><label>Map Y</label><input id="editSimLocMapY" value="${Number(loc.map_y).toFixed(4)}" onclick="event.stopPropagation()" onmousedown="event.stopPropagation()"></div></div><div class="row"><button class="primary" onclick="event.stopPropagation(); saveSimLocation('${loc.id}')">Save</button><button onclick="event.stopPropagation(); mapClickMode='moveSimLoc'; setStatus('Click map to move this work location.')">Move on Map</button><button class="danger" onclick="event.stopPropagation(); deleteSimLocation('${loc.id}')">Delete</button></div>`
          : "";
        return `<div class="card ${sel ? "selected" : ""}" onclick="selectSimLocation('${loc.id}')"><h3>${escapeHtml(loc.name)}</h3><p>${meta.label} • ${meta.target} • map ${Number(loc.map_x).toFixed(3)}, ${Number(loc.map_y).toFixed(3)}</p>${editor}</div>`;
      })
      .join("");

    section.innerHTML = `
      <h3 style="margin:14px 0 6px">Work Locations</h3>
      <p class="small muted">Point destinations for sim staff and vendors. They sit inside zones without changing zone access rules.</p>
      <div class="row">
        <div><label>Place as</label><select id="placeSimLocType" onchange="placeSimLocationType=this.value">${typeOptions}</select></div>
      </div>
      <p class="small">Click the map to place the selected work location type.</p>
      <div class="list" id="accessWorkLocationList">${cards || '<p class="muted">No work locations yet. Pick a type and click the map.</p>'}</div>`;

    const picker = document.getElementById("placeSimLocType");
    if (picker) {
      picker.value = placeSimLocationType;
      picker.onchange = () => {
        placeSimLocationType = picker.value;
      };
    }
  }

  window.selectSimLocation = function (id) {
    selectedSimLocationId = id;
    if (typeof selectedKind !== "undefined") {
      selectedKind = "simLocation";
      selectedId = id;
    }
    renderWorkLocationSection();
    if (typeof drawBase === "function") drawBase();
    setStatus("Selected work location.");
  };

  window.saveSimLocation = async function (id) {
    if (!getDashEvent()) return;
    const updated = await api(`/events/${getDashEvent().id}/sim-locations/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        name: document.getElementById("editSimLocName")?.value,
        location_type: document.getElementById("editSimLocType")?.value,
        map_x: parseFloat(document.getElementById("editSimLocMapX")?.value),
        map_y: parseFloat(document.getElementById("editSimLocMapY")?.value),
        updated_by: "dash_access",
      }),
    });
    const idx = accessSimLocations.findIndex((l) => l.id === id);
    if (idx >= 0) accessSimLocations[idx] = updated;
    renderWorkLocationSection();
    if (typeof drawBase === "function") drawBase();
    setStatus(`Saved work location "${updated.name}".`);
  };

  window.deleteSimLocation = async function (id) {
    if (!getDashEvent() || !confirm("Delete this work location?")) return;
    await api(`/events/${getDashEvent().id}/sim-locations/${id}`, { method: "DELETE" });
    accessSimLocations = accessSimLocations.filter((l) => l.id !== id);
    if (selectedSimLocationId === id) selectedSimLocationId = null;
    renderWorkLocationSection();
    if (typeof drawBase === "function") drawBase();
    setStatus("Deleted work location.");
  };

  function updateRfidSectionVisibility() {
    const section = document.getElementById("accessRfidSection");
    if (section) section.classList.toggle("hidden", accessTool !== "rfidDevices");
    updateWorkLocationSectionVisibility();
  }

  function syncPortalFlowFlipButton(gate) {
    const btn = document.getElementById("portalFlowFlipBtn");
    if (!btn) return;
    const flipped = gate ? gateFlowFlipped(gate) : false;
    btn.classList.toggle("active", flipped);
    btn.textContent = flipped ? "⇄ Flipped" : "⇄ Flip direction";
  }

  function updateAccessMapPanel() {
    const orient = document.getElementById("accessPortalOrient");
    syncAccessLayerCheckboxes();

    const gateSelected =
      typeof selectedKind !== "undefined" && selectedKind === "gate" && typeof selectedId !== "undefined" && selectedId;
    const newGateSelected = typeof selectedKind !== "undefined" && selectedKind === "newGate";
    const gate = gateSelected ? (getDashGates() || []).find((g) => g.id === selectedId) : null;
    const previewGate = newGateSelected ? getNewGatePreview() : null;
    const activeGate = gate || previewGate;

    if (orient) {
      orient.classList.toggle("hidden", !activeGate);
      if (activeGate) {
        const title = document.getElementById("accessPortalOrientTitle");
        const deg = document.getElementById("accessPortalOrientDeg");
        const slider = document.getElementById("mapPortalFenceHeading");
        const heading = Math.round(gateFenceHeading(activeGate));
        if (title) {
          title.textContent = previewGate
            ? "New scanner — fence heading"
            : `${activeGate.name || "Scanner"} — fence heading`;
        }
        if (deg) deg.textContent = `${heading}°`;
        if (slider && document.activeElement !== slider) slider.value = String(heading);
        syncPortalFlowFlipButton(gate);
      }
    }
  }

  function getNewGatePreview() {
    if (typeof selectedKind === "undefined" || selectedKind !== "newGate") return null;
    const mx = parseFloat(document.getElementById("newGateMapX")?.value);
    const my = parseFloat(document.getElementById("newGateMapY")?.value);
    if (!Number.isFinite(mx) || !Number.isFinite(my)) return null;
    const heading = parseInt(
      document.getElementById("mapPortalFenceHeading")?.value ||
        document.getElementById("newGateFenceHeading")?.value ||
        "0",
      10
    );
    return {
      id: "__new_gate_preview__",
      name: document.getElementById("newGateName")?.value || "New scanner",
      map_x: mx,
      map_y: my,
      fence_heading_deg: heading,
    };
  }

  function gatesForSnapDrawing() {
    const list = [...(getDashGates() || [])];
    const preview = getNewGatePreview();
    if (preview) list.push(preview);
    return list;
  }

  function setAccessLayer(key, enabled) {
    accessLayers[key] = !!enabled;
    saveAccessLayerPrefs();
    syncAccessLayerCheckboxes();
    if (typeof drawBase === "function") drawBase();
    else {
      decorateGateMarkers();
      drawAccessLayers();
    }
    updateAccessMapPanel();
  }

  function zoneLabel(cls) {
    return ({ ga: "GA", vip: "VIP", staff: "Staff", backstage: "Backstage", vendor: "Vendor" }[cls] || cls);
  }

  function hexToRgba(hex, alphaPct) {
    const raw = (hex || "#4caf50").replace("#", "");
    const full =
      raw.length === 3
        ? raw
            .split("")
            .map((c) => c + c)
            .join("")
        : raw.slice(0, 6);
    const r = parseInt(full.slice(0, 2), 16);
    const g = parseInt(full.slice(2, 4), 16);
    const b = parseInt(full.slice(4, 6), 16);
    const a = Math.max(0.1, Math.min(0.9, (alphaPct ?? 38) / 100));
    return `rgba(${r},${g},${b},${a.toFixed(2)})`;
  }

  function parseRgbaColor(value) {
    const fallback = { color: "#4caf50", opacity: 38 };
    if (!value) return fallback;
    const rgba = value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/i);
    if (!rgba) {
      if (value.startsWith("#")) return { color: value.slice(0, 7), opacity: 38 };
      return fallback;
    }
    const r = Number(rgba[1]);
    const g = Number(rgba[2]);
    const b = Number(rgba[3]);
    const a = rgba[4] != null ? Number(rgba[4]) : 1;
    const toHex = (n) => n.toString(16).padStart(2, "0");
    return {
      color: `#${toHex(r)}${toHex(g)}${toHex(b)}`,
      opacity: Math.round(Math.max(10, Math.min(90, a * 100))),
    };
  }

  function classColorStorageKey(cls) {
    return `beacon_zone_color_${cls || "ga"}`;
  }

  function getStoredClassColor(cls) {
    try {
      const raw = localStorage.getItem(classColorStorageKey(cls));
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function getDefaultClassColor(cls) {
    const stored = getStoredClassColor(cls);
    if (stored?.color) return stored;
    return parseRgbaColor(ZONE_COLORS[cls] || ZONE_COLORS.ga);
  }

  function getSelectedFillColor() {
    const color = document.getElementById("accessZoneColor")?.value || "#4caf50";
    const opacity = Number(document.getElementById("accessZoneOpacity")?.value || 38);
    return hexToRgba(color, opacity);
  }

  function setFillColorInputs(color, opacity) {
    const colorEl = document.getElementById("accessZoneColor");
    const opacityEl = document.getElementById("accessZoneOpacity");
    if (colorEl && color) colorEl.value = color;
    if (opacityEl && opacity != null) opacityEl.value = String(opacity);
    syncFillColorPreview();
  }

  function syncFillColorPreview() {
    const preview = document.getElementById("accessZoneColorPreview");
    const label = document.getElementById("accessZoneOpacityLabel");
    const fill = getSelectedFillColor();
    if (preview) preview.style.background = fill;
    if (label) label.textContent = `${document.getElementById("accessZoneOpacity")?.value || 38}%`;
    document.querySelectorAll("[data-zone-preset]").forEach((btn) => {
      const match =
        btn.dataset.zoneColor === (document.getElementById("accessZoneColor")?.value || "") &&
        Number(btn.dataset.zoneOpacity) === Number(document.getElementById("accessZoneOpacity")?.value || 0);
      btn.classList.toggle("active", match);
    });
  }

  function renderZonePresets() {
    const host = document.getElementById("accessZonePresets");
    if (!host) return;
    host.innerHTML = ZONE_PRESETS.map(
      (preset) =>
        `<button type="button" class="zoneColorSwatch" data-zone-preset="1" data-zone-color="${preset.color}" data-zone-opacity="${preset.opacity}" title="${escapeHtml(preset.name)}" style="background:${hexToRgba(preset.color, preset.opacity)}"></button>`
    ).join("");
    host.querySelectorAll("[data-zone-preset]").forEach((btn) => {
      btn.onclick = () => {
        setFillColorInputs(btn.getAttribute("data-zone-color"), Number(btn.getAttribute("data-zone-opacity")));
      };
    });
    syncFillColorPreview();
  }

  function applyClassDefaultColor() {
    const cls = document.getElementById("accessZoneClass")?.value || fillZoneClass || "ga";
    const defaults = getDefaultClassColor(cls);
    setFillColorInputs(defaults.color, defaults.opacity);
  }

  function gateFenceHeading(gate) {
    if (
      portalHeadingPreview != null &&
      typeof selectedKind !== "undefined" &&
      (selectedKind === "gate" || selectedKind === "newGate") &&
      typeof selectedId !== "undefined" &&
      (gate?.id === selectedId || gate?.id === "__new_gate_preview__")
    ) {
      return ((portalHeadingPreview % 360) + 360) % 360;
    }
    return Number(gate?.fence_heading_deg ?? gate?.fenceHeadingDeg ?? 0) % 360;
  }

  function gateFlowFlipped(gate) {
    if (
      portalFlowFlipPreview != null &&
      typeof selectedKind !== "undefined" &&
      selectedKind === "gate" &&
      typeof selectedId !== "undefined" &&
      gate?.id === selectedId
    ) {
      return portalFlowFlipPreview;
    }
    return !!(gate?.portal_flow_flipped ?? gate?.portalFlowFlipped);
  }

  function getPortalFlowHeading(gate) {
    const fence = gateFenceHeading(gate);
    const flipped = gateFlowFlipped(gate);
    return (fence + 90 + (flipped ? 180 : 0)) % 360;
  }

  function headingUnitRad(deg) {
    const rad = (deg * Math.PI) / 180;
    return { ux: Math.cos(rad), uy: Math.sin(rad) };
  }

  function getPortalSnapPair(gate) {
    const cx = gate?.map_x ?? gate?.mapX;
    const cy = gate?.map_y ?? gate?.mapY;
    if (cx == null || cy == null) return null;
    const heading = gateFenceHeading(gate);
    const { ux, uy } = headingUnitRad(heading);
    return {
      gateId: gate.id,
      gateName: gate.name || "Scanner",
      center: { x: cx, y: cy },
      heading,
      a: { x: cx - ux * PORTAL_SNAP_DIST, y: cy - uy * PORTAL_SNAP_DIST, side: "a" },
      b: { x: cx + ux * PORTAL_SNAP_DIST, y: cy + uy * PORTAL_SNAP_DIST, side: "b" },
    };
  }

  function iterBarrierSegments(barrier) {
    const pts = barrier?.points || [];
    if (pts.length < 2) return [];
    const closed = !!barrier.closed;
    const segCount = pts.length - 1 + (closed && pts.length >= 3 ? 1 : 0);
    const out = [];
    for (let i = 0; i < segCount; i++) {
      out.push({ segIndex: i, a: pts[i], b: pts[(i + 1) % pts.length] });
    }
    return out;
  }

  function projectPointOnSegment(a, b, px, py) {
    const ax = a.x;
    const ay = a.y;
    const bx = b.x;
    const by = b.y;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    if (len2 < 1e-12) {
      const dist = Math.hypot(px - ax, py - ay);
      return { t: 0, x: ax, y: ay, dist };
    }
    let t = ((px - ax) * dx + (py - ay) * dy) / len2;
    t = Math.max(0, Math.min(1, t));
    const x = ax + dx * t;
    const y = ay + dy * t;
    return { t, x, y, dist: Math.hypot(px - x, py - y) };
  }

  function segmentTangentHeadingDeg(a, b) {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    return ((Math.atan2(dy, dx) * 180) / Math.PI + 360) % 360;
  }

  function fenceCrossingHeadingDeg(a, b) {
    return (segmentTangentHeadingDeg(a, b) + 90) % 360;
  }

  function findNearestBarrierSegment(px, py) {
    let best = null;
    accessBarriers.forEach((barrier) => {
      iterBarrierSegments(barrier).forEach(({ segIndex, a, b }) => {
        const proj = projectPointOnSegment(a, b, px, py);
        if (!best || proj.dist < best.dist) {
          best = {
            barrier_id: barrier.id,
            barrier_name: barrier.name,
            segIndex,
            t: proj.t,
            x: proj.x,
            y: proj.y,
            dist: proj.dist,
            a,
            b,
          };
        }
      });
    });
    return best;
  }

  function snapToExistingBarrier(p) {
    let best = null;
    let bestDist = BARRIER_ENDPOINT_SNAP_RADIUS;
    accessBarriers.forEach((barrier) => {
      (barrier.points || []).forEach((pt, idx) => {
        const d = Math.hypot(p.x - pt.x, p.y - pt.y);
        if (d < bestDist) {
          bestDist = d;
          best = {
            x: pt.x,
            y: pt.y,
            snapped: true,
            snapKind: "barrier_endpoint",
            barrierId: barrier.id,
            barrierName: barrier.name,
            pointIndex: idx,
          };
        }
      });
    });
    if (best) return best;

    bestDist = BARRIER_SEGMENT_SNAP_RADIUS;
    accessBarriers.forEach((barrier) => {
      iterBarrierSegments(barrier).forEach(({ segIndex, a, b }) => {
        const proj = projectPointOnSegment(a, b, p.x, p.y);
        if (proj.dist < bestDist) {
          bestDist = proj.dist;
          best = {
            x: proj.x,
            y: proj.y,
            snapped: true,
            snapKind: "barrier_segment",
            barrierId: barrier.id,
            barrierName: barrier.name,
            segIndex,
            t: proj.t,
          };
        }
      });
    });
    return best || { x: p.x, y: p.y, snapped: false };
  }

  function snapBarrierPoint(p, gates) {
    const scannerSnap = snapAccessPoint(p, gates);
    if (scannerSnap.snapped) return scannerSnap;
    const barrierSnap = snapToExistingBarrier(p);
    if (barrierSnap.snapped) return barrierSnap;
    return { x: p.x, y: p.y, snapped: false };
  }

  function drawNormSegmentWithGaps(grid, a, b, gaps, mark) {
    const ax = a.x;
    const ay = a.y;
    const bx = b.x;
    const by = b.y;
    const segLen = Math.hypot(bx - ax, by - ay);
    if (segLen < 1e-9) return;
    let intervals = [[0, 1]];
    gaps
      .slice()
      .sort((x, y) => x[0] - y[0])
      .forEach(([tCenter, halfWidth]) => {
        const halfT = halfWidth / segLen;
        const gapLo = Math.max(0, tCenter - halfT);
        const gapHi = Math.min(1, tCenter + halfT);
        const next = [];
        intervals.forEach(([lo, hi]) => {
          if (hi <= gapLo || lo >= gapHi) {
            next.push([lo, hi]);
          } else {
            if (lo < gapLo) next.push([lo, gapLo]);
            if (hi > gapHi) next.push([gapHi, hi]);
          }
        });
        intervals = next;
      });
    intervals.forEach(([lo, hi]) => {
      if (hi - lo < 1e-6) return;
      const x0 = ax + (bx - ax) * lo;
      const y0 = ay + (by - ay) * lo;
      const x1 = ax + (bx - ax) * hi;
      const y1 = ay + (by - ay) * hi;
      const ga = gridFromNorm(x0, y0);
      const gb = gridFromNorm(x1, y1);
      drawGridLine(grid, ga.gx, ga.gy, gb.gx, gb.gy, mark);
    });
  }

  function gateSegmentGaps(gate, a, b) {
    const cx = gate?.map_x ?? gate?.mapX;
    const cy = gate?.map_y ?? gate?.mapY;
    if (cx == null || cy == null) return [];
    let t = gate.barrier_segment_t;
    if (t == null) t = projectPointOnSegment(a, b, cx, cy).t;
    return [[Number(t), PORTAL_GAP_HALF_WIDTH]];
  }

  function collectGateAttachments(gates) {
    const attachments = new Map();
    (gates || []).forEach((gate) => {
      if (!gate.barrier_id || gate.barrier_segment_index == null) return;
      const key = `${gate.barrier_id}:${gate.barrier_segment_index}`;
      if (!attachments.has(key)) attachments.set(key, []);
      attachments.get(key).push(gate);
    });
    return attachments;
  }

  function snapAccessPoint(p, gates) {
    let best = null;
    let bestDist = PORTAL_SNAP_RADIUS;
    (gates || []).forEach((gate) => {
      const pair = getPortalSnapPair(gate);
      if (!pair) return;
      [pair.a, pair.b].forEach((pt) => {
        const d = Math.hypot(p.x - pt.x, p.y - pt.y);
        if (d < bestDist) {
          bestDist = d;
          best = {
            x: pt.x,
            y: pt.y,
            snapped: true,
            gateId: gate.id,
            gateName: pair.gateName,
            side: pt.side,
          };
        }
      });
    });
    return best || { x: p.x, y: p.y, snapped: false };
  }

  function addDraftBarrierPoint(p, snapInfo) {
    draftBarrierPoints.push({ x: p.x, y: p.y });
    drawAccessLayers();
    if (snapInfo?.snapped) {
      if (snapInfo.snapKind === "barrier_endpoint") {
        setStatus(`Snapped to ${snapInfo.barrierName} corner (point ${draftBarrierPoints.length}).`);
      } else if (snapInfo.snapKind === "barrier_segment") {
        setStatus(`Snapped to ${snapInfo.barrierName} edge (point ${draftBarrierPoints.length}).`);
      } else {
        setStatus(`Snapped to ${snapInfo.gateName} side ${snapInfo.side.toUpperCase()} (point ${draftBarrierPoints.length}).`);
      }
    } else {
      setStatus(`Barrier point ${draftBarrierPoints.length}. Snap to corners/edges or click Close Perimeter when done.`);
    }
  }

  function ensureZoneSvg() {
    const wrap = document.getElementById("mapStage") || document.getElementById("mapWrap");
    if (!wrap) return null;
    let svg = document.getElementById("zoneSvg");
    if (!svg) {
      svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.id = "zoneSvg";
      svg.setAttribute("viewBox", `0 0 ${SVG_W} ${SVG_H}`);
      svg.classList.add("pathLine");
      svg.style.pointerEvents = "none";
      wrap.appendChild(svg);
    }
    return svg;
  }

  function toSvg(x, y) {
    return { x: x * SVG_W, y: y * SVG_H };
  }

  function gridFromNorm(x, y) {
    return {
      gx: Math.max(0, Math.min(GRID_W - 1, Math.round(x * (GRID_W - 1)))),
      gy: Math.max(0, Math.min(GRID_H - 1, Math.round(y * (GRID_H - 1)))),
    };
  }

  function normFromGrid(gx, gy) {
    return { x: gx / (GRID_W - 1), y: gy / (GRID_H - 1) };
  }

  function addPortalVirtualWall(grid, gate) {
    const pair = getPortalSnapPair(gate);
    if (!pair) return;
    const mark = (gx, gy) => {
      if (gx >= 0 && gx < GRID_W && gy >= 0 && gy < GRID_H) grid[gy][gx] = 1;
    };
    const { ux, uy } = headingUnitRad(pair.heading);
    const extend = 0.006;
    const ax = pair.a.x - ux * extend;
    const ay = pair.a.y - uy * extend;
    const bx = pair.b.x + ux * extend;
    const by = pair.b.y + uy * extend;
    const a = gridFromNorm(ax, ay);
    const b = gridFromNorm(bx, by);
    drawGridLine(grid, a.gx, a.gy, b.gx, b.gy, mark);
  }

  function rasterizeWalls(grid, gates) {
    const mark = (gx, gy) => {
      if (gx >= 0 && gx < GRID_W && gy >= 0 && gy < GRID_H) grid[gy][gx] = 1;
    };
    const attachments = collectGateAttachments(gates);

    accessBarriers.forEach((barrier) => {
      iterBarrierSegments(barrier).forEach(({ segIndex, a, b }) => {
        const key = `${barrier.id}:${segIndex}`;
        const segGates = attachments.get(key) || [];
        const gaps = [];
        segGates.forEach((gate) => {
          gateSegmentGaps(gate, a, b).forEach((gap) => gaps.push(gap));
        });
        drawNormSegmentWithGaps(grid, a, b, gaps, mark);
      });
    });

    (gates || []).forEach((gate) => addPortalVirtualWall(grid, gate));
  }

  function drawGridLine(grid, x0, y0, x1, y1, mark) {
    let dx = Math.abs(x1 - x0);
    let dy = Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1;
    const sy = y0 < y1 ? 1 : -1;
    let err = dx - dy;
    while (true) {
      mark(x0, y0);
      for (let oy = -1; oy <= 1; oy++) {
        for (let ox = -1; ox <= 1; ox++) mark(x0 + ox, y0 + oy);
      }
      if (x0 === x1 && y0 === y1) break;
      const e2 = 2 * err;
      if (e2 > -dy) {
        err -= dy;
        x0 += sx;
      }
      if (e2 < dx) {
        err += dx;
        y0 += sy;
      }
    }
  }

  function cornerToNorm(gx, gy) {
    return { x: gx / GRID_W, y: gy / GRID_H };
  }

  function cellFilled(filled, cx, cy) {
    if (cx < 0 || cy < 0 || cx >= GRID_W || cy >= GRID_H) return false;
    return filled[cy][cx];
  }

  function simplifyOrthogonalPolygon(points) {
    if (points.length < 4) return points;
    const merged = [];
    const eps = 1e-9;
    for (let i = 0; i < points.length; i++) {
      const prev = points[(i - 1 + points.length) % points.length];
      const curr = points[i];
      const next = points[(i + 1) % points.length];
      const sameX = Math.abs(prev.x - curr.x) < eps && Math.abs(curr.x - next.x) < eps;
      const sameY = Math.abs(prev.y - curr.y) < eps && Math.abs(curr.y - next.y) < eps;
      if (!sameX && !sameY) merged.push(curr);
    }
    return merged.length >= 3 ? merged : points;
  }

  function traceBoundaryPolygon(filled) {
    const segments = [];
    for (let cy = 0; cy < GRID_H; cy++) {
      for (let cx = 0; cx < GRID_W; cx++) {
        if (!filled[cy][cx]) continue;
        if (!cellFilled(filled, cx, cy - 1)) segments.push([cx, cy, cx + 1, cy]);
        if (!cellFilled(filled, cx + 1, cy)) segments.push([cx + 1, cy, cx + 1, cy + 1]);
        if (!cellFilled(filled, cx, cy + 1)) segments.push([cx + 1, cy + 1, cx, cy + 1]);
        if (!cellFilled(filled, cx - 1, cy)) segments.push([cx, cy + 1, cx, cy]);
      }
    }
    if (!segments.length) return [];

    const adj = new Map();
    const key = (x, y) => `${x},${y}`;
    segments.forEach(([x1, y1, x2, y2]) => {
      if (!adj.has(key(x1, y1))) adj.set(key(x1, y1), []);
      adj.get(key(x1, y1)).push([x2, y2]);
    });

    const polygon = [];
    let x = segments[0][0];
    let y = segments[0][1];
    const startX = x;
    const startY = y;
    let prevX = null;
    let prevY = null;
    const used = new Set();

    for (let guard = 0; guard <= segments.length + 2; guard++) {
      polygon.push(cornerToNorm(x, y));
      const outs = adj.get(key(x, y)) || [];
      let next = null;
      for (const [nx, ny] of outs) {
        const edgeKey = `${x},${y}->${nx},${ny}`;
        if (used.has(edgeKey)) continue;
        if (prevX !== null && nx === prevX && ny === prevY) continue;
        next = [nx, ny];
        used.add(edgeKey);
        break;
      }
      if (!next) break;
      if (next[0] === startX && next[1] === startY && polygon.length >= 3) break;
      prevX = x;
      prevY = y;
      x = next[0];
      y = next[1];
    }

    return simplifyOrthogonalPolygon(polygon);
  }

  function floodFillRegion(seedX, seedY, gates) {
    const grid = Array.from({ length: GRID_H }, () => Array(GRID_W).fill(0));
    rasterizeWalls(grid, gates);
    const seed = gridFromNorm(seedX, seedY);
    if (grid[seed.gy][seed.gx] === 1) {
      throw new Error("Click inside an open area, not on a barrier.");
    }

    const filled = Array.from({ length: GRID_H }, () => Array(GRID_W).fill(false));
    const q = [[seed.gx, seed.gy]];
    filled[seed.gy][seed.gx] = true;
    let touchesEdge = false;

    while (q.length) {
      const [cx, cy] = q.shift();
      if (cx === 0 || cy === 0 || cx === GRID_W - 1 || cy === GRID_H - 1) touchesEdge = true;
      [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => {
        const nx = cx + dx;
        const ny = cy + dy;
        if (nx < 0 || ny < 0 || nx >= GRID_W || ny >= GRID_H) return;
        if (filled[ny][nx] || grid[ny][nx] === 1) return;
        filled[ny][nx] = true;
        q.push([nx, ny]);
      });
    }

    if (touchesEdge) {
      throw new Error("That area is open to the map edge. Close it with barriers first.");
    }

    const polygon = traceBoundaryPolygon(filled);
    if (polygon.length < 3) {
      throw new Error("Could not build a zone polygon from that click.");
    }
    return polygon;
  }

  function drawAccessLayers() {
    const svg = ensureZoneSvg();
    if (!svg) return;
    svg.innerHTML = "";

    accessZones.forEach((zone) => {
      if (!accessLayers.zones) return;
      const pts = zone.polygon || [];
      if (pts.length < 3) return;
      const poly = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      poly.setAttribute(
        "points",
        pts.map((p) => `${p.x * SVG_W},${p.y * SVG_H}`).join(" ")
      );
      poly.setAttribute("fill", zone.fill_color || ZONE_COLORS[zone.zone_class] || ZONE_COLORS.ga);
      poly.setAttribute("stroke", selectedZoneId === zone.id ? "#6df7a7" : "rgba(255,255,255,0.55)");
      poly.setAttribute("stroke-width", selectedZoneId === zone.id ? "4" : "2");
      poly.style.pointerEvents = "auto";
      poly.onclick = (ev) => {
        ev.stopPropagation();
        selectZone(zone.id);
      };
      svg.appendChild(poly);
    });

    accessBarriers.forEach((barrier) => {
      if (!accessLayers.barriers) return;
      const pts = barrier.points || [];
      if (pts.length < 2) return;
      const pl = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      pl.setAttribute("fill", "none");
      const closedPts = barrier.closed && pts.length >= 3 ? [...pts, pts[0]] : pts;
      pl.setAttribute(
        "points",
        closedPts.map((p) => `${p.x * SVG_W},${p.y * SVG_H}`).join(" ")
      );
      pl.setAttribute("stroke", selectedBarrierId === barrier.id ? "#6df7a7" : "#ff8a65");
      pl.setAttribute("stroke-width", selectedBarrierId === barrier.id ? "7" : "5");
      pl.setAttribute("stroke-linecap", "round");
      pl.setAttribute("stroke-linejoin", "round");
      pl.style.pointerEvents = "stroke";
      pl.onclick = (ev) => {
        ev.stopPropagation();
        selectBarrier(barrier.id);
      };
      svg.appendChild(pl);
    });

    if (draftBarrierPoints.length >= 1 && (accessLayers.barriers || accessTool === "drawBarrier")) {
      const draftPts = draftBarrierPoints.slice();
      if (draftBarrierClosed && draftPts.length >= 3) draftPts.push(draftPts[0]);
      const draft = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      draft.setAttribute("fill", "none");
      draft.setAttribute(
        "points",
        draftPts.map((p) => `${p.x * SVG_W},${p.y * SVG_H}`).join(" ")
      );
      draft.setAttribute("stroke", "#ffd166");
      draft.setAttribute("stroke-width", "4");
      draft.setAttribute("stroke-dasharray", "8 6");
      svg.appendChild(draft);
    }

    if (accessLayers.snapPoints || accessLayers.gates) {
      drawPortalSnapLayers(svg);
    } else if (
      (typeof selectedKind !== "undefined" && (selectedKind === "gate" || selectedKind === "newGate")) ||
      accessTool === "drawBarrier"
    ) {
      const onlyId =
        selectedKind === "gate"
          ? selectedId
          : selectedKind === "newGate"
            ? "__new_gate_preview__"
            : null;
      drawPortalSnapLayers(svg, onlyId);
    }
  }

  function drawPortalFlowArrow(svg, gate, pair, isSelected) {
    const cx = pair.center.x * SVG_W;
    const cy = pair.center.y * SVG_H;
    const deg = getPortalFlowHeading(gate);
    const rad = (deg * Math.PI) / 180;
    const ux = Math.cos(rad);
    const uy = Math.sin(rad);
    const len = 26;
    const tipX = cx + ux * len;
    const tipY = cy + uy * len;
    const color = isSelected ? "#ffe082" : "#ffca28";

    const shaft = document.createElementNS("http://www.w3.org/2000/svg", "line");
    shaft.setAttribute("x1", String(cx));
    shaft.setAttribute("y1", String(cy));
    shaft.setAttribute("x2", String(tipX));
    shaft.setAttribute("y2", String(tipY));
    shaft.setAttribute("stroke", color);
    shaft.setAttribute("stroke-width", "3.5");
    shaft.setAttribute("stroke-linecap", "round");
    shaft.setAttribute("opacity", "0.95");
    shaft.style.pointerEvents = "none";
    svg.appendChild(shaft);

    const backRad = rad + Math.PI;
    const wing = 0.45;
    const headLen = 9;
    const hx1 = tipX + Math.cos(backRad + wing) * headLen;
    const hy1 = tipY + Math.sin(backRad + wing) * headLen;
    const hx2 = tipX + Math.cos(backRad - wing) * headLen;
    const hy2 = tipY + Math.sin(backRad - wing) * headLen;
    const head = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    head.setAttribute("points", `${tipX},${tipY} ${hx1},${hy1} ${hx2},${hy2}`);
    head.setAttribute("fill", color);
    head.setAttribute("stroke", "#ffffff");
    head.setAttribute("stroke-width", "1");
    head.style.pointerEvents = "none";
    svg.appendChild(head);
  }

  function gateMarkerHalfPx(gate) {
    const scale = getScannerMarkerScale();
    const t = String(gate?.device_type || gate?.deviceType || "scanner").toLowerCase();
    if (t === "handheld") return { w: 7 * scale, h: 11 * scale };
    if (t === "ipad") return { w: 11 * scale, h: 8 * scale };
    return { w: 12 * scale, h: 6 * scale };
  }

  function drawPortalFenceSnapGraphics(svg, gate, pair, isSelected) {
    const fence = document.createElementNS("http://www.w3.org/2000/svg", "line");
    fence.setAttribute("x1", String(pair.a.x * SVG_W));
    fence.setAttribute("y1", String(pair.a.y * SVG_H));
    fence.setAttribute("x2", String(pair.b.x * SVG_W));
    fence.setAttribute("y2", String(pair.b.y * SVG_H));
    fence.setAttribute("class", "gateFenceLine");
    fence.setAttribute("stroke", isSelected ? "#6df7a7" : "#64b5f6");
    fence.setAttribute("stroke-width", isSelected ? "3" : "2.5");
    svg.appendChild(fence);

    [pair.a, pair.b].forEach((pt) => {
      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", String(pt.x * SVG_W));
      dot.setAttribute("cy", String(pt.y * SVG_H));
      dot.setAttribute("r", isSelected ? "5" : "4");
      dot.setAttribute("class", `gateSnapSvgDot${isSelected ? " selected" : ""}`);
      svg.appendChild(dot);
    });
  }

  function decorateGateMarkers() {
    document.querySelectorAll(".marker.gate .gateSnapDot").forEach((d) => d.remove());
    const gateSelected =
      typeof selectedKind !== "undefined" && selectedKind === "gate" && typeof selectedId !== "undefined" && selectedId;
    const newGateSelected = typeof selectedKind !== "undefined" && selectedKind === "newGate";
    const show =
      accessLayers.snapPoints || accessTool === "drawBarrier" || gateSelected || newGateSelected;
    if (!show) return;

    gatesForSnapDrawing().forEach((gate) => {
      if (gate.id === "__new_gate_preview__" && !newGateSelected) return;
      const el =
        gate.id === "__new_gate_preview__"
          ? null
          : document.querySelector(`.marker.gate[data-gate-id="${gate.id}"]`);
      if (gate.id !== "__new_gate_preview__" && !el) return;
      const pair = getPortalSnapPair(gate);
      if (!pair) return;
      const { ux, uy } = headingUnitRad(pair.heading);
      const half = gateMarkerHalfPx(gate);
      const edge = Math.max(half.w, half.h) * 0.52;
      const isSelected =
        (typeof selectedKind !== "undefined" && selectedKind === "gate" && selectedId === gate.id) ||
        gate.id === "__new_gate_preview__";

      if (gate.id === "__new_gate_preview__") return;

      [
        { side: "a", pt: pair.a, sign: -1 },
        { side: "b", pt: pair.b, sign: 1 },
      ].forEach(({ side, pt, sign }) => {
        const dot = document.createElement("span");
        dot.className = `gateSnapDot${accessTool === "drawBarrier" ? " gateSnapDotHit" : ""}${isSelected ? " selected" : ""}`;
        dot.style.left = `calc(50% + ${(ux * edge * sign).toFixed(2)}px)`;
        dot.style.top = `calc(50% + ${(uy * edge * sign).toFixed(2)}px)`;
        dot.title = accessTool === "drawBarrier" ? `Snap barrier to ${pair.gateName}` : "";
        if (accessTool === "drawBarrier") {
          dot.onclick = (ev) => {
            ev.stopPropagation();
            addDraftBarrierPoint(
              { x: pt.x, y: pt.y },
              { snapped: true, gateName: pair.gateName, side }
            );
          };
        } else {
          dot.style.pointerEvents = "none";
        }
        el.appendChild(dot);
      });
    });
  }

  function drawPortalSnapLayers(svg, onlyGateId) {
    const selectedGateId =
      typeof selectedKind !== "undefined" && selectedKind === "gate" ? selectedId : null;
    const previewGate = getNewGatePreview();
    const showAllSnaps = accessLayers.snapPoints || accessTool === "drawBarrier";

    gatesForSnapDrawing().forEach((gate) => {
      if (onlyGateId && gate.id !== onlyGateId) return;
      const pair = getPortalSnapPair(gate);
      if (!pair) return;
      const isSelected =
        gate.id === selectedGateId || gate.id === "__new_gate_preview__" || gate.id === onlyGateId;
      const showSnap = showAllSnaps || isSelected;
      const showFlow = accessLayers.snapPoints || accessLayers.gates || isSelected;

      if (showSnap) drawPortalFenceSnapGraphics(svg, gate, pair, isSelected);

      if (accessTool === "drawBarrier") {
        [pair.a, pair.b].forEach((pt) => {
          const hit = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          hit.setAttribute("cx", String(pt.x * SVG_W));
          hit.setAttribute("cy", String(pt.y * SVG_H));
          hit.setAttribute("r", "14");
          hit.setAttribute("fill", "transparent");
          hit.setAttribute("data-portal-snap", "1");
          hit.style.pointerEvents = "auto";
          hit.style.cursor = "crosshair";
          hit.onclick = (ev) => {
            ev.stopPropagation();
            addDraftBarrierPoint(
              { x: pt.x, y: pt.y },
              { snapped: true, gateName: pair.gateName, side: pt.side }
            );
          };
          svg.appendChild(hit);
        });
      }

      if (showFlow && gate.id !== "__new_gate_preview__") {
        drawPortalFlowArrow(svg, gate, pair, isSelected);
      }
    });
  }

  function clearAccessOverlay() {
    const svg = document.getElementById("zoneSvg");
    if (svg) svg.innerHTML = "";
  }

  async function loadAccessLayout() {
    if (!getDashEvent()) return;
    const eventId = getDashEvent().id;
    accessBarriers = await api(`/events/${eventId}/access-barriers`);
    accessZones = await api(`/events/${eventId}/access-zones`);
    accessSimLocations = await api(`/events/${eventId}/sim-locations`);
    renderAccessLists();
    if (typeof currentTab !== "undefined" && currentTab === "access") drawAccessLayers();
  }

  function setAccessTool(tool) {
    accessTool = tool;
    draftBarrierPoints = [];
    draftBarrierClosed = false;
    document.querySelectorAll("[data-access-tool]").forEach((btn) => {
      btn.classList.toggle("primary", btn.dataset.accessTool === tool);
    });
    const hints = {
      select: "Select barriers, zones, or scanners on the map or in the list.",
      drawBarrier: "Trace a perimeter fence/barricade. Points snap to existing corners, edges, and scanner snap dots.",
      fillZone: "Click inside a closed barrier perimeter. Place scanners on fence segments to create entry gaps.",
      linkPortal: "Select a scanner on the map or use Scanners to edit rules per device.",
      rfidDevices: "Add, edit, or place scanners on the map.",
      workLocations:
        "Place staff/vendor work spots on the map. Sim routes staff and vendors here without creating nested zones.",
    };
    setStatus(hints[tool] || "Access control ready.");
    updateRfidSectionVisibility();
    if (tool === "rfidDevices" && typeof renderAccessRfidList === "function") renderAccessRfidList();
    renderWorkLocationSection();
    updateAccessMapPanel();
    if (typeof drawBase === "function") drawBase();
  }

  function renderAccessLists() {
    const barrierList = document.getElementById("accessBarrierList");
    const zoneList = document.getElementById("accessZoneList");
    if (!barrierList || !zoneList) return;

    barrierList.innerHTML =
      accessBarriers
        .map(
          (b) =>
            `<div class="card ${selectedBarrierId === b.id ? "selected" : ""}" onclick="selectAccessBarrier('${b.id}')"><h3>${escapeHtml(b.name)}</h3><p>${escapeHtml(b.barrier_type)} • ${(b.points || []).length} points${b.closed ? " • closed perimeter" : ""}</p><button class="danger" onclick="event.stopPropagation(); deleteAccessBarrier('${b.id}')">Delete</button></div>`
        )
        .join("") || '<p class="muted">No barriers yet.</p>';

    zoneList.innerHTML =
      accessZones
        .map((z) => {
          const swatch = z.fill_color || ZONE_COLORS[z.zone_class] || ZONE_COLORS.ga;
          return `<div class="card ${selectedZoneId === z.id ? "selected" : ""}" onclick="selectAccessZone('${z.id}')"><div class="row" style="align-items:center;gap:10px"><span class="zoneColorSwatch" style="background:${swatch}"></span><div><h3>${escapeHtml(z.name)}</h3><p>${zoneLabel(z.zone_class)} • ${(z.polygon || []).length} vertices</p></div></div><button class="danger" onclick="event.stopPropagation(); deleteAccessZone('${z.id}')">Delete</button></div>`;
        })
        .join("") || '<p class="muted">No zones yet.</p>';

    renderZoneEditor();
    if (accessTool === "rfidDevices" && typeof renderAccessRfidList === "function") renderAccessRfidList();
    else if (typeof renderAccessRfidList !== "function") renderPortalEditor();
    renderWorkLocationSection();
  }

  function renderZoneEditor() {
    const editor = document.getElementById("accessZoneEditor");
    if (!editor) return;
    if (!selectedZoneId) {
      editor.innerHTML = "";
      return;
    }
    const zone = accessZones.find((z) => z.id === selectedZoneId);
    if (!zone) {
      editor.innerHTML = "";
      return;
    }

    const parsed = parseRgbaColor(zone.fill_color || ZONE_COLORS[zone.zone_class] || ZONE_COLORS.ga);
    editor.innerHTML = `
      <div class="card selected" style="margin-top:10px">
        <h3>Edit "${escapeHtml(zone.name)}"</h3>
        <div class="row">
          <div><label>Name</label><input id="editZoneName" value="${escapeHtml(zone.name)}" /></div>
          <div><label>Class</label><select id="editZoneClass">${["ga", "vip", "staff", "backstage", "vendor"]
            .map((c) => `<option value="${c}" ${zone.zone_class === c ? "selected" : ""}>${zoneLabel(c)}</option>`)
            .join("")}</select></div>
        </div>
        <div class="row" style="margin-top:8px;align-items:end">
          <div><label>Fill color</label><input id="editZoneColor" type="color" value="${parsed.color}" style="width:100%;height:42px;padding:4px" /></div>
          <div><label>Opacity</label><input id="editZoneOpacity" type="range" min="10" max="90" value="${parsed.opacity}" style="padding:0" /><div class="small" id="editZoneOpacityLabel">${parsed.opacity}%</div></div>
          <div><label>Preview</label><div id="editZoneColorPreview" class="zoneColorPreview" style="background:${zone.fill_color || ZONE_COLORS[zone.zone_class] || ZONE_COLORS.ga}"></div></div>
        </div>
        <div class="row" style="margin-top:10px">
          <button class="primary" onclick="saveSelectedZoneColor()">Save Zone Color</button>
        </div>
      </div>`;

    const syncEditPreview = () => {
      const fill = hexToRgba(
        document.getElementById("editZoneColor")?.value || parsed.color,
        Number(document.getElementById("editZoneOpacity")?.value || parsed.opacity)
      );
      const preview = document.getElementById("editZoneColorPreview");
      const label = document.getElementById("editZoneOpacityLabel");
      if (preview) preview.style.background = fill;
      if (label) label.textContent = `${document.getElementById("editZoneOpacity")?.value || parsed.opacity}%`;
      zone.fill_color = fill;
      drawAccessLayers();
    };
    document.getElementById("editZoneColor")?.addEventListener("input", syncEditPreview);
    document.getElementById("editZoneColor")?.addEventListener("change", syncEditPreview);
    document.getElementById("editZoneOpacity")?.addEventListener("input", syncEditPreview);
    document.getElementById("editZoneOpacity")?.addEventListener("change", syncEditPreview);
  }

  function renderPortalEditor() {
    const gatePanel = document.getElementById("gateRulesPanel");
    const fallback = document.getElementById("accessPortalEditor");
    const editor = gatePanel || fallback;
    if (!editor) return;
    if (gatePanel && fallback) fallback.innerHTML = "";
    if (selectedKind !== "gate" || !selectedId) {
      editor.innerHTML = gatePanel
        ? '<p class="muted small">Save device first, then configure scanner access rules here.</p>'
        : '<p class="muted">Select a scanner to configure zone access.</p>';
      return;
    }
    const gate = (getDashGates() || []).find((g) => g.id === selectedId);
    if (!gate) return;

    const zoneOptions = (includeBlank) => {
      const blank = includeBlank ? `<option value="">—</option>` : "";
      return (
        blank +
        accessZones
          .map((z) => `<option value="${z.id}">${escapeHtml(z.name)} (${zoneLabel(z.zone_class)})</option>`)
          .join("")
      );
    };

    const barrierOptions =
      `<option value="">—</option>` +
      accessBarriers.map((b) => `<option value="${b.id}">${escapeHtml(b.name)}</option>`).join("");

    const classes = ["ga", "vip", "staff", "backstage", "vendor"];
    const allowed = new Set(gate.allowed_classes || []);

    const rulesBody = `
        <label>Zone A (from / outside)</label>
        <select id="portalZoneA">${zoneOptions(true)}</select>
        <label>Zone B (to / inside)</label>
        <select id="portalZoneB">${zoneOptions(true)}</select>
        <label>Attached barrier segment</label>
        <select id="portalBarrier">${barrierOptions}</select>
        <label>Direction</label>
        <select id="portalDirection">
          <option value="bidirectional">Bidirectional</option>
          <option value="a_to_b">A → B only</option>
          <option value="b_to_a">B → A only</option>
        </select>
        <label>Allowed classes</label>
        <div class="row">${classes
          .map(
            (c) =>
              `<label style="display:flex;gap:6px;align-items:center"><input type="checkbox" class="portalClass" value="${c}" ${
                allowed.has(c) ? "checked" : ""
              }/> ${zoneLabel(c)}</label>`
          )
          .join("")}</div>
        <div class="row" style="margin-top:10px">
          <button class="primary" onclick="event.stopPropagation(); savePortalAccess()">Save Rules</button>
          <button onclick="event.stopPropagation(); snapPortalToBarrier()">Snap Onto Fence (create entry)</button>
        </div>`;

    editor.innerHTML = gatePanel
      ? rulesBody
      : `<div class="card selected"><h3>${escapeHtml(gate.name)} access rules</h3>${rulesBody}</div>`;

    document.getElementById("portalZoneA").value = gate.zone_a_id || "";
    document.getElementById("portalZoneB").value = gate.zone_b_id || "";
    document.getElementById("portalBarrier").value = gate.barrier_id || "";
    document.getElementById("portalDirection").value = gate.direction || "bidirectional";
    updateAccessMapPanel();
  }

  function selectBarrier(id) {
    selectedBarrierId = id;
    selectedZoneId = null;
    portalHeadingPreview = null;
    portalFlowFlipPreview = null;
    renderAccessLists();
    drawAccessLayers();
    setStatus("Selected barrier.");
  }

  function selectZone(id) {
    selectedZoneId = id;
    selectedBarrierId = null;
    portalHeadingPreview = null;
    portalFlowFlipPreview = null;
    const zone = accessZones.find((z) => z.id === id);
    if (zone) {
      const parsed = parseRgbaColor(zone.fill_color || ZONE_COLORS[zone.zone_class] || ZONE_COLORS.ga);
      const classEl = document.getElementById("accessZoneClass");
      const nameEl = document.getElementById("accessZoneName");
      if (classEl) classEl.value = zone.zone_class;
      if (nameEl) nameEl.value = zone.name;
      fillZoneClass = zone.zone_class;
      setFillColorInputs(parsed.color, parsed.opacity);
    }
    renderAccessLists();
    drawAccessLayers();
    setStatus("Selected zone.");
  }

  window.selectAccessBarrier = selectBarrier;
  window.selectAccessZone = selectZone;

  window.selectAccessPortal = function (id) {
    portalHeadingPreview = null;
    portalFlowFlipPreview = null;
    if (typeof selectGate === "function") selectGate(id);
    setAccessTool("rfidDevices");
    renderAccessLists();
    updateAccessMapPanel();
    drawAccessLayers();
  };

  window.closeDraftBarrier = function () {
    if (draftBarrierPoints.length < 3) {
      setStatus("Add at least 3 points before closing the perimeter.");
      return;
    }
    draftBarrierClosed = true;
    drawAccessLayers();
    setStatus("Perimeter closed. Click Finish Barrier to save.");
  };

  window.finishDraftBarrier = async function () {
    if (!getDashEvent()) return;
    if (draftBarrierPoints.length < 2) {
      setStatus("Add at least 2 points before finishing a barrier.");
      return;
    }
    const first = draftBarrierPoints[0];
    const last = draftBarrierPoints[draftBarrierPoints.length - 1];
    const nearStart = Math.hypot(first.x - last.x, first.y - last.y) < BARRIER_ENDPOINT_SNAP_RADIUS;
    const closed = draftBarrierClosed || (draftBarrierPoints.length >= 3 && nearStart);
    const name = document.getElementById("accessBarrierName")?.value?.trim() || "Barrier";
    const barrier_type = document.getElementById("accessBarrierType")?.value || "fence";
    const created = await api(`/events/${getDashEvent().id}/access-barriers`, {
      method: "POST",
      body: JSON.stringify({
        name,
        barrier_type,
        points: draftBarrierPoints,
        closed,
        updated_by: "dash_access",
      }),
    });
    draftBarrierPoints = [];
    draftBarrierClosed = false;
    accessBarriers.push(created);
    renderAccessLists();
    drawAccessLayers();
    setStatus(`Saved barrier "${created.name}".`);
  };

  window.cancelDraftBarrier = function () {
    draftBarrierPoints = [];
    draftBarrierClosed = false;
    drawAccessLayers();
    setStatus("Barrier drawing cancelled.");
  };

  window.deleteAccessBarrier = async function (id) {
    if (!confirm("Delete this barrier?")) return;
    await api(`/events/${getDashEvent().id}/access-barriers/${id}`, { method: "DELETE" });
    accessBarriers = accessBarriers.filter((b) => b.id !== id);
    if (selectedBarrierId === id) selectedBarrierId = null;
    renderAccessLists();
    drawAccessLayers();
    setStatus("Deleted barrier.");
  };

  window.deleteAccessZone = async function (id) {
    if (!confirm("Delete this zone?")) return;
    await api(`/events/${getDashEvent().id}/access-zones/${id}`, { method: "DELETE" });
    accessZones = accessZones.filter((z) => z.id !== id);
    if (selectedZoneId === id) selectedZoneId = null;
    await loadAccessLayout();
    if (typeof refreshAll === "function") await refreshAll();
    setStatus("Deleted zone.");
  };

  window.saveFilledZone = async function (polygon) {
    fillZoneClass = document.getElementById("accessZoneClass")?.value || fillZoneClass || "ga";
    const name = document.getElementById("accessZoneName")?.value?.trim() || `${zoneLabel(fillZoneClass)} Zone`;
    const fillColor = getSelectedFillColor();
    const created = await api(`/events/${getDashEvent().id}/access-zones`, {
      method: "POST",
      body: JSON.stringify({
        name,
        zone_class: fillZoneClass,
        polygon,
        fill_color: fillColor,
        updated_by: "dash_access",
      }),
    });
    accessZones.push(created);
    selectedZoneId = created.id;
    renderAccessLists();
    drawAccessLayers();
    setStatus(`Saved ${zoneLabel(created.zone_class)} zone "${created.name}".`);
  };

  window.saveSelectedZoneColor = async function () {
    if (!getDashEvent() || !selectedZoneId) return;
    const fillColor = hexToRgba(
      document.getElementById("editZoneColor")?.value || "#4caf50",
      Number(document.getElementById("editZoneOpacity")?.value || 38)
    );
    const updated = await api(`/events/${getDashEvent().id}/access-zones/${selectedZoneId}`, {
      method: "PUT",
      body: JSON.stringify({
        name: document.getElementById("editZoneName")?.value?.trim(),
        zone_class: document.getElementById("editZoneClass")?.value,
        fill_color: fillColor,
        updated_by: "dash_access",
      }),
    });
    const idx = accessZones.findIndex((z) => z.id === selectedZoneId);
    if (idx >= 0) accessZones[idx] = updated;
    const classEl = document.getElementById("accessZoneClass");
    const nameEl = document.getElementById("accessZoneName");
    if (classEl) classEl.value = updated.zone_class;
    if (nameEl) nameEl.value = updated.name;
    fillZoneClass = updated.zone_class;
    setFillColorInputs(
      parseRgbaColor(updated.fill_color).color,
      parseRgbaColor(updated.fill_color).opacity
    );
    renderAccessLists();
    drawAccessLayers();
    setStatus(`Updated zone "${updated.name}" color.`);
  };

  window.saveZoneClassColorDefault = function () {
    const cls = document.getElementById("accessZoneClass")?.value || fillZoneClass || "ga";
    const color = document.getElementById("accessZoneColor")?.value || "#4caf50";
    const opacity = Number(document.getElementById("accessZoneOpacity")?.value || 38);
    localStorage.setItem(classColorStorageKey(cls), JSON.stringify({ color, opacity }));
    setStatus(`Saved default fill color for ${zoneLabel(cls)}.`);
  };

  window.resetPortalFenceHeadingPreview = function () {
    portalHeadingPreview = null;
    portalFlowFlipPreview = null;
    updateAccessMapPanel();
    refreshGateSnapGraphics();
    setStatus("Reset scanner orientation preview to saved values.");
  };

  function syncFenceHeadingControls(heading) {
    const h = Math.round(Number(heading) || 0);
    const deg = document.getElementById("accessPortalOrientDeg");
    if (deg) deg.textContent = `${h}°`;
    const sidebar = document.getElementById("mapPortalFenceHeading");
    if (sidebar && document.activeElement !== sidebar) sidebar.value = String(h);
    const editSlider = document.getElementById("editGateFenceHeading");
    if (editSlider && document.activeElement !== editSlider) editSlider.value = String(h);
    const editDeg = document.getElementById("editGateFenceHeadingDeg");
    if (editDeg) editDeg.textContent = `${h}°`;
    const newSlider = document.getElementById("newGateFenceHeading");
    if (newSlider && document.activeElement !== newSlider) newSlider.value = String(h);
  }

  window.syncGateFenceHeadingPreview = function (val) {
    portalHeadingPreview = Number(val);
    syncFenceHeadingControls(portalHeadingPreview);
    refreshGateSnapGraphics();
  };

  window.syncNewGateFenceHeadingPreview = function (val) {
    portalHeadingPreview = Number(val);
    syncFenceHeadingControls(portalHeadingPreview);
    refreshGateSnapGraphics();
  };

  window.togglePortalFlowFlip = function () {
    if (selectedKind !== "gate" || !selectedId) return;
    const gate = (getDashGates() || []).find((g) => g.id === selectedId);
    if (!gate) return;
    const current = gateFlowFlipped(gate);
    portalFlowFlipPreview = !current;
    syncPortalFlowFlipButton(gate);
    drawAccessLayers();
    setStatus(`Flow direction preview ${portalFlowFlipPreview ? "flipped" : "restored"}. Click Save to persist.`);
  };

  window.savePortalFenceHeading = async function () {
    if (!getDashEvent() || selectedKind !== "gate" || !selectedId) return;
    const heading = parseInt(document.getElementById("mapPortalFenceHeading")?.value || "0", 10);
    const gate = (getDashGates() || []).find((g) => g.id === selectedId);
    const flowFlipped = gate ? gateFlowFlipped(gate) : false;
    const updated = await api(`/events/${getDashEvent().id}/scanners/${selectedId}`, {
      method: "PUT",
      body: JSON.stringify({
        fence_heading_deg: heading,
        portal_flow_flipped: flowFlipped,
        updated_by: "dash_access",
      }),
    });
    const idx = (getDashGates() || []).findIndex((g) => g.id === selectedId);
    if (idx >= 0 && typeof gates !== "undefined") gates[idx] = updated;
    portalHeadingPreview = null;
    portalFlowFlipPreview = null;
    renderAccessLists();
    updateAccessMapPanel();
    refreshGateSnapGraphics();
    setStatus(`Saved scanner orientation (heading ${heading}°, flow ${flowFlipped ? "flipped" : "normal"}).`);
  };

  window.savePortalAccess = async function () {
    if (!getDashEvent() || selectedKind !== "gate" || !selectedId) return;
    const allowed = [...document.querySelectorAll(".portalClass:checked")].map((el) => el.value);
    const updated = await api(
      `/events/${getDashEvent().id}/scanners/${selectedId}/access`,
      {
        method: "PUT",
        body: JSON.stringify({
          zone_a_id: document.getElementById("portalZoneA").value || null,
          zone_b_id: document.getElementById("portalZoneB").value || null,
          barrier_id: document.getElementById("portalBarrier").value || null,
          direction: document.getElementById("portalDirection").value,
          allowed_classes: allowed,
          updated_by: "dash_access",
        }),
      }
    );
    const idx = (getDashGates() || []).findIndex((g) => g.id === selectedId);
    if (idx >= 0 && typeof gates !== "undefined") gates[idx] = updated;
    renderAccessLists();
    if (typeof drawBase === "function") drawBase();
    setStatus("Saved scanner access rules.");
  };

  window.snapPortalToBarrier = async function () {
    if (selectedKind !== "gate" || !selectedId) return;
    const gate = (getDashGates() || []).find((g) => g.id === selectedId);
    if (!gate) return;
    const hit = findNearestBarrierSegment(gate.map_x, gate.map_y);
    if (!hit || hit.dist > 0.05) {
      setStatus("Draw a perimeter fence first, then place the scanner near it.");
      return;
    }
    const heading = Math.round(fenceCrossingHeadingDeg(hit.a, hit.b));
    const allowed = [...document.querySelectorAll(".portalClass:checked")].map((el) => el.value);
    const updated = await api(`/events/${getDashEvent().id}/scanners/${selectedId}/access`, {
      method: "PUT",
      body: JSON.stringify({
        zone_a_id: document.getElementById("portalZoneA")?.value || gate.zone_a_id || null,
        zone_b_id: document.getElementById("portalZoneB")?.value || gate.zone_b_id || null,
        allowed_classes: allowed.length ? allowed : gate.allowed_classes || [],
        direction: document.getElementById("portalDirection")?.value || gate.direction || "bidirectional",
        barrier_id: hit.barrier_id,
        barrier_segment_index: hit.segIndex,
        barrier_segment_t: hit.t,
        map_x: hit.x,
        map_y: hit.y,
        fence_heading_deg: heading,
        updated_by: "dash_access",
      }),
    });
    const idx = (getDashGates() || []).findIndex((g) => g.id === selectedId);
    if (idx >= 0 && typeof gates !== "undefined") gates[idx] = updated;
    document.getElementById("portalBarrier").value = hit.barrier_id;
    portalHeadingPreview = heading;
    syncFenceHeadingControls(heading);
    renderAccessLists();
    updateAccessMapPanel();
    if (typeof drawBase === "function") drawBase();
    drawAccessLayers();
    setStatus(`Scanner snapped to ${hit.barrier_name} segment ${hit.segIndex + 1} (entry gap created).`);
  };

  async function handleAccessMapClick(p) {
    if (typeof currentTab === "undefined" || currentTab !== "access") return false;

    if (accessTool === "drawBarrier") {
      const snapped = snapBarrierPoint(p, getDashGates());
      addDraftBarrierPoint({ x: snapped.x, y: snapped.y }, snapped);
      return true;
    }

    if (accessTool === "fillZone") {
      try {
        fillZoneClass = document.getElementById("accessZoneClass")?.value || "ga";
        const polygon = floodFillRegion(p.x, p.y, getDashGates());
        await saveFilledZone(polygon);
      } catch (err) {
        setStatus(err.message || String(err));
      }
      return true;
    }

    if (accessTool === "workLocations") {
      try {
        const locationType =
          document.getElementById("placeSimLocType")?.value || placeSimLocationType || "staff_spot";
        placeSimLocationType = locationType;
        const meta = SIM_LOCATION_META[locationType] || SIM_LOCATION_META.staff_spot;
        const created = await api(`/events/${getDashEvent().id}/sim-locations`, {
          method: "POST",
          body: JSON.stringify({
            name: meta.label,
            location_type: locationType,
            map_x: p.x,
            map_y: p.y,
            updated_by: "dash_access",
          }),
        });
        accessSimLocations.push(created);
        selectedSimLocationId = created.id;
        renderWorkLocationSection();
        if (typeof drawBase === "function") drawBase();
        setStatus(`Placed ${meta.label} at ${p.x.toFixed(3)}, ${p.y.toFixed(3)}.`);
      } catch (err) {
        setStatus(err.message || String(err));
      }
      return true;
    }

    return false;
  }

  function installAccessControl() {
    if (typeof api !== "function") {
      setTimeout(installAccessControl, 100);
      return;
    }

    window.getDashEvent = function () {
      return typeof currentEvent !== "undefined" ? currentEvent : null;
    };
    window.getDashGates = function () {
      return typeof gates !== "undefined" ? gates : [];
    };

    const origClear = clearOverlay;
    clearOverlay = function () {
      origClear();
      if (typeof currentTab !== "undefined" && currentTab === "access") drawAccessLayers();
      else clearAccessOverlay();
    };

    const origDraw = drawBase;
    drawBase = function () {
      origDraw();
      applyAccessLayerVisibility();
      if (typeof currentTab !== "undefined" && currentTab === "access") {
        decorateGateMarkers();
        drawSimLocationMarkers();
        drawAccessLayers();
      }
    };

    const origSetTab = setTab;
    setTab = function (tab, autoLoad) {
      const prevTab = typeof currentTab !== "undefined" ? currentTab : null;
      origSetTab(tab, autoLoad);
      updateAccessMapPanel();
      if (tab === "access") {
        const finish = () => drawAccessLayers();
        if (prevTab !== "access" && autoLoad !== false) {
          loadAccessLayout().then(() => {
            setAccessTool("select");
            finish();
          });
        } else if (prevTab !== "access") {
          loadAccessLayout().then(finish);
        } else {
          finish();
        }
      }
    };

    const origRefresh = refreshAll;
    refreshAll = async function () {
      await origRefresh();
      await loadAccessLayout();
    };

    if (typeof selectGate === "function") {
      const origSelectGate = selectGate;
      selectGate = function (id) {
        origSelectGate(id);
        portalHeadingPreview = null;
        portalFlowFlipPreview = null;
        if (typeof currentTab !== "undefined" && currentTab === "access") {
          renderAccessLists();
          updateAccessMapPanel();
          drawAccessLayers();
        }
      };
    }

    const mapWrap = document.getElementById("mapWrap");
    if (mapWrap && !mapWrap.dataset.accessHooked) {
      mapWrap.dataset.accessHooked = "1";
      mapWrap.addEventListener(
        "click",
        (e) => {
          if (typeof currentTab === "undefined" || currentTab !== "access") return;
          if (
            accessTool !== "drawBarrier" &&
            accessTool !== "fillZone" &&
            accessTool !== "workLocations"
          )
            return;
          const p = mapXY(e);
          handleAccessMapClick(p).then((handled) => {
            if (handled) e.stopImmediatePropagation();
          });
        },
        true
      );
    }

    const fillClass = document.getElementById("accessZoneClass");
    if (fillClass) {
      fillClass.onchange = () => {
        fillZoneClass = fillClass.value;
        applyClassDefaultColor();
      };
    }

    const colorEl = document.getElementById("accessZoneColor");
    const opacityEl = document.getElementById("accessZoneOpacity");
    if (colorEl) {
      colorEl.addEventListener("input", syncFillColorPreview);
      colorEl.addEventListener("change", syncFillColorPreview);
    }
    if (opacityEl) {
      opacityEl.addEventListener("input", syncFillColorPreview);
      opacityEl.addEventListener("change", syncFillColorPreview);
    }

    renderZonePresets();
    applyClassDefaultColor();
    loadAccessLayerPrefs();
    syncAccessLayerCheckboxes();

    const layerMap = {
      accessLayerSnap: "snapPoints",
      accessLayerBarriers: "barriers",
      accessLayerZones: "zones",
      accessLayerGates: "gates",
      accessLayerPois: "pois",
      accessLayerAnchors: "anchors",
      accessLayerWorkLocs: "workLocations",
    };
    Object.entries(layerMap).forEach(([id, key]) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("change", () => setAccessLayer(key, el.checked));
    });

    const mapHeadingSlider = document.getElementById("mapPortalFenceHeading");
    if (mapHeadingSlider) {
      mapHeadingSlider.addEventListener("input", () => {
        portalHeadingPreview = Number(mapHeadingSlider.value);
        syncFenceHeadingControls(portalHeadingPreview);
        refreshGateSnapGraphics();
      });
    }

    const scaleSlider = document.getElementById("dashScannerScale");
    const savedScale = Math.round(getScannerMarkerScale() * 100);
    applyScannerMarkerScale(savedScale);
    if (scaleSlider) {
      scaleSlider.value = String(savedScale);
      scaleSlider.addEventListener("input", () => {
        const pct = Number(scaleSlider.value);
        applyScannerMarkerScale(pct);
        localStorage.setItem(SCANNER_SCALE_KEY, String(pct));
      });
    }

    updateAccessMapPanel();
    setAccessTool("select");
  }

  window.setAccessLayer = setAccessLayer;
  window.updateAccessMapPanel = updateAccessMapPanel;

  window.renderPortalEditor = renderPortalEditor;
  window.loadAccessLayout = loadAccessLayout;
  window.setAccessTool = setAccessTool;
  installAccessControl();
})();
