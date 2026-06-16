(function () {
  const SVG_W = 1000;
  const SVG_H = 562.5;
  const GRID_W = 400;
  const GRID_H = 225;

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
        setFillColorInputs(btn.dataset.zoneColor, Number(btn.dataset.zoneOpacity));
      };
    });
    syncFillColorPreview();
  }

  function applyClassDefaultColor() {
    const cls = document.getElementById("accessZoneClass")?.value || fillZoneClass || "ga";
    const defaults = getDefaultClassColor(cls);
    setFillColorInputs(defaults.color, defaults.opacity);
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

    (gates || []).forEach((gate) => {
      const gx = gate.map_x ?? gate.mapX;
      const gy = gate.map_y ?? gate.mapY;
      if (gx == null || gy == null) return;
      const c = gridFromNorm(gx, gy);
      for (let dy = -1; dy <= 1; dy++) {
        for (let dx = -1; dx <= 1; dx++) {
          if (c.gx + dx >= 0 && c.gx + dx < GRID_W && c.gy + dy >= 0 && c.gy + dy < GRID_H) {
            grid[c.gy + dy][c.gx + dx] = 0;
          }
        }
      }
    });
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

  function floodFillRegion(seedX, seedY, gates) {
    const grid = Array.from({ length: GRID_H }, () => Array(GRID_W).fill(0));
    rasterizeWalls(grid, gates);
    const seed = gridFromNorm(seedX, seedY);
    if (grid[seed.gy][seed.gx] === 1) {
      throw new Error("Click inside an open area, not on a barrier.");
    }

    const visited = Array.from({ length: GRID_H }, () => Array(GRID_W).fill(false));
    const q = [[seed.gx, seed.gy]];
    visited[seed.gy][seed.gx] = true;
    let touchesEdge = false;
    const cells = [];

    while (q.length) {
      const [cx, cy] = q.shift();
      cells.push([cx, cy]);
      if (cx === 0 || cy === 0 || cx === GRID_W - 1 || cy === GRID_H - 1) touchesEdge = true;
      [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => {
        const nx = cx + dx;
        const ny = cy + dy;
        if (nx < 0 || ny < 0 || nx >= GRID_W || ny >= GRID_H) return;
        if (visited[ny][nx] || grid[ny][nx] === 1) return;
        visited[ny][nx] = true;
        q.push([nx, ny]);
      });
    }

    if (touchesEdge) {
      throw new Error("That area is open to the map edge. Close it with barriers first.");
    }

    const edgeSet = new Set();
    cells.forEach(([cx, cy]) => {
      [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => {
        const nx = cx + dx;
        const ny = cy + dy;
        if (nx < 0 || ny < 0 || nx >= GRID_W || ny >= GRID_H || grid[ny][nx] === 1) {
          edgeSet.add(`${cx},${cy}`);
        }
      });
    });

    const polygon = [...edgeSet]
      .map((key) => {
        const [gx, gy] = key.split(",").map(Number);
        return normFromGrid(gx, gy);
      })
      .sort((a, b) => a.x - b.x || a.y - b.y);

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

    if (draftBarrierPoints.length >= 1) {
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
      drawBarrier: "Click the map to add barrier points. Finish when the outline is complete.",
      fillZone: "Click inside a closed area, then save the filled zone.",
      linkPortal: "Select a portal/gate, then set zone access rules in the panel.",
    };
    setStatus(hints[tool] || "Access control ready.");
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
          return `<div class="card ${selectedZoneId === z.id ? "selected" : ""}" onclick="selectAccessZone('${z.id}')"><div class="row" style="align-items:center;gap:10px"><span class="zoneColorSwatch" style="background:${swatch}"></span><div><h3>${escapeHtml(z.name)}</h3><p>${zoneLabel(z.zone_class)} • ${(z.polygon || []).length} points</p></div></div><button class="danger" onclick="event.stopPropagation(); deleteAccessZone('${z.id}')">Delete</button></div>`;
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
    };
    document.getElementById("editZoneColor")?.addEventListener("input", syncEditPreview);
    document.getElementById("editZoneOpacity")?.addEventListener("input", syncEditPreview);
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
  }

  function selectBarrier(id) {
    selectedBarrierId = id;
    selectedZoneId = null;
    renderAccessLists();
    drawAccessLayers();
    setStatus("Selected barrier.");
  }

  function selectZone(id) {
    selectedZoneId = id;
    selectedBarrierId = null;
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
    if (typeof selectGate === "function") selectGate(id);
    setAccessTool("linkPortal");
    renderAccessLists();
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
    const name = document.getElementById("accessZoneName")?.value?.trim() || `${zoneLabel(fillZoneClass)} Zone`;
    const created = await api(`/events/${getDashEvent().id}/access-zones`, {
      method: "POST",
      body: JSON.stringify({
        name,
        zone_class: fillZoneClass,
        polygon,
        fill_color: getSelectedFillColor(),
        updated_by: "dash_access",
      }),
    });
    accessZones.push(created);
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

  function handleAccessMapClick(p) {
    if (typeof currentTab === "undefined" || currentTab !== "access") return false;

    if (accessTool === "drawBarrier") {
      draftBarrierPoints.push({ x: p.x, y: p.y });
      drawAccessLayers();
      setStatus(`Barrier point ${draftBarrierPoints.length}. Click Finish Barrier when done.`);
      return true;
    }

    if (accessTool === "fillZone") {
      try {
        fillZoneClass = document.getElementById("accessZoneClass")?.value || "ga";
        const polygon = floodFillRegion(p.x, p.y, getDashGates());
        saveFilledZone(polygon);
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
      if (typeof currentTab !== "undefined" && currentTab === "access") drawAccessLayers();
    };

    const origSetTab = setTab;
    setTab = function (tab, autoLoad) {
      origSetTab(tab, autoLoad);
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
        if (typeof currentTab !== "undefined" && currentTab === "access") {
          setAccessTool("linkPortal");
          renderAccessLists();
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
          if (handleAccessMapClick(p)) {
            e.stopImmediatePropagation();
          }
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
    if (colorEl) colorEl.addEventListener("input", syncFillColorPreview);
    if (opacityEl) opacityEl.addEventListener("input", syncFillColorPreview);

    renderZonePresets();
    applyClassDefaultColor();

    setAccessTool("select");
  }

  window.loadAccessLayout = loadAccessLayout;
  window.setAccessTool = setAccessTool;
  installAccessControl();
})();
