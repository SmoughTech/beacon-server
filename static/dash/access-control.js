(function () {
  const SVG_W = 1000;
  const SVG_H = 562.5;
  const GRID_W = 400;
  const GRID_H = 225;
  const PORTAL_SNAP_DIST = 0.024;
  const PORTAL_SNAP_RADIUS = 0.022;

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
  let selectedBarrierId = null;
  let selectedZoneId = null;
  let fillZoneClass = "ga";
  let portalHeadingPreview = null;
  const ACCESS_LAYER_KEY = "beacon_access_layers";
  let accessLayers = { snapPoints: true, barriers: true, zones: true, gates: true };

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
  }

  function updateAccessMapPanel() {
    const panel = document.getElementById("accessMapPanel");
    const orient = document.getElementById("accessPortalOrient");
    if (!panel) return;
    const onAccess = typeof currentTab !== "undefined" && currentTab === "access";
    panel.classList.toggle("hidden", !onAccess);
    if (!onAccess) return;

    syncAccessLayerCheckboxes();

    const gateSelected =
      typeof selectedKind !== "undefined" && selectedKind === "gate" && typeof selectedId !== "undefined" && selectedId;
    const gate = gateSelected ? (getDashGates() || []).find((g) => g.id === selectedId) : null;

    if (orient) {
      orient.classList.toggle("hidden", !gate);
      if (gate) {
        const title = document.getElementById("accessPortalOrientTitle");
        const deg = document.getElementById("accessPortalOrientDeg");
        const slider = document.getElementById("mapPortalFenceHeading");
        const heading = Math.round(gateFenceHeading(gate));
        if (title) title.textContent = `${gate.name || "Portal"} — fence heading`;
        if (deg) deg.textContent = `${heading}°`;
        if (slider && document.activeElement !== slider) slider.value = String(heading);
      }
    }
  }

  function setAccessLayer(key, enabled) {
    accessLayers[key] = !!enabled;
    saveAccessLayerPrefs();
    syncAccessLayerCheckboxes();
    if (typeof drawBase === "function") drawBase();
    else drawAccessLayers();
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
      selectedKind === "gate" &&
      typeof selectedId !== "undefined" &&
      gate?.id === selectedId
    ) {
      return ((portalHeadingPreview % 360) + 360) % 360;
    }
    return Number(gate?.fence_heading_deg ?? gate?.fenceHeadingDeg ?? 0) % 360;
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
      gateName: gate.name || "Portal",
      center: { x: cx, y: cy },
      heading,
      a: { x: cx - ux * PORTAL_SNAP_DIST, y: cy - uy * PORTAL_SNAP_DIST, side: "a" },
      b: { x: cx + ux * PORTAL_SNAP_DIST, y: cy + uy * PORTAL_SNAP_DIST, side: "b" },
    };
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
      setStatus(`Snapped to ${snapInfo.gateName} side ${snapInfo.side.toUpperCase()} (point ${draftBarrierPoints.length}).`);
    } else {
      setStatus(`Barrier point ${draftBarrierPoints.length}. Click Finish Barrier when done.`);
    }
  }

  function ensureZoneSvg() {
    const wrap = document.getElementById("mapWrap");
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

    accessBarriers.forEach((barrier) => {
      const pts = barrier.points || [];
      for (let i = 1; i < pts.length; i++) {
        const a = gridFromNorm(pts[i - 1].x, pts[i - 1].y);
        const b = gridFromNorm(pts[i].x, pts[i].y);
        drawGridLine(grid, a.gx, a.gy, b.gx, b.gy, mark);
      }
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
      pl.setAttribute(
        "points",
        pts.map((p) => `${p.x * SVG_W},${p.y * SVG_H}`).join(" ")
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
      const draft = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      draft.setAttribute("fill", "none");
      draft.setAttribute(
        "points",
        draftBarrierPoints.map((p) => `${p.x * SVG_W},${p.y * SVG_H}`).join(" ")
      );
      draft.setAttribute("stroke", "#ffd166");
      draft.setAttribute("stroke-width", "4");
      draft.setAttribute("stroke-dasharray", "8 6");
      svg.appendChild(draft);
    }

    if (accessLayers.snapPoints) {
      drawPortalSnapLayers(svg);
    } else if (typeof selectedKind !== "undefined" && selectedKind === "gate" && selectedId) {
      drawPortalSnapLayers(svg, selectedId);
    }
  }

  function drawPortalSnapLayers(svg, onlyGateId) {
    const selectedGateId =
      typeof selectedKind !== "undefined" && selectedKind === "gate" ? selectedId : null;
    (getDashGates() || []).forEach((gate) => {
      if (onlyGateId && gate.id !== onlyGateId) return;
      const pair = getPortalSnapPair(gate);
      if (!pair) return;
      const isSelected = gate.id === selectedGateId;
      const stroke = isSelected ? "#6df7a7" : "#64b5f6";
      const dotR = isSelected ? "10" : "8";

      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(pair.a.x * SVG_W));
      line.setAttribute("y1", String(pair.a.y * SVG_H));
      line.setAttribute("x2", String(pair.b.x * SVG_W));
      line.setAttribute("y2", String(pair.b.y * SVG_H));
      line.setAttribute("stroke", stroke);
      line.setAttribute("stroke-width", "3");
      line.setAttribute("stroke-dasharray", "7 5");
      line.setAttribute("opacity", "0.85");
      line.style.pointerEvents = "none";
      svg.appendChild(line);

      [pair.a, pair.b].forEach((pt) => {
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", String(pt.x * SVG_W));
        circle.setAttribute("cy", String(pt.y * SVG_H));
        circle.setAttribute("r", dotR);
        circle.setAttribute("fill", stroke);
        circle.setAttribute("stroke", "#ffffff");
        circle.setAttribute("stroke-width", "2");
        circle.setAttribute("data-portal-snap", "1");
        circle.setAttribute("title", `${pair.gateName} snap ${pt.side.toUpperCase()}`);
        if (accessTool === "drawBarrier") {
          circle.style.pointerEvents = "auto";
          circle.style.cursor = "crosshair";
          circle.onclick = (ev) => {
            ev.stopPropagation();
            addDraftBarrierPoint(
              { x: pt.x, y: pt.y },
              { snapped: true, gateName: pair.gateName, side: pt.side }
            );
          };
        } else {
          circle.style.pointerEvents = "none";
        }
        svg.appendChild(circle);

        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("x", String(pt.x * SVG_W));
        label.setAttribute("y", String(pt.y * SVG_H - 12));
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("fill", "#b3e5fc");
        label.setAttribute("font-size", "11");
        label.setAttribute("font-weight", "700");
        label.textContent = pt.side.toUpperCase();
        label.style.pointerEvents = "none";
        svg.appendChild(label);
      });
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
    renderAccessLists();
    if (typeof currentTab !== "undefined" && currentTab === "access") drawAccessLayers();
  }

  function setAccessTool(tool) {
    accessTool = tool;
    draftBarrierPoints = [];
    document.querySelectorAll("[data-access-tool]").forEach((btn) => {
      btn.classList.toggle("primary", btn.dataset.accessTool === tool);
    });
    const hints = {
      select: "Select barriers, zones, or portals on the map or in the list.",
      drawBarrier: "Click the map or blue portal snap points (A/B) to trace your fence. Portals leave an opening for zone fill.",
      fillZone: "Click inside a barrier-enclosed area. Portals complete the boundary (A↔B) so fill won't leak to the map edge.",
      linkPortal: "Select a portal/gate, then set zone access rules in the panel.",
    };
    setStatus(hints[tool] || "Access control ready.");
    updateAccessMapPanel();
    if (typeof drawBase === "function") drawBase();
  }

  function renderAccessLists() {
    const barrierList = document.getElementById("accessBarrierList");
    const zoneList = document.getElementById("accessZoneList");
    const portalList = document.getElementById("accessPortalList");
    if (!barrierList || !zoneList || !portalList) return;

    barrierList.innerHTML =
      accessBarriers
        .map(
          (b) =>
            `<div class="card ${selectedBarrierId === b.id ? "selected" : ""}" onclick="selectAccessBarrier('${b.id}')"><h3>${escapeHtml(b.name)}</h3><p>${escapeHtml(b.barrier_type)} • ${(b.points || []).length} points</p><button class="danger" onclick="event.stopPropagation(); deleteAccessBarrier('${b.id}')">Delete</button></div>`
        )
        .join("") || '<p class="muted">No barriers yet.</p>';

    zoneList.innerHTML =
      accessZones
        .map((z) => {
          const swatch = z.fill_color || ZONE_COLORS[z.zone_class] || ZONE_COLORS.ga;
          return `<div class="card ${selectedZoneId === z.id ? "selected" : ""}" onclick="selectAccessZone('${z.id}')"><div class="row" style="align-items:center;gap:10px"><span class="zoneColorSwatch" style="background:${swatch}"></span><div><h3>${escapeHtml(z.name)}</h3><p>${zoneLabel(z.zone_class)} • ${(z.polygon || []).length} vertices</p></div></div><button class="danger" onclick="event.stopPropagation(); deleteAccessZone('${z.id}')">Delete</button></div>`;
        })
        .join("") || '<p class="muted">No zones yet.</p>';

    portalList.innerHTML =
      (getDashGates() || [])
        .map((g) => {
          const a = accessZones.find((z) => z.id === g.zone_a_id);
          const b = accessZones.find((z) => z.id === g.zone_b_id);
          const allowed = (g.allowed_classes || []).map(zoneLabel).join(", ") || "none";
          return `<div class="card ${selectedKind === "gate" && selectedId === g.id ? "selected" : ""}" onclick="selectAccessPortal('${g.id}')"><h3>${escapeHtml(g.name)}</h3><p>${escapeHtml(g.device_type || "portal")} • ${allowed}</p><p class="muted">${a ? a.name : "Outside?"} → ${b ? b.name : "Unset"}</p></div>`;
        })
        .join("") || '<p class="muted">Add WRSTOPS gates first (+ Gate on POIs tab).</p>';

    renderZoneEditor();
    renderPortalEditor();
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
    const editor = document.getElementById("accessPortalEditor");
    if (!editor) return;
    if (selectedKind !== "gate" || !selectedId) {
      editor.innerHTML = '<p class="muted">Select a portal to configure zone access.</p>';
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

    editor.innerHTML = `
      <div class="card selected">
        <h3>${escapeHtml(gate.name)} portal rules</h3>
        <p class="small">Rotate snap points using the <b>fence heading slider under the map</b> for live preview.</p>
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
          <button class="primary" onclick="savePortalAccess()">Save Portal Rules</button>
          <button onclick="snapPortalToBarrier()">Snap To Nearest Barrier</button>
        </div>
      </div>`;

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
    renderAccessLists();
    drawAccessLayers();
    setStatus("Selected barrier.");
  }

  function selectZone(id) {
    selectedZoneId = id;
    selectedBarrierId = null;
    portalHeadingPreview = null;
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
    if (typeof selectGate === "function") selectGate(id);
    setAccessTool("linkPortal");
    renderAccessLists();
    updateAccessMapPanel();
    drawAccessLayers();
  };

  window.finishDraftBarrier = async function () {
    if (!getDashEvent()) return;
    if (draftBarrierPoints.length < 2) {
      setStatus("Add at least 2 points before finishing a barrier.");
      return;
    }
    const name = document.getElementById("accessBarrierName")?.value?.trim() || "Barrier";
    const barrier_type = document.getElementById("accessBarrierType")?.value || "fence";
    const created = await api(`/events/${getDashEvent().id}/access-barriers`, {
      method: "POST",
      body: JSON.stringify({
        name,
        barrier_type,
        points: draftBarrierPoints,
        updated_by: "dash_access",
      }),
    });
    draftBarrierPoints = [];
    accessBarriers.push(created);
    renderAccessLists();
    drawAccessLayers();
    setStatus(`Saved barrier "${created.name}".`);
  };

  window.cancelDraftBarrier = function () {
    draftBarrierPoints = [];
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
    updateAccessMapPanel();
    drawAccessLayers();
    setStatus("Reset portal heading preview to saved value.");
  };

  window.savePortalFenceHeading = async function () {
    if (!getDashEvent() || selectedKind !== "gate" || !selectedId) return;
    const heading = parseInt(document.getElementById("mapPortalFenceHeading")?.value || "0", 10);
    const updated = await api(`/events/${getDashEvent().id}/wrstops-gates/${selectedId}`, {
      method: "PUT",
      body: JSON.stringify({
        fence_heading_deg: heading,
        updated_by: "dash_access",
      }),
    });
    const idx = (getDashGates() || []).findIndex((g) => g.id === selectedId);
    if (idx >= 0 && typeof gates !== "undefined") gates[idx] = updated;
    portalHeadingPreview = null;
    renderAccessLists();
    updateAccessMapPanel();
    drawAccessLayers();
    setStatus(`Saved portal fence heading (${heading}°). Snap points updated.`);
  };

  window.savePortalAccess = async function () {
    if (!getDashEvent() || selectedKind !== "gate" || !selectedId) return;
    const allowed = [...document.querySelectorAll(".portalClass:checked")].map((el) => el.value);
    const updated = await api(
      `/events/${getDashEvent().id}/wrstops-gates/${selectedId}/portal-access`,
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
    setStatus("Saved portal access rules.");
  };

  window.snapPortalToBarrier = function () {
    if (selectedKind !== "gate" || !selectedId) return;
    const gate = (getDashGates() || []).find((g) => g.id === selectedId);
    if (!gate) return;
    let best = null;
    let bestDist = Infinity;
    accessBarriers.forEach((barrier) => {
      (barrier.points || []).forEach((p, i) => {
        if (i === 0) return;
        const a = barrier.points[i - 1];
        const b = p;
        const t = 0.5;
        const mx = a.x + (b.x - a.x) * t;
        const my = a.y + (b.y - a.y) * t;
        const d = Math.hypot(mx - gate.map_x, my - gate.map_y);
        if (d < bestDist) {
          bestDist = d;
          best = { barrier_id: barrier.id, mx, my };
        }
      });
    });
    if (!best) {
      setStatus("Draw barriers first, then snap the portal.");
      return;
    }
    document.getElementById("portalBarrier").value = best.barrier_id;
    setStatus(`Snapped portal to nearest barrier (${bestDist.toFixed(4)} map units away).`);
  };

  async function handleAccessMapClick(p) {
    if (typeof currentTab === "undefined" || currentTab !== "access") return false;

    if (accessTool === "drawBarrier") {
      const snapped = snapAccessPoint(p, getDashGates());
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
      if (typeof currentTab !== "undefined" && currentTab === "access") drawAccessLayers();
    };

    const origSetTab = setTab;
    setTab = function (tab, autoLoad) {
      origSetTab(tab, autoLoad);
      updateAccessMapPanel();
      if (tab === "access") {
        loadAccessLayout().then(() => {
          setAccessTool("select");
          drawAccessLayers();
        });
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
        if (typeof currentTab !== "undefined" && currentTab === "access") {
          setAccessTool("linkPortal");
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
          if (accessTool !== "drawBarrier" && accessTool !== "fillZone") return;
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
        const deg = document.getElementById("accessPortalOrientDeg");
        if (deg) deg.textContent = `${Math.round(portalHeadingPreview)}°`;
        drawAccessLayers();
      });
    }

    updateAccessMapPanel();
    setAccessTool("select");
  }

  window.setAccessLayer = setAccessLayer;
  window.updateAccessMapPanel = updateAccessMapPanel;

  window.loadAccessLayout = loadAccessLayout;
  window.setAccessTool = setAccessTool;
  installAccessControl();
})();
