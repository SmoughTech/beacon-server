(function () {
  const SVG_W = 1000;
  const SVG_H = 562.5;
  const TILE_SIZE_FT = 2;
  const TILE_COLS = 400;
  const TILE_ROWS = 225;
  const VERTEX_COLS = TILE_COLS + 1;
  const VERTEX_ROWS = TILE_ROWS + 1;
  const GRID_W = TILE_COLS;
  const GRID_H = TILE_ROWS;
  const PORTAL_SNAP_DIST = 0.011;
  const PORTAL_SNAP_RADIUS = 0.014;
  const BARRIER_ENDPOINT_SNAP_RADIUS = 0.02;
  const BARRIER_SEGMENT_SNAP_RADIUS = 0.018;
  const SCANNER_FENCE_SNAP_RADIUS = 0.045;
  const PLACEMENT_SNAP_RADIUS = 0.018;
  const PORTAL_GAP_HALF_WIDTH = 0.014;

  const ZONE_COLORS = {
    ga: "rgba(76,175,80,0.38)",
    vip: "rgba(255,193,7,0.40)",
    staff: "rgba(66,165,245,0.40)",
    backstage: "rgba(171,71,188,0.40)",
    vendor: "rgba(255,152,0,0.38)",
  };

  function showsAccessMapLayers() {
    return typeof currentTab !== "undefined" && (currentTab === "access" || currentTab === "sim");
  }

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
  let accessQueues = [];
  let accessPaths = [];
  let accessSpawnPoints = [];
  let accessTool = "select";
  let draftBarrierPoints = [];
  let draftBarrierTiles = new Set();
  let draftBarrierClosed = false;
  let barrierDragState = null;
  let barrierDragPreviewTiles = new Set();
  let draftPathTiles = new Set();
  let pathDragState = null;
  let pathDragPreviewTiles = new Set();
  let pathDraftVertices = [];
  let queueDragState = null;
  const QUEUE_ENTRANCE_SNAP_RADIUS = 0.028;
  const QUEUE_PORTAL_SNAP_RADIUS = 0.024;
  let pathBrushWidth = 1;
  let draftQueuePoints = [];
  let selectedBarrierId = null;
  let selectedZoneId = null;
  let selectedQueueId = null;
  let selectedPathId = null;
  let selectedSpawnId = null;
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
    tileGrid: true,
    paths: true,
    spawnPoints: true,
    queues: true,
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
    if (typeof decorateGateDragHandles === "function") decorateGateDragHandles();
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
      accessLayerTileGrid: "tileGrid",
      accessLayerPaths: "paths",
      accessLayerSpawnPoints: "spawnPoints",
      accessLayerQueues: "queues",
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

  function enterSelectCategory(category, id) {
    accessTool = "select";
    syncAccessToolbarButtons();
    selectedBarrierId = category === "barriers" ? id : null;
    selectedPathId = category === "paths" ? id : null;
    selectedQueueId = category === "queues" ? id : null;
    selectedZoneId = category === "zones" ? id : null;
    syncAccessToolPanels();
  }

  function syncAccessToolbarButtons() {
    document.querySelectorAll("[data-access-tool]").forEach((btn) => {
      btn.classList.toggle("primary", btn.dataset.accessTool === accessTool);
    });
  }

  function isAccessCategoryVisible(category) {
    if (accessTool === "rfidDevices" || accessTool === "workLocations" || accessTool === "linkPortal" || accessTool === "placeSpawn") {
      return false;
    }
    const toolByCategory = {
      barriers: "drawBarrier",
      paths: "drawPath",
      spawns: "placeSpawn",
      queues: "drawQueue",
      zones: "fillZone",
    };
    const selectedByCategory = {
      barriers: selectedBarrierId,
      paths: selectedPathId,
      spawns: selectedSpawnId,
      queues: selectedQueueId,
      zones: selectedZoneId,
    };
    if (accessTool === toolByCategory[category]) return true;
    if (accessTool === "select" && selectedByCategory[category]) return true;
    return false;
  }

  function syncAccessToolPanels() {
    const rfidSection = document.getElementById("accessRfidSection");
    if (rfidSection) rfidSection.classList.toggle("hidden", accessTool !== "rfidDevices");

    const sectionIds = {
      barriers: "accessSectionBarriers",
      paths: "accessSectionPaths",
      spawns: "accessSectionSpawns",
      queues: "accessSectionQueues",
      zones: "accessSectionZones",
    };
    Object.entries(sectionIds).forEach(([category, id]) => {
      const el = document.getElementById(id);
      if (el) el.classList.toggle("hidden", !isAccessCategoryVisible(category));
    });

    const anyCategoryVisible = Object.keys(sectionIds).some((category) => isAccessCategoryVisible(category));
    const hint = document.getElementById("accessSectionHint");
    if (hint) {
      hint.classList.toggle(
        "hidden",
        anyCategoryVisible || accessTool === "rfidDevices" || accessTool === "workLocations" || accessTool === "linkPortal" || accessTool === "placeSpawn"
      );
    }

    const footer = document.getElementById("accessLayoutFooter");
    if (footer) footer.classList.toggle("hidden", !anyCategoryVisible);

    const portalEditor = document.getElementById("accessPortalEditor");
    if (portalEditor) portalEditor.classList.toggle("hidden", accessTool !== "linkPortal");

    const barrierEditor = document.getElementById("accessBarrierSection");
    if (barrierEditor) barrierEditor.classList.toggle("hidden", accessTool !== "drawBarrier");
    const queueSection = document.getElementById("accessQueueSection");
    if (queueSection) queueSection.classList.toggle("hidden", accessTool !== "drawQueue");
    const pathSection = document.getElementById("accessPathSection");
    if (pathSection) pathSection.classList.toggle("hidden", accessTool !== "drawPath");
    const spawnSection = document.getElementById("accessSpawnSection");
    if (spawnSection) spawnSection.classList.toggle("hidden", accessTool !== "placeSpawn");
    const zoneEditor = document.getElementById("accessZoneSection");
    if (zoneEditor) zoneEditor.classList.toggle("hidden", accessTool !== "fillZone");

    updateWorkLocationSectionVisibility();

    const mapWrap = document.getElementById("mapWrap");
    if (mapWrap) {
      mapWrap.classList.toggle(
        "accessPaintCursor",
        accessTool === "drawPath" || accessTool === "drawBarrier" || accessTool === "drawQueue" || accessTool === "placeSpawn"
      );
    }
  }

  function getPathBrushWidth() {
    const raw = Number(document.getElementById("accessPathWidth")?.value || pathBrushWidth || 1);
    if (raw === 2 || raw === 4) return raw;
    return 1;
  }

  function pathWidthLabel(width) {
    if (width === 2) return "2 tiles (4ft)";
    if (width === 4) return "4 tiles (8ft)";
    return "1 tile (2ft)";
  }

  function perpendicularDir(tx0, ty0, tx1, ty1) {
    const dx = tx1 - tx0;
    const dy = ty1 - ty0;
    if (dx === 0 && dy === 0) return { px: 0, py: 1 };
    if (Math.abs(dx) >= Math.abs(dy)) return { px: 0, py: 1 };
    if (Math.abs(dy) > Math.abs(dx)) return { px: 1, py: 0 };
    const sx = dx > 0 ? 1 : dx < 0 ? -1 : 0;
    const sy = dy > 0 ? 1 : dy < 0 ? -1 : 0;
    return { px: -sy, py: sx };
  }

  function brushOffsets(width) {
    const start = -Math.floor((width - 1) / 2);
    return Array.from({ length: width }, (_, i) => start + i);
  }

  function addBrushTilesAlongLine(tx0, ty0, tx1, ty1, width, targetSet) {
    const perp = perpendicularDir(tx0, ty0, tx1, ty1);
    tileLineBetween(tx0, ty0, tx1, ty1).forEach(([tx, ty]) => {
      brushOffsets(width).forEach((off) => {
        const nx = tx + perp.px * off;
        const ny = ty + perp.py * off;
        if (nx >= 0 && nx < TILE_COLS && ny >= 0 && ny < TILE_ROWS) {
          targetSet.add(tileKey(nx, ny));
        }
      });
    });
  }

  function tileKey(tx, ty) {
    return `${tx},${ty}`;
  }

  function parseTileKey(key) {
    const [tx, ty] = key.split(",").map(Number);
    return { tx, ty };
  }

  function tileLineBetween(tx0, ty0, tx1, ty1) {
    return vertexLineBetween(tx0, ty0, tx1, ty1);
  }

  function addTilesAlongLine(tx0, ty0, tx1, ty1, targetSet) {
    tileLineBetween(tx0, ty0, tx1, ty1).forEach(([tx, ty]) => {
      if (tx >= 0 && tx < TILE_COLS && ty >= 0 && ty < TILE_ROWS) {
        targetSet.add(tileKey(tx, ty));
      }
    });
  }

  function allDraftBarrierTileKeys() {
    const out = new Set(draftBarrierTiles);
    barrierDragPreviewTiles.forEach((k) => out.add(k));
    return out;
  }

  function allDraftPathTileKeys() {
    const out = new Set(draftPathTiles);
    pathDragPreviewTiles.forEach((k) => out.add(k));
    return out;
  }

  function drawBarrierTileRects(svg, tileKeys, stroke, fill, selected) {
    const stepX = SVG_W / TILE_COLS;
    const stepY = SVG_H / TILE_ROWS;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.style.pointerEvents = "none";
    tileKeys.forEach((key) => {
      const { tx, ty } = parseTileKey(key);
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", String(tx * stepX));
      rect.setAttribute("y", String(ty * stepY));
      rect.setAttribute("width", String(stepX));
      rect.setAttribute("height", String(stepY));
      rect.style.fill = fill;
      rect.style.stroke = stroke;
      rect.style.strokeWidth = selected ? "1.5" : "1";
      rect.style.opacity = "0.85";
      g.appendChild(rect);
    });
    svg.appendChild(g);
  }

  function iterTileBarrierSegments(barrier) {
    const tileSet = new Set();
    (barrier.tiles || []).forEach(([tx, ty]) => tileSet.add(tileKey(tx, ty)));
    const edges = [];
    tileSet.forEach((key) => {
      const { tx, ty } = parseTileKey(key);
      if (!tileSet.has(tileKey(tx, ty - 1))) {
        edges.push({
          a: normFromVertex(tx, ty),
          b: normFromVertex(tx + 1, ty),
        });
      }
      if (!tileSet.has(tileKey(tx + 1, ty))) {
        edges.push({
          a: normFromVertex(tx + 1, ty),
          b: normFromVertex(tx + 1, ty + 1),
        });
      }
      if (!tileSet.has(tileKey(tx, ty + 1))) {
        edges.push({
          a: normFromVertex(tx + 1, ty + 1),
          b: normFromVertex(tx, ty + 1),
        });
      }
      if (!tileSet.has(tileKey(tx - 1, ty))) {
        edges.push({
          a: normFromVertex(tx, ty + 1),
          b: normFromVertex(tx, ty),
        });
      }
    });
    return edges.map((edge, segIndex) => ({ segIndex, ...edge }));
  }

  function beginBarrierDrag(p) {
    const { gx: tx, gy: ty } = gridFromNorm(p.x, p.y);
    barrierDragState = { startTx: tx, startTy: ty };
    barrierDragPreviewTiles = new Set();
    addTilesAlongLine(tx, ty, tx, ty, barrierDragPreviewTiles);
    drawAccessLayers();
  }

  function updateBarrierDrag(p) {
    if (!barrierDragState) return;
    const { gx: tx, gy: ty } = gridFromNorm(p.x, p.y);
    barrierDragPreviewTiles = new Set();
    addTilesAlongLine(barrierDragState.startTx, barrierDragState.startTy, tx, ty, barrierDragPreviewTiles);
    drawAccessLayers();
  }

  function endBarrierDrag() {
    if (!barrierDragState) return;
    barrierDragPreviewTiles.forEach((k) => draftBarrierTiles.add(k));
    const count = draftBarrierTiles.size;
    barrierDragState = null;
    barrierDragPreviewTiles = new Set();
    drawAccessLayers();
    setStatus(`${count} tile${count === 1 ? "" : "s"} painted. Drag again or click Finish Barrier.`);
  }

  function beginPathDrag(p) {
    const anchor = pathDragAnchor(p);
    const width = getPathBrushWidth();
    pathBrushWidth = width;
    pathDragState = {
      startTx: anchor.tx,
      startTy: anchor.ty,
      width,
      curX: p.x,
      curY: p.y,
    };
    pathDragPreviewTiles = new Set();
    addBrushTilesAlongLine(anchor.tx, anchor.ty, anchor.tx, anchor.ty, width, pathDragPreviewTiles);
    bindPathDragListeners();
    drawAccessLayers();
    if (anchor.snapped) {
      setStatus(`Path snapped to ${anchor.label}. Drag toward destination; release to stamp tiles.`);
    }
  }

  function updatePathDrag(p) {
    if (!pathDragState) return;
    pathDragState.curX = p.x;
    pathDragState.curY = p.y;
    const anchor = pathDragAnchor(p);
    pathDragPreviewTiles = new Set();
    addBrushTilesAlongLine(
      pathDragState.startTx,
      pathDragState.startTy,
      anchor.tx,
      anchor.ty,
      pathDragState.width,
      pathDragPreviewTiles
    );
    drawAccessLayers();
  }

  function endPathDrag() {
    if (!pathDragState) return;
    pathDragPreviewTiles.forEach((k) => draftPathTiles.add(k));
    const endAnchor = pathDragAnchor({ x: pathDragState.curX, y: pathDragState.curY });
    const start = normFromGrid(pathDragState.startTx, pathDragState.startTy);
    const end = normFromGrid(endAnchor.tx, endAnchor.ty);
    pathDraftVertices.push(start);
    pathDraftVertices.push(end);
    const count = draftPathTiles.size;
    pathDragState = null;
    pathDragPreviewTiles = new Set();
    unbindPathDragListeners();
    drawAccessLayers();
    const snapNote = endAnchor.snapped ? " (snapped to queue entrance)" : "";
    setStatus(`${count} path tile${count === 1 ? "" : "s"} painted${snapNote}. Drag again or Finish Path.`);
  }

  function appendQueueSegment(x0, y0, x1, y1) {
    const a = vertexFromNorm(x0, y0);
    const b = vertexFromNorm(x1, y1);
    if (!draftQueuePoints.length) {
      draftQueuePoints.push(normFromVertex(a.vx, a.vy));
    }
    vertexLineBetween(a.vx, a.vy, b.vx, b.vy)
      .slice(1)
      .forEach(([vx, vy]) => {
        draftQueuePoints.push(normFromVertex(vx, vy));
      });
  }

  function beginQueueDrag(p) {
    const gates = getDashGates() || [];
    if (!gates.length) {
      setStatus("Place a scanner first, then drag the queue line toward it.");
      return;
    }
    let start;
    if (draftQueuePoints.length === 0) {
      start = snapQueuePoint(p);
    } else {
      start = draftQueuePoints[draftQueuePoints.length - 1];
    }
    queueDragState = { startX: start.x, startY: start.y, curX: p.x, curY: p.y };
    bindPathDragListeners();
    drawAccessLayers();
  }

  function updateQueueDrag(p) {
    if (!queueDragState) return;
    queueDragState.curX = p.x;
    queueDragState.curY = p.y;
    drawAccessLayers();
  }

  function endQueueDrag() {
    if (!queueDragState) return;
    const end = snapQueueEndpoint({ x: queueDragState.curX, y: queueDragState.curY });
    appendQueueSegment(queueDragState.startX, queueDragState.startY, end.x, end.y);
    const count = draftQueuePoints.length;
    queueDragState = null;
    unbindPathDragListeners();
    drawAccessLayers();
    if (end.snapped) {
      setStatus(`Queue line: ${count} points — snapped to ${end.gateName || "scanner"}. Drag again or Finish Queue.`);
    } else {
      setStatus(`Queue line: ${count} points. Drag toward scanner; release near portal to snap.`);
    }
  }

  function onDocumentPathDragMove(e) {
    const p = mapXY(e);
    if (pathDragState) updatePathDrag(p);
    else if (queueDragState) updateQueueDrag(p);
  }

  function onDocumentPathDragEnd() {
    if (pathDragState) endPathDrag();
    else if (queueDragState) endQueueDrag();
  }

  function bindPathDragListeners() {
    if (document.body.dataset.pathDragBound) return;
    document.body.dataset.pathDragBound = "1";
    document.addEventListener("mousemove", onDocumentPathDragMove, true);
    document.addEventListener("mouseup", onDocumentPathDragEnd, true);
  }

  function unbindPathDragListeners() {
    if (!document.body.dataset.pathDragBound) return;
    if (pathDragState || queueDragState) return;
    delete document.body.dataset.pathDragBound;
    document.removeEventListener("mousemove", onDocumentPathDragMove, true);
    document.removeEventListener("mouseup", onDocumentPathDragEnd, true);
  }

  function tilesToPayloadList(tileSet) {
    return Array.from(tileSet).map((key) => {
      const { tx, ty } = parseTileKey(key);
      return [tx, ty];
    });
  }

  function bresenhamGridTiles(x0, y0, x1, y1) {
    const tiles = [];
    let cx = x0;
    let cy = y0;
    const dx = Math.abs(x1 - x0);
    const dy = Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1;
    const sy = y0 < y1 ? 1 : -1;
    let err = dx - dy;
    while (true) {
      tiles.push([cx, cy]);
      if (cx === x1 && cy === y1) break;
      const e2 = 2 * err;
      if (e2 > -dy) {
        err -= dy;
        cx += sx;
      }
      if (e2 < dx) {
        err += dx;
        cy += sy;
      }
    }
    return tiles;
  }

  function orderedPathTilesFromPaint(tileSet, vertices) {
    const ordered = [];
    const seen = new Set();
    if (vertices.length >= 2) {
      for (let i = 0; i < vertices.length - 1; i++) {
        const a = gridFromNorm(vertices[i].x, vertices[i].y);
        const b = gridFromNorm(vertices[i + 1].x, vertices[i + 1].y);
        for (const [tx, ty] of bresenhamGridTiles(a.gx, a.gy, b.gx, b.gy)) {
          const k = tileKey(tx, ty);
          if (tileSet.has(k) && !seen.has(k)) {
            seen.add(k);
            ordered.push([tx, ty]);
          }
        }
      }
    }
    for (const k of tileSet) {
      if (!seen.has(k)) {
        const { tx, ty } = parseTileKey(k);
        ordered.push([tx, ty]);
      }
    }
    return ordered;
  }

  function snapToQueueEntrance(p) {
    const candidates = [];
    accessQueues.forEach((queue) => {
      const tail = queue.points?.[0];
      if (tail) candidates.push({ point: tail, label: "queue tail" });
    });
    if (draftQueuePoints.length >= 1) {
      candidates.push({ point: draftQueuePoints[0], label: "draft queue tail" });
    }
    let best = null;
    let bestDist = QUEUE_ENTRANCE_SNAP_RADIUS;
    for (const item of candidates) {
      const d = Math.hypot(p.x - item.point.x, p.y - item.point.y);
      if (d < bestDist) {
        bestDist = d;
        best = item;
      }
    }
    return best;
  }

  function pathDragAnchor(p) {
    const entrance = snapToQueueEntrance(p);
    if (entrance) {
      const g = gridFromNorm(entrance.point.x, entrance.point.y);
      return { tx: g.gx, ty: g.gy, snapped: true, label: entrance.label };
    }
    const g = gridFromNorm(p.x, p.y);
    return { tx: g.gx, ty: g.gy, snapped: false };
  }

  function snapQueueEndpoint(p) {
    const gates = getDashGates() || [];
    const gateSelect = document.getElementById("accessQueueGate");
    const selectedId = gateSelect?.value;
    const ordered = selectedId
      ? [...gates.filter((g) => g.id === selectedId), ...gates.filter((g) => g.id !== selectedId)]
      : gates;

    for (const gate of ordered) {
      const mx = gate.map_x ?? gate.mapX;
      const my = gate.map_y ?? gate.mapY;
      if (mx == null || my == null) continue;
      const d = Math.hypot(p.x - mx, p.y - my);
      if (d < QUEUE_PORTAL_SNAP_RADIUS) {
        if (gateSelect && !selectedId) gateSelect.value = gate.id;
        return { ...snapQueuePoint({ x: mx, y: my }), snapped: true, gateName: gate.name || gate.id };
      }
    }

    const portalSnap = snapAccessPoint(p, ordered);
    if (portalSnap.snapped) {
      if (portalSnap.gateId && gateSelect) gateSelect.value = portalSnap.gateId;
      return {
        ...snapQueuePoint(portalSnap),
        snapped: true,
        gateName: portalSnap.gateName,
      };
    }
    return { ...snapQueuePoint(p), snapped: false };
  }

  function snapToPathTile(normX, normY) {
    const { gx, gy } = gridFromNorm(normX, normY);
    let best = null;
    let bestDist = Infinity;
    for (const path of accessPaths) {
      const tiles = path.tiles || [];
      for (let i = 0; i < tiles.length; i++) {
        const [tx, ty] = tiles[i];
        const d = Math.abs(tx - gx) + Math.abs(ty - gy);
        if (d < bestDist) {
          bestDist = d;
          best = { path_id: path.id, tile_index: i, tx, ty };
        }
      }
    }
    if (!best || bestDist > 10) return null;
    return {
      ...best,
      map_x: (best.tx + 0.5) / TILE_COLS,
      map_y: (best.ty + 0.5) / TILE_ROWS,
    };
  }

  function drawPathFlowArrows(svg, path) {
    const tiles = path.tiles || [];
    if (tiles.length < 2) return;
    const reverse = (path.flow_direction || path.flowDirection || "forward") === "reverse";
    const step = Math.max(3, Math.floor(tiles.length / 7));
    for (let i = step; i < tiles.length; i += step) {
      const toIdx = reverse ? tiles.length - 1 - i : i;
      const fromIdx = reverse ? toIdx + 1 : toIdx - 1;
      if (fromIdx < 0 || fromIdx >= tiles.length) continue;
      const [x0, y0] = tiles[fromIdx];
      const [x1, y1] = tiles[toIdx];
      const ax = ((x0 + 0.5) / TILE_COLS) * SVG_W;
      const ay = ((y0 + 0.5) / TILE_ROWS) * SVG_H;
      const bx = ((x1 + 0.5) / TILE_COLS) * SVG_W;
      const by = ((y1 + 0.5) / TILE_ROWS) * SVG_H;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(ax));
      line.setAttribute("y1", String(ay));
      line.setAttribute("x2", String(bx));
      line.setAttribute("y2", String(by));
      line.setAttribute("stroke", selectedPathId === path.id ? "#ffe082" : "#ffca28");
      line.setAttribute("stroke-width", "3");
      line.setAttribute("stroke-linecap", "round");
      line.setAttribute("opacity", "0.92");
      line.style.pointerEvents = "none";
      svg.appendChild(line);
      const rad = Math.atan2(by - ay, bx - ax);
      const wing = 0.45;
      const headLen = 8;
      const head = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
      const hx = bx;
      const hy = by;
      head.setAttribute(
        "points",
        [
          `${hx},${hy}`,
          `${hx + Math.cos(rad + Math.PI + wing) * headLen},${hy + Math.sin(rad + Math.PI + wing) * headLen}`,
          `${hx + Math.cos(rad + Math.PI - wing) * headLen},${hy + Math.sin(rad + Math.PI - wing) * headLen}`,
        ].join(" ")
      );
      head.setAttribute("fill", selectedPathId === path.id ? "#ffe082" : "#ffca28");
      head.style.pointerEvents = "none";
      svg.appendChild(head);
    }
  }

  function snapQueuePoint(p) {
    const { vx, vy } = vertexFromNorm(p.x, p.y);
    return normFromVertex(vx, vy);
  }

  function vertexFromNorm(x, y) {
    return {
      vx: Math.max(0, Math.min(VERTEX_COLS - 1, Math.round(x * TILE_COLS))),
      vy: Math.max(0, Math.min(VERTEX_ROWS - 1, Math.round(y * TILE_ROWS))),
    };
  }

  function normFromVertex(vx, vy) {
    return { x: vx / TILE_COLS, y: vy / TILE_ROWS };
  }

  function vertexLineBetween(ax, ay, bx, by) {
    const points = [];
    let x0 = ax;
    let y0 = ay;
    const x1 = bx;
    const y1 = by;
    let dx = Math.abs(x1 - x0);
    let dy = Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1;
    const sy = y0 < y1 ? 1 : -1;
    let err = dx - dy;
    while (true) {
      points.push([x0, y0]);
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
    return points;
  }

  function appendQueueVertexPoint(p) {
    const snapped = snapQueuePoint(p);
    if (!draftQueuePoints.length) {
      draftQueuePoints.push(snapped);
      return;
    }
    const prev = draftQueuePoints[draftQueuePoints.length - 1];
    const a = vertexFromNorm(prev.x, prev.y);
    const b = vertexFromNorm(snapped.x, snapped.y);
    const steps = vertexLineBetween(a.vx, a.vy, b.vx, b.vy);
    steps.slice(1).forEach(([vx, vy]) => {
      draftQueuePoints.push(normFromVertex(vx, vy));
    });
  }

  function snapPlacementAnchor(x, y, radiusNorm = PLACEMENT_SNAP_RADIUS) {
    const vtx = vertexFromNorm(x, y);
    const vx = vtx.vx;
    const vy = vtx.vy;
    let best = { x: vx / TILE_COLS, y: vy / TILE_ROWS, snapKind: "vertex", vx, vy };
    let bestDist = Math.hypot(x - best.x, y - best.y);

    const consider = (px, py, meta) => {
      const d = Math.hypot(x - px, y - py);
      if (d <= radiusNorm && d < bestDist) {
        bestDist = d;
        best = { x: px, y: py, ...meta };
      }
    };

    const tx = Math.max(0, Math.min(TILE_COLS - 1, Math.floor(x * TILE_COLS)));
    const ty = Math.max(0, Math.min(TILE_ROWS - 1, Math.floor(y * TILE_ROWS)));
    consider((tx + 0.5) / TILE_COLS, ty / TILE_ROWS, { snapKind: "h_edge", tx, vy: ty });
    consider((tx + 0.5) / TILE_COLS, (ty + 1) / TILE_ROWS, { snapKind: "h_edge", tx, vy: ty + 1 });
    consider(tx / TILE_COLS, (ty + 0.5) / TILE_ROWS, { snapKind: "v_edge", vx: tx, ty });
    consider((tx + 1) / TILE_COLS, (ty + 0.5) / TILE_ROWS, { snapKind: "v_edge", vx: tx + 1, ty });

    for (let ox = 0; ox <= 1; ox += 1) {
      for (let oy = 0; oy <= 1; oy += 1) {
        const cvx = Math.max(0, Math.min(VERTEX_COLS - 1, tx + ox));
        const cvy = Math.max(0, Math.min(VERTEX_ROWS - 1, ty + oy));
        consider(cvx / TILE_COLS, cvy / TILE_ROWS, { snapKind: "vertex", vx: cvx, vy: cvy });
      }
    }

    return best;
  }

  function drawTileGrid(svg) {
    if (!accessLayers.tileGrid) return;
    const stepX = SVG_W / TILE_COLS;
    const stepY = SVG_H / TILE_ROWS;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.setAttribute("class", "accessTileGrid");
    g.style.pointerEvents = "none";

    let defs = svg.querySelector("defs.accessTileDefs");
    if (!defs) {
      defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
      defs.setAttribute("class", "accessTileDefs");
      const pattern = document.createElementNS("http://www.w3.org/2000/svg", "pattern");
      pattern.setAttribute("id", "accessTilePattern");
      pattern.setAttribute("patternUnits", "userSpaceOnUse");
      pattern.setAttribute("width", String(stepX));
      pattern.setAttribute("height", String(stepY));

      const addLine = (x1, y1, x2, y2, stroke, width) => {
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", String(x1));
        line.setAttribute("y1", String(y1));
        line.setAttribute("x2", String(x2));
        line.setAttribute("y2", String(y2));
        line.setAttribute("stroke", stroke);
        line.setAttribute("stroke-width", String(width));
        pattern.appendChild(line);
      };

      addLine(0, stepY, stepX, stepY, "rgba(255,255,255,0.14)", 1);
      addLine(stepX, 0, stepX, stepY, "rgba(255,255,255,0.14)", 1);
      addLine(0, 0, stepX, stepY, "rgba(0,229,255,0.07)", 0.75);
      addLine(stepX, 0, 0, stepY, "rgba(0,229,255,0.07)", 0.75);

      defs.appendChild(pattern);
      svg.insertBefore(defs, svg.firstChild);
    }

    const fill = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    fill.setAttribute("x", "0");
    fill.setAttribute("y", "0");
    fill.setAttribute("width", String(SVG_W));
    fill.setAttribute("height", String(SVG_H));
    fill.setAttribute("fill", "url(#accessTilePattern)");
    g.appendChild(fill);
    svg.appendChild(g);
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

  function isGateOnBarrier(gate) {
    return !!(gate?.barrier_id) && gate?.barrier_segment_index != null;
  }

  function portalFenceLineHeading(gate) {
    const fence = gateFenceHeading(gate);
    if (isGateOnBarrier(gate)) return (fence + 90) % 360;
    return fence;
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
    const heading = portalFenceLineHeading(gate);
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

  function snapRadiusNorm(base) {
    const scale = typeof getMapScale === "function" ? getMapScale() : 1;
    return base / Math.max(1, scale);
  }

  function iterBarrierSegments(barrier) {
    if (barrier?.tiles?.length) {
      return iterTileBarrierSegments(barrier);
    }
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
    if (!accessLayers.snapPoints && accessTool !== "drawBarrier") {
      return { x: p.x, y: p.y, snapped: false };
    }

    let best = null;
    let bestDist = snapRadiusNorm(BARRIER_ENDPOINT_SNAP_RADIUS);

    const considerPoint = (pt, meta) => {
      const d = Math.hypot(p.x - pt.x, p.y - pt.y);
      if (d < bestDist) {
        bestDist = d;
        best = { x: pt.x, y: pt.y, snapped: true, ...meta };
      }
    };

    if (accessTool === "drawBarrier") {
      draftBarrierPoints.forEach((pt, idx) => {
        considerPoint(pt, {
          snapKind: "draft_point",
          pointIndex: idx,
        });
      });
    }

    accessBarriers.forEach((barrier) => {
      (barrier.points || []).forEach((pt, idx) => {
        considerPoint(pt, {
          snapKind: "barrier_endpoint",
          barrierId: barrier.id,
          barrierName: barrier.name,
          pointIndex: idx,
        });
      });
    });
    if (best) return best;

    bestDist = snapRadiusNorm(BARRIER_SEGMENT_SNAP_RADIUS);
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
    const { vx, vy } = vertexFromNorm(p.x, p.y);
    const snapped = normFromVertex(vx, vy);
    return {
      x: snapped.x,
      y: snapped.y,
      snapped: true,
      snapKind: "grid_vertex",
      vx,
      vy,
    };
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
      if (snapInfo.snapKind === "barrier_endpoint" || snapInfo.snapKind === "draft_point") {
        setStatus(`Snapped to corner (point ${draftBarrierPoints.length}).`);
      } else if (snapInfo.snapKind === "grid_vertex") {
        setStatus(`Snapped to grid vertex (${snapInfo.vx}, ${snapInfo.vy}) — point ${draftBarrierPoints.length}.`);
      } else if (snapInfo.snapKind === "barrier_segment") {
        setStatus(`Snapped to ${snapInfo.barrierName} edge (point ${draftBarrierPoints.length}).`);
      } else {
        setStatus(`Snapped to ${snapInfo.gateName} side ${snapInfo.side.toUpperCase()} (point ${draftBarrierPoints.length}).`);
      }
    } else {
      setStatus(`Barrier point ${draftBarrierPoints.length}. Clicks snap to grid vertices (H/V/diagonal segments).`);
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
      svg.setAttribute("preserveAspectRatio", "none");
      svg.classList.add("accessOverlay");
    }
    svg.style.pointerEvents = "none";
    wrap.appendChild(svg);
    return svg;
  }

  function pathStrokeWidthPx(widthTiles) {
    return Math.max(5, Number(widthTiles || 1) * 4);
  }

  function drawQueueLiveStroke(svg, state, committed) {
    if (!state && !(committed && committed.length >= 1)) return;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.style.pointerEvents = "none";

    if (committed && committed.length >= 1) {
      const pl = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      pl.setAttribute("fill", "none");
      pl.setAttribute(
        "points",
        committed.map((p) => `${p.x * SVG_W},${p.y * SVG_H}`).join(" ")
      );
      pl.setAttribute("stroke", "#26c6da");
      pl.setAttribute("stroke-width", "5");
      pl.setAttribute("stroke-linecap", "round");
      pl.setAttribute("stroke-linejoin", "round");
      pl.setAttribute("opacity", "0.9");
      g.appendChild(pl);
    }

    if (state) {
      const endSnap = snapQueueEndpoint({ x: state.curX, y: state.curY });
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(state.startX * SVG_W));
      line.setAttribute("y1", String(state.startY * SVG_H));
      line.setAttribute("x2", String(endSnap.x * SVG_W));
      line.setAttribute("y2", String(endSnap.y * SVG_H));
      line.setAttribute("stroke", endSnap.snapped ? "#ffe082" : "#00e5ff");
      line.setAttribute("stroke-width", "5");
      line.setAttribute("stroke-linecap", "round");
      line.setAttribute("stroke-dasharray", endSnap.snapped ? "none" : "8 5");
      line.setAttribute("opacity", "0.95");
      g.appendChild(line);

      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", String(endSnap.x * SVG_W));
      dot.setAttribute("cy", String(endSnap.y * SVG_H));
      dot.setAttribute("r", endSnap.snapped ? "6" : "5");
      dot.setAttribute("fill", endSnap.snapped ? "#ffe082" : "#00e5ff");
      dot.setAttribute("stroke", "#ffffff");
      dot.setAttribute("stroke-width", "2");
      g.appendChild(dot);
    }

    svg.appendChild(g);
  }

  function drawPathLiveStroke(svg, state, committed) {
    if (!state && !committed) return;
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    g.style.pointerEvents = "none";

    if (state) {
      const start = normFromGrid(state.startTx, state.startTy);
      const endAnchor = pathDragAnchor({ x: state.curX, y: state.curY });
      const end = normFromGrid(endAnchor.tx, endAnchor.ty);
      const snapped = endAnchor.snapped;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(start.x * SVG_W));
      line.setAttribute("y1", String(start.y * SVG_H));
      line.setAttribute("x2", String(end.x * SVG_W));
      line.setAttribute("y2", String(end.y * SVG_H));
      line.setAttribute("stroke", snapped ? "#ffe082" : "#00e5ff");
      line.setAttribute("stroke-width", String(pathStrokeWidthPx(state.width)));
      line.setAttribute("stroke-linecap", "round");
      line.setAttribute("stroke-dasharray", snapped ? "none" : "8 5");
      line.setAttribute("opacity", "0.95");
      g.appendChild(line);

      const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      dot.setAttribute("cx", String(end.x * SVG_W));
      dot.setAttribute("cy", String(end.y * SVG_H));
      dot.setAttribute("r", snapped ? "6" : "5");
      dot.setAttribute("fill", snapped ? "#ffe082" : "#00e5ff");
      dot.setAttribute("stroke", "#ffffff");
      dot.setAttribute("stroke-width", "2");
      g.appendChild(dot);
    }

    if (committed && committed.length >= 2) {
      const pl = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      pl.setAttribute("fill", "none");
      pl.setAttribute(
        "points",
        committed.map((p) => `${p.x * SVG_W},${p.y * SVG_H}`).join(" ")
      );
      pl.setAttribute("stroke", "#26c6da");
      pl.setAttribute("stroke-width", String(pathStrokeWidthPx(getPathBrushWidth())));
      pl.setAttribute("stroke-linecap", "round");
      pl.setAttribute("stroke-linejoin", "round");
      pl.setAttribute("opacity", "0.85");
      g.appendChild(pl);
    }

    svg.appendChild(g);
  }

  function toSvg(x, y) {
    return { x: x * SVG_W, y: y * SVG_H };
  }

  function gridFromNorm(x, y) {
    return {
      gx: Math.max(0, Math.min(TILE_COLS - 1, Math.floor(x * TILE_COLS))),
      gy: Math.max(0, Math.min(TILE_ROWS - 1, Math.floor(y * TILE_ROWS))),
    };
  }

  function normFromGrid(gx, gy) {
    return { x: (gx + 0.5) / TILE_COLS, y: (gy + 0.5) / TILE_ROWS };
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
      if (barrier.tiles?.length) {
        barrier.tiles.forEach(([tx, ty]) => mark(tx, ty));
        return;
      }
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
    return normFromVertex(gx, gy);
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

    drawTileGrid(svg);

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
      if (barrier.tiles?.length) {
        const keys = barrier.tiles.map(([tx, ty]) => tileKey(tx, ty));
        const wrap = document.createElementNS("http://www.w3.org/2000/svg", "g");
        wrap.style.pointerEvents = "auto";
        wrap.onclick = (ev) => {
          ev.stopPropagation();
          selectBarrier(barrier.id);
        };
        const stepX = SVG_W / TILE_COLS;
        const stepY = SVG_H / TILE_ROWS;
        keys.forEach((key) => {
          const { tx, ty } = parseTileKey(key);
          const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
          rect.setAttribute("x", String(tx * stepX));
          rect.setAttribute("y", String(ty * stepY));
          rect.setAttribute("width", String(stepX));
          rect.setAttribute("height", String(stepY));
          rect.style.fill =
            selectedBarrierId === barrier.id ? "rgba(109,247,167,0.55)" : "rgba(255,138,101,0.72)";
          rect.style.stroke = selectedBarrierId === barrier.id ? "#6df7a7" : "#ff8a65";
          rect.style.strokeWidth = selectedBarrierId === barrier.id ? "1.5" : "1";
          wrap.appendChild(rect);
        });
        svg.appendChild(wrap);
        return;
      }
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

    accessQueues.forEach((queue) => {
      if (!accessLayers.queues) return;
      const pts = queue.points || [];
      if (pts.length < 2) return;
      const pl = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
      pl.setAttribute("fill", "none");
      pl.setAttribute(
        "points",
        pts.map((p) => `${p.x * SVG_W},${p.y * SVG_H}`).join(" ")
      );
      pl.setAttribute("stroke", selectedQueueId === queue.id ? "#80cbc4" : "#26c6da");
      pl.setAttribute("stroke-width", selectedQueueId === queue.id ? "6" : "4");
      pl.setAttribute("stroke-dasharray", "10 6");
      pl.setAttribute("stroke-linecap", "round");
      pl.setAttribute("stroke-linejoin", "round");
      pl.style.pointerEvents = "stroke";
      pl.onclick = (ev) => {
        ev.stopPropagation();
        selectAccessQueue(queue.id);
      };
      svg.appendChild(pl);
      const head = pts[pts.length - 1];
      const tail = pts[0];
      [
        { p: tail, label: "tail", fill: "#ffd166" },
        { p: head, label: "scanner", fill: "#26c6da" },
      ].forEach(({ p, fill }) => {
        const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        dot.setAttribute("cx", String(p.x * SVG_W));
        dot.setAttribute("cy", String(p.y * SVG_H));
        dot.setAttribute("r", "5");
        dot.setAttribute("fill", fill);
        dot.setAttribute("stroke", "#0d1520");
        dot.setAttribute("stroke-width", "1.5");
        dot.style.pointerEvents = "none";
        svg.appendChild(dot);
      });
    });

    if (
      (queueDragState || draftQueuePoints.length >= 1) &&
      (accessLayers.queues || accessTool === "drawQueue")
    ) {
      drawQueueLiveStroke(svg, queueDragState, draftQueuePoints);
    }

    if ((draftBarrierTiles.size || barrierDragPreviewTiles.size) && (accessLayers.barriers || accessTool === "drawBarrier")) {
      drawBarrierTileRects(
        svg,
        allDraftBarrierTileKeys(),
        "#ffd166",
        "rgba(255,209,102,0.55)",
        true
      );
    }

    if ((draftPathTiles.size || pathDragPreviewTiles.size) && (accessLayers.paths || accessTool === "drawPath")) {
      drawBarrierTileRects(
        svg,
        allDraftPathTileKeys(),
        "#00e5ff",
        "rgba(0,229,255,0.55)",
        true
      );
    }

    if (
      accessTool === "drawPath" &&
      (pathDragState || draftPathTiles.size || pathDragPreviewTiles.size || pathDraftVertices.length >= 2)
    ) {
      drawPathLiveStroke(svg, pathDragState, pathDraftVertices);
    }

    accessPaths.forEach((path) => {
      if (!accessLayers.paths) return;
      const keys = (path.tiles || []).map(([tx, ty]) => tileKey(tx, ty));
      if (!keys.length) return;
      const wrap = document.createElementNS("http://www.w3.org/2000/svg", "g");
      wrap.style.pointerEvents = "auto";
      wrap.onclick = (ev) => {
        ev.stopPropagation();
        selectPath(path.id);
      };
      drawBarrierTileRects(
        wrap,
        keys,
        selectedPathId === path.id ? "#6df7a7" : "#26a69a",
        selectedPathId === path.id ? "rgba(109,247,167,0.55)" : "rgba(38,166,154,0.48)",
        selectedPathId === path.id
      );
      svg.appendChild(wrap);
      if (accessLayers.paths) drawPathFlowArrows(svg, path);
    });

    if (accessLayers.spawnPoints) {
      accessSpawnPoints.forEach((sp) => {
        const mx = sp.map_x ?? sp.mapX ?? 0.5;
        const my = sp.map_y ?? sp.mapY ?? 0.5;
        const cx = mx * SVG_W;
        const cy = my * SVG_H;
        const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
        g.style.pointerEvents = "auto";
        g.onclick = (ev) => {
          ev.stopPropagation();
          selectSpawnPoint(sp.id);
        };
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        circle.setAttribute("cx", String(cx));
        circle.setAttribute("cy", String(cy));
        circle.setAttribute("r", selectedSpawnId === sp.id ? "7" : "5.5");
        circle.setAttribute("fill", selectedSpawnId === sp.id ? "#81c784" : "#4caf50");
        circle.setAttribute("stroke", "#fff");
        circle.setAttribute("stroke-width", "1.2");
        g.appendChild(circle);
        const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
        label.setAttribute("x", String(cx));
        label.setAttribute("y", String(cy + 3));
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("fill", "#fff");
        label.setAttribute("font-size", "8");
        label.setAttribute("font-weight", "700");
        label.textContent = "S";
        label.style.pointerEvents = "none";
        g.appendChild(label);
        svg.appendChild(g);
      });
    }

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

  function placementFromMapPoint(gate, x, y) {
    const hit = findNearestBarrierSegment(x, y);
    if (hit && hit.dist <= SCANNER_FENCE_SNAP_RADIUS) {
      return {
        map_x: hit.x,
        map_y: hit.y,
        fence_heading_deg: Math.round(segmentTangentHeadingDeg(hit.a, hit.b)),
        barrier_id: hit.barrier_id,
        barrier_segment_index: hit.segIndex,
        barrier_segment_t: hit.t,
        snapped: true,
        barrier_name: hit.barrier_name,
      };
    }
    const anchor = snapPlacementAnchor(x, y);
    return {
      map_x: anchor.x,
      map_y: anchor.y,
      fence_heading_deg: gate?.fence_heading_deg ?? gate?.fenceHeadingDeg ?? 0,
      barrier_id: null,
      barrier_segment_index: null,
      barrier_segment_t: null,
      snapped: true,
      snap_kind: anchor.snapKind,
      barrier_name: null,
    };
  }

  async function commitScannerPlacement(gateId, x, y) {
    if (!getDashEvent()) return null;
    const gate = (getDashGates() || []).find((g) => g.id === gateId);
    if (!gate) return null;
    const place = placementFromMapPoint(gate, x, y);
    const allowed = gate.allowed_classes || [];
    const updated = await api(`/events/${getDashEvent().id}/scanners/${gateId}/access`, {
      method: "PUT",
      body: JSON.stringify({
        zone_a_id: gate.zone_a_id || null,
        zone_b_id: gate.zone_b_id || null,
        allowed_classes: allowed,
        direction: gate.direction || "bidirectional",
        barrier_id: place.barrier_id,
        barrier_segment_index: place.barrier_segment_index,
        barrier_segment_t: place.barrier_segment_t,
        map_x: place.map_x,
        map_y: place.map_y,
        fence_heading_deg: place.fence_heading_deg,
        updated_by: "dash_access",
      }),
    });
    const idx = (getDashGates() || []).findIndex((g) => g.id === gateId);
    if (idx >= 0 && typeof gates !== "undefined") gates[idx] = updated;
    return { updated, place };
  }

  let gateDragState = null;

  function setGateMarkerPosition(gateId, x, y) {
    const el = document.querySelector(`.marker.gate[data-gate-id="${gateId}"]`);
    if (!el || typeof pct !== "function") return;
    el.style.left = pct(x);
    el.style.top = pct(y);
  }

  function decorateGateDragHandles() {
    document.querySelectorAll(".gateDragHandle").forEach((d) => d.remove());
    if (!accessLayers.gates || accessTool === "drawBarrier" || accessTool === "drawPath") return;

    (getDashGates() || []).forEach((gate) => {
      const el = document.querySelector(`.marker.gate[data-gate-id="${gate.id}"]`);
      if (!el) return;
      const handle = document.createElement("span");
      handle.className = "gateDragHandle";
      handle.title = "Drag scanner; release on a fence to snap an entry gap";
      handle.onpointerdown = (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        gateDragState = {
          gateId: gate.id,
          pointerId: ev.pointerId,
          handle,
          marker: el,
        };
        handle.classList.add("dragging");
        el.classList.add("draggingGate");
        if (typeof setSelected === "function") setSelected("gate", gate.id);
        handle.setPointerCapture(ev.pointerId);
        setStatus(`Dragging ${gate.name || "scanner"}… release on a fence to snap.`);
      };
      handle.onpointermove = (ev) => {
        if (!gateDragState || gateDragState.gateId !== gate.id || ev.pointerId !== gateDragState.pointerId) {
          return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        const p = mapXY(ev);
        const g = (getDashGates() || []).find((item) => item.id === gate.id);
        if (g) {
          const place = placementFromMapPoint(g, p.x, p.y);
          g.map_x = place.map_x;
          g.map_y = place.map_y;
          g.fence_heading_deg = place.fence_heading_deg;
        }
        setGateMarkerPosition(gate.id, g.map_x, g.map_y);
        decorateGateMarkers();
        drawAccessLayers();
      };
      handle.onpointerup = async (ev) => {
        if (!gateDragState || gateDragState.gateId !== gate.id || ev.pointerId !== gateDragState.pointerId) {
          return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        handle.classList.remove("dragging");
        el.classList.remove("draggingGate");
        const p = mapXY(ev);
        gateDragState = null;
        try {
          const result = await commitScannerPlacement(gate.id, p.x, p.y);
          if (!result) return;
          portalHeadingPreview = result.place.fence_heading_deg;
          syncFenceHeadingControls(result.place.fence_heading_deg);
          renderAccessLists();
          updateAccessMapPanel();
          drawBase();
          if (result.place.snapped) {
            setStatus(`Scanner snapped to ${result.place.barrier_name} — entry gap created.`);
          } else {
            setStatus("Scanner moved.");
          }
        } catch (err) {
          drawBase();
          setStatus(err.message || String(err));
        }
      };
      handle.onpointercancel = (ev) => {
        if (!gateDragState || gateDragState.gateId !== gate.id) return;
        handle.classList.remove("dragging");
        el.classList.remove("draggingGate");
        gateDragState = null;
        drawBase();
      };
      el.appendChild(handle);
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
    accessQueues = await api(`/events/${eventId}/access-queues`);
    try {
      accessPaths = await api(`/events/${eventId}/access-paths`);
    } catch {
      accessPaths = [];
    }
    try {
      accessSpawnPoints = await api(`/events/${eventId}/access-spawn-points`);
    } catch {
      accessSpawnPoints = [];
    }
    accessSimLocations = await api(`/events/${eventId}/sim-locations`);
    renderAccessLists();
    syncAccessToolPanels();
    if (showsAccessMapLayers()) drawAccessLayers();
  }

  function setAccessTool(tool) {
    accessTool = tool;
    if (tool === "select") {
      selectedBarrierId = null;
      selectedZoneId = null;
      selectedQueueId = null;
      selectedPathId = null;
    } else if (tool === "drawBarrier") {
      selectedZoneId = null;
      selectedQueueId = null;
      selectedPathId = null;
    } else if (tool === "drawPath") {
      selectedBarrierId = null;
      selectedZoneId = null;
      selectedQueueId = null;
      selectedSpawnId = null;
    } else if (tool === "placeSpawn") {
      selectedBarrierId = null;
      selectedZoneId = null;
      selectedQueueId = null;
      selectedPathId = null;
    } else if (tool === "drawQueue") {
      selectedBarrierId = null;
      selectedZoneId = null;
      selectedPathId = null;
    } else if (tool === "fillZone") {
      selectedBarrierId = null;
      selectedQueueId = null;
      selectedPathId = null;
    } else if (tool === "rfidDevices" || tool === "linkPortal" || tool === "workLocations") {
      selectedBarrierId = null;
      selectedZoneId = null;
      selectedQueueId = null;
      selectedPathId = null;
    }
    draftBarrierPoints = [];
    draftBarrierTiles = new Set();
    draftBarrierClosed = false;
    barrierDragState = null;
    barrierDragPreviewTiles = new Set();
    draftPathTiles = new Set();
    pathDragState = null;
    pathDragPreviewTiles = new Set();
    pathDraftVertices = [];
    draftQueuePoints = [];
    queueDragState = null;
    syncAccessToolbarButtons();
    const hints = {
      select: "Select barriers, zones, queues, or scanners on the map or in the list.",
      drawBarrier: "Drag on the map to paint barrier tiles (2ft each). Release and drag again to extend. Finish when done.",
      drawPath:
        "Drag on the map to paint a path in walk order. Yellow arrows show flow. Use Save Flow to reverse direction.",
      placeSpawn:
        "Click a painted path to snap a token spawn. Set ticket class first — sim injects tokens here.",
      drawQueue:
        "Drag from the back of the line toward the scanner — cyan line follows the cursor; release near a portal to snap. Pick a scanner first.",
      fillZone: "Click inside a closed barrier perimeter. Place scanners on fence segments to create entry gaps.",
      linkPortal: "Select a scanner on the map or use Scanners to edit rules per device.",
      rfidDevices: "Add, edit, or place scanners on the map.",
      workLocations:
        "Place staff/vendor work spots on the map. Sim routes staff and vendors here without creating nested zones.",
    };
    setStatus(hints[tool] || "Access control ready.");
    syncAccessToolPanels();
    renderAccessLists();
    const toolPanelIds = {
      drawBarrier: "accessBarrierSection",
      drawPath: "accessPathSection",
      placeSpawn: "accessSpawnSection",
      drawQueue: "accessQueueSection",
      fillZone: "accessZoneSection",
    };
    const toolPanel = document.getElementById(toolPanelIds[tool]);
    if (toolPanel) toolPanel.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (tool === "rfidDevices" && typeof renderAccessRfidList === "function") renderAccessRfidList();
    renderWorkLocationSection();
    updateAccessMapPanel();
    if (typeof drawBase === "function") drawBase();
    if (showsAccessMapLayers()) drawAccessLayers();
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

    const pathList = document.getElementById("accessPathList");
    if (pathList) {
      pathList.innerHTML =
        accessPaths
          .map((path) => {
            const width = path.width_tiles || path.widthTiles || 1;
            const flow = (path.flow_direction || path.flowDirection || "forward") === "reverse" ? "← reverse" : "→ forward";
            return `<div class="card ${selectedPathId === path.id ? "selected" : ""}" onclick="selectAccessPath('${path.id}')"><h3>${escapeHtml(path.name)}</h3><p>${pathWidthLabel(width)} • ${(path.tiles || []).length} tiles • ${flow}</p><button class="danger" onclick="event.stopPropagation(); deleteAccessPath('${path.id}')">Delete</button></div>`;
          })
          .join("") || '<p class="muted">No guest paths yet.</p>';
    }

    const spawnList = document.getElementById("accessSpawnList");
    if (spawnList) {
      spawnList.innerHTML =
        accessSpawnPoints
          .map((sp) => {
            const path = accessPaths.find((p) => p.id === sp.path_id);
            const pathName = path ? path.name : sp.path_id;
            return `<div class="card ${selectedSpawnId === sp.id ? "selected" : ""}" onclick="selectSpawnPoint('${sp.id}')"><h3>${escapeHtml(sp.name)}</h3><p>${escapeHtml(pathName)} • ${(sp.ticket_class || "ga").toUpperCase()} • tile ${sp.tile_index + 1}</p><button class="danger" onclick="event.stopPropagation(); deleteSpawnPoint('${sp.id}')">Delete</button></div>`;
          })
          .join("") || '<p class="muted">No spawn points yet. Use Place Spawn on a path.</p>';
    }

    zoneList.innerHTML =
      accessZones
        .map((z) => {
          const swatch = z.fill_color || ZONE_COLORS[z.zone_class] || ZONE_COLORS.ga;
          return `<div class="card ${selectedZoneId === z.id ? "selected" : ""}" onclick="selectAccessZone('${z.id}')"><div class="row" style="align-items:center;gap:10px"><span class="zoneColorSwatch" style="background:${swatch}"></span><div><h3>${escapeHtml(z.name)}</h3><p>${zoneLabel(z.zone_class)} • ${(z.polygon || []).length} vertices</p></div></div><button class="danger" onclick="event.stopPropagation(); deleteAccessZone('${z.id}')">Delete</button></div>`;
        })
        .join("") || '<p class="muted">No zones yet.</p>';

    const queueList = document.getElementById("accessQueueList");
    if (queueList) {
      queueList.innerHTML =
        accessQueues
          .map((q) => {
            const gate = (getDashGates() || []).find((g) => g.id === q.gate_id);
            const gateName = gate ? gate.name : q.gate_id;
            return `<div class="card ${selectedQueueId === q.id ? "selected" : ""}" onclick="selectAccessQueue('${q.id}')"><h3>${escapeHtml(q.name)}</h3><p>${escapeHtml(gateName)} • ${(q.points || []).length} points</p><button class="danger" onclick="event.stopPropagation(); deleteAccessQueue('${q.id}')">Delete</button></div>`;
          })
          .join("") || '<p class="muted">No queue lines yet.</p>';
    }

    const gateSelect = document.getElementById("accessQueueGate");
    if (gateSelect) {
      const gates = getDashGates() || [];
      gateSelect.innerHTML = gates
        .map(
          (g) =>
            `<option value="${g.id}" ${selectedKind === "gate" && selectedId === g.id ? "selected" : ""}>${escapeHtml(g.name || g.id)}</option>`
        )
        .join("");
      if (!gateSelect.value && gates[0]) gateSelect.value = gates[0].id;
    }

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
    accessTool = "select";
    syncAccessToolbarButtons();
    selectedBarrierId = id;
    selectedZoneId = null;
    selectedPathId = null;
    selectedQueueId = null;
    portalHeadingPreview = null;
    portalFlowFlipPreview = null;
    syncAccessToolPanels();
    renderAccessLists();
    drawAccessLayers();
    setStatus("Selected barrier.");
  }

  function selectZone(id) {
    accessTool = "select";
    syncAccessToolbarButtons();
    selectedZoneId = id;
    selectedBarrierId = null;
    selectedPathId = null;
    selectedQueueId = null;
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
    syncAccessToolPanels();
    renderAccessLists();
    drawAccessLayers();
    setStatus("Selected zone.");
  }

  window.selectAccessBarrier = selectBarrier;
  window.selectAccessZone = selectZone;

  function selectPath(id) {
    accessTool = "select";
    syncAccessToolbarButtons();
    selectedPathId = id;
    selectedBarrierId = null;
    selectedZoneId = null;
    selectedQueueId = null;
    const path = accessPaths.find((p) => p.id === id);
    if (path) {
      const widthEl = document.getElementById("accessPathWidth");
      const nameEl = document.getElementById("accessPathName");
      const flowEl = document.getElementById("accessPathFlow");
      const width = path.width_tiles || path.widthTiles || 1;
      if (widthEl) widthEl.value = String(width);
      if (nameEl) nameEl.value = path.name;
      if (flowEl) flowEl.value = path.flow_direction || path.flowDirection || "forward";
      pathBrushWidth = width;
    }
    selectedSpawnId = null;
    syncAccessToolPanels();
    renderAccessLists();
    drawAccessLayers();
    setStatus("Selected guest path.");
  }

  window.selectAccessPath = selectPath;

  function selectSpawnPoint(id) {
    accessTool = "select";
    syncAccessToolbarButtons();
    selectedSpawnId = id;
    selectedPathId = null;
    selectedBarrierId = null;
    selectedZoneId = null;
    selectedQueueId = null;
    const sp = accessSpawnPoints.find((s) => s.id === id);
    if (sp) {
      const nameEl = document.getElementById("accessSpawnName");
      const classEl = document.getElementById("accessSpawnClass");
      if (nameEl) nameEl.value = sp.name;
      if (classEl) classEl.value = sp.ticket_class || "ga";
    }
    syncAccessToolPanels();
    renderAccessLists();
    drawAccessLayers();
    setStatus("Selected spawn point.");
  }

  window.selectSpawnPoint = selectSpawnPoint;

  window.deleteSpawnPoint = async function (id) {
    if (!confirm("Delete this spawn point?")) return;
    await api(`/events/${getDashEvent().id}/access-spawn-points/${id}`, { method: "DELETE" });
    accessSpawnPoints = accessSpawnPoints.filter((s) => s.id !== id);
    if (selectedSpawnId === id) selectedSpawnId = null;
    renderAccessLists();
    drawAccessLayers();
    setStatus("Deleted spawn point.");
  };

  window.saveSelectedPathFlow = async function () {
    if (!selectedPathId || !getDashEvent()) {
      setStatus("Select a path first.");
      return;
    }
    const flow = document.getElementById("accessPathFlow")?.value || "forward";
    try {
      const updated = await api(`/events/${getDashEvent().id}/access-paths/${selectedPathId}`, {
        method: "PUT",
        body: JSON.stringify({ flow_direction: flow, updated_by: "dash_access" }),
      });
      const idx = accessPaths.findIndex((p) => p.id === selectedPathId);
      if (idx >= 0) accessPaths[idx] = updated;
      drawAccessLayers();
      renderAccessLists();
      setStatus(`Path flow set to ${flow === "reverse" ? "reverse" : "forward"}.`);
    } catch (err) {
      setStatus(`Save flow failed: ${err.message || err}`);
    }
  };

  window.selectAccessPortal = function (id) {
    portalHeadingPreview = null;
    portalFlowFlipPreview = null;
    if (typeof selectGate === "function") selectGate(id);
    setAccessTool("rfidDevices");
    renderAccessLists();
    updateAccessMapPanel();
    drawAccessLayers();
  };

  window.clearDraftBarrierTiles = function () {
    draftBarrierTiles = new Set();
    barrierDragState = null;
    barrierDragPreviewTiles = new Set();
    drawAccessLayers();
    setStatus("Cleared painted tiles. Drag to paint again.");
  };

  window.closeDraftBarrier = function () {
    clearDraftBarrierTiles();
  };

  window.finishDraftBarrier = async function () {
    if (!getDashEvent()) return;
    if (draftBarrierTiles.size < 1) {
      setStatus("Paint at least one tile by dragging on the map.");
      return;
    }
    const name = document.getElementById("accessBarrierName")?.value?.trim() || "Barrier";
    const barrier_type = document.getElementById("accessBarrierType")?.value || "fence";
    const created = await api(`/events/${getDashEvent().id}/access-barriers`, {
      method: "POST",
      body: JSON.stringify({
        name,
        barrier_type,
        points: [],
        tiles: tilesToPayloadList(draftBarrierTiles),
        closed: false,
        updated_by: "dash_access",
      }),
    });
    draftBarrierTiles = new Set();
    draftBarrierPoints = [];
    draftBarrierClosed = false;
    barrierDragState = null;
    barrierDragPreviewTiles = new Set();
    accessBarriers.push(created);
    enterSelectCategory("barriers", created.id);
    renderAccessLists();
    drawAccessLayers();
    setStatus(`Saved tile barrier "${created.name}" (${created.tiles?.length || 0} tiles).`);
  };

  window.cancelDraftBarrier = function () {
    draftBarrierPoints = [];
    draftBarrierTiles = new Set();
    draftBarrierClosed = false;
    barrierDragState = null;
    barrierDragPreviewTiles = new Set();
    drawAccessLayers();
    setStatus("Barrier drawing cancelled.");
  };

  window.clearDraftPathTiles = function () {
    draftPathTiles = new Set();
    pathDragState = null;
    pathDragPreviewTiles = new Set();
    pathDraftVertices = [];
    unbindPathDragListeners();
    drawAccessLayers();
    setStatus("Cleared path paint. Drag to paint again.");
  };

  window.cancelDraftPath = function () {
    draftPathTiles = new Set();
    pathDragState = null;
    pathDragPreviewTiles = new Set();
    pathDraftVertices = [];
    unbindPathDragListeners();
    drawAccessLayers();
    setStatus("Path drawing cancelled.");
  };

  window.finishDraftPath = async function () {
    if (!getDashEvent()) return;
    if (draftPathTiles.size < 1) {
      setStatus("Paint at least one path tile by dragging on the map.");
      return;
    }
    const name = document.getElementById("accessPathName")?.value?.trim() || "Path";
    const width_tiles = getPathBrushWidth();
    const flow_direction = document.getElementById("accessPathFlow")?.value || "forward";
    const orderedTiles = orderedPathTilesFromPaint(draftPathTiles, pathDraftVertices);
    try {
      const created = await api(`/events/${getDashEvent().id}/access-paths`, {
        method: "POST",
        body: JSON.stringify({
          name,
          width_tiles,
          tiles: orderedTiles.length ? orderedTiles : tilesToPayloadList(draftPathTiles),
          flow_direction,
          updated_by: "dash_access",
        }),
      });
      draftPathTiles = new Set();
      pathDragState = null;
      pathDragPreviewTiles = new Set();
      pathDraftVertices = [];
      unbindPathDragListeners();
      accessPaths.push(created);
      enterSelectCategory("paths", created.id);
      renderAccessLists();
      drawAccessLayers();
      setStatus(`Saved guest path "${created.name}" (${created.tiles?.length || 0} tiles, ${pathWidthLabel(width_tiles)}).`);
    } catch (err) {
      setStatus(`Save path failed: ${err.message || err}`);
    }
  };

  window.deleteAccessPath = async function (id) {
    if (!confirm("Delete this guest path?")) return;
    await api(`/events/${getDashEvent().id}/access-paths/${id}`, { method: "DELETE" });
    accessPaths = accessPaths.filter((p) => p.id !== id);
    if (selectedPathId === id) selectedPathId = null;
    renderAccessLists();
    drawAccessLayers();
    setStatus("Deleted guest path.");
  };

  window.finishDraftQueue = async function () {
    if (!getDashEvent()) return;
    if (draftQueuePoints.length < 2) {
      setStatus("Add at least 2 queue points (back of line → scanner).");
      return;
    }
    const gateId = document.getElementById("accessQueueGate")?.value;
    if (!gateId) {
      setStatus("Select a scanner for this queue line.");
      return;
    }
    const gate = (getDashGates() || []).find((g) => g.id === gateId);
    if (gate) {
      const mx = gate.map_x ?? gate.mapX;
      const my = gate.map_y ?? gate.mapY;
      if (mx != null && my != null) {
        const end = snapQueueEndpoint({ x: mx, y: my });
        const last = draftQueuePoints[draftQueuePoints.length - 1];
        if (Math.hypot(last.x - end.x, last.y - end.y) > 1e-6) {
          appendQueueSegment(last.x, last.y, end.x, end.y);
        }
      }
    }
    const name = document.getElementById("accessQueueName")?.value?.trim() || "Queue";
    const created = await api(`/events/${getDashEvent().id}/access-queues`, {
      method: "POST",
      body: JSON.stringify({
        name,
        gate_id: gateId,
        points: draftQueuePoints,
        updated_by: "dash_access",
      }),
    });
    draftQueuePoints = [];
    accessQueues.push(created);
    enterSelectCategory("queues", created.id);
    renderAccessLists();
    drawAccessLayers();
    setStatus(`Saved queue "${created.name}" for scanner.`);
  };

  window.cancelDraftQueue = function () {
    draftQueuePoints = [];
    queueDragState = null;
    unbindPathDragListeners();
    drawAccessLayers();
    setStatus("Queue drawing cancelled.");
  };

  window.selectAccessQueue = function (id) {
    accessTool = "select";
    syncAccessToolbarButtons();
    selectedQueueId = id;
    selectedBarrierId = null;
    selectedZoneId = null;
    selectedPathId = null;
    const queue = accessQueues.find((q) => q.id === id);
    if (queue) {
      const gateSelect = document.getElementById("accessQueueGate");
      if (gateSelect) gateSelect.value = queue.gate_id;
    }
    syncAccessToolPanels();
    renderAccessLists();
    drawAccessLayers();
    setStatus("Selected queue line.");
  };

  window.deleteAccessQueue = async function (id) {
    if (!confirm("Delete this queue line?")) return;
    await api(`/events/${getDashEvent().id}/access-queues/${id}`, { method: "DELETE" });
    accessQueues = accessQueues.filter((q) => q.id !== id);
    if (selectedQueueId === id) selectedQueueId = null;
    renderAccessLists();
    drawAccessLayers();
    setStatus("Deleted queue line.");
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
    enterSelectCategory("zones", created.id);
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
    const gate = (getDashGates() || []).find((g) => g.id === selectedId);
    if (!gate) return;
    const allowed = [...document.querySelectorAll(".portalClass:checked")].map((el) => el.value);
    const barrierDropdown = document.getElementById("portalBarrier")?.value || "";
    const headingEl = document.getElementById("mapPortalFenceHeading");
    const fenceHeadingDeg = headingEl
      ? parseInt(headingEl.value || "0", 10)
      : Number(gate.fence_heading_deg ?? gate.fenceHeadingDeg ?? 0);
    const updated = await api(
      `/events/${getDashEvent().id}/scanners/${selectedId}/access`,
      {
        method: "PUT",
        body: JSON.stringify({
          zone_a_id: document.getElementById("portalZoneA").value || null,
          zone_b_id: document.getElementById("portalZoneB").value || null,
          barrier_id: barrierDropdown || gate.barrier_id || null,
          direction: document.getElementById("portalDirection").value,
          allowed_classes: allowed,
          map_x: gate.map_x ?? gate.mapX,
          map_y: gate.map_y ?? gate.mapY,
          fence_heading_deg: fenceHeadingDeg,
          barrier_segment_index: gate.barrier_segment_index ?? null,
          barrier_segment_t: gate.barrier_segment_t ?? null,
          updated_by: "dash_access",
        }),
      }
    );
    const idx = (getDashGates() || []).findIndex((g) => g.id === selectedId);
    if (idx >= 0 && typeof gates !== "undefined") gates[idx] = updated;
    portalHeadingPreview = null;
    portalFlowFlipPreview = null;
    syncFenceHeadingControls(updated.fence_heading_deg ?? updated.fenceHeadingDeg ?? fenceHeadingDeg);
    renderAccessLists();
    updateAccessMapPanel();
    refreshGateSnapGraphics();
    if (typeof drawBase === "function") drawBase();
    setStatus("Saved scanner access rules.");
  };

  window.snapPortalToBarrier = async function () {
    if (selectedKind !== "gate" || !selectedId) return;
    const gate = (getDashGates() || []).find((g) => g.id === selectedId);
    if (!gate) return;
    try {
      const result = await commitScannerPlacement(selectedId, gate.map_x, gate.map_y);
      if (!result) return;
      if (result.place.snapped) {
        document.getElementById("portalBarrier").value = result.place.barrier_id;
        portalHeadingPreview = result.place.fence_heading_deg;
        syncFenceHeadingControls(result.place.fence_heading_deg);
        renderAccessLists();
        updateAccessMapPanel();
        drawBase();
        setStatus(`Scanner snapped to ${result.place.barrier_name} — entry gap created.`);
      } else {
        setStatus("Move the scanner closer to a fence, or drag the yellow handle onto the barrier.");
      }
    } catch (err) {
      setStatus(err.message || String(err));
    }
  };

  async function handleAccessMapClick(p) {
    if (typeof currentTab === "undefined" || currentTab !== "access") return false;

    if (accessTool === "drawBarrier") {
      return true;
    }

    if (accessTool === "drawPath") {
      return true;
    }

    if (accessTool === "drawQueue") {
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

    if (accessTool === "placeSpawn") {
      try {
        const snap = snapToPathTile(p.x, p.y);
        if (!snap) {
          setStatus("Click closer to a painted path tile.");
          return true;
        }
        const name = document.getElementById("accessSpawnName")?.value?.trim() || "Spawn";
        const ticket_class = document.getElementById("accessSpawnClass")?.value || "ga";
        const created = await api(`/events/${getDashEvent().id}/access-spawn-points`, {
          method: "POST",
          body: JSON.stringify({
            name,
            path_id: snap.path_id,
            tile_index: snap.tile_index,
            map_x: snap.map_x,
            map_y: snap.map_y,
            ticket_class,
            updated_by: "dash_access",
          }),
        });
        accessSpawnPoints.push(created);
        selectedSpawnId = created.id;
        renderAccessLists();
        drawAccessLayers();
        setStatus(`Placed spawn on path tile ${snap.tile_index + 1}.`);
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
        const anchor = snapPlacementAnchor(p.x, p.y);
        const created = await api(`/events/${getDashEvent().id}/sim-locations`, {
          method: "POST",
          body: JSON.stringify({
            name: meta.label,
            location_type: locationType,
            map_x: anchor.x,
            map_y: anchor.y,
            updated_by: "dash_access",
          }),
        });
        accessSimLocations.push(created);
        selectedSimLocationId = created.id;
        renderWorkLocationSection();
        if (typeof drawBase === "function") drawBase();
        setStatus(`Placed ${meta.label} on grid (${anchor.snapKind}).`);
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
      if (showsAccessMapLayers()) drawAccessLayers();
      else clearAccessOverlay();
    };

    const origDraw = drawBase;
    drawBase = function () {
      origDraw();
      applyAccessLayerVisibility();
      if (showsAccessMapLayers()) {
        if (currentTab === "access") {
          decorateGateMarkers();
          decorateGateDragHandles();
          drawSimLocationMarkers();
        }
        drawAccessLayers();
        const svg = document.getElementById("zoneSvg");
        const stage = getMapStage();
        if (svg && stage) stage.appendChild(svg);
        const simSvg = document.getElementById("simAgentSvg");
        if (simSvg && stage) stage.appendChild(simSvg);
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
      } else if (tab === "sim") {
        const finishSimMap = () => {
          if (typeof drawBase === "function") drawBase();
          drawAccessLayers();
          if (typeof window.drawSimAgents === "function") window.drawSimAgents();
        };
        if (autoLoad !== false) {
          loadAccessLayout().then(finishSimMap);
        } else {
          finishSimMap();
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
        "dragstart",
        (e) => {
          e.preventDefault();
        },
        true
      );
      mapWrap.addEventListener(
        "mousedown",
        (e) => {
          if (typeof currentTab === "undefined" || currentTab !== "access") return;
          if (e.button !== 0) return;
          if (accessTool === "drawQueue" || accessTool === "fillZone" || accessTool === "workLocations" || accessTool === "placeSpawn") {
            e.preventDefault();
            return;
          }
          if (accessTool === "drawPath") {
            const p = mapXY(e);
            beginPathDrag(p);
            e.preventDefault();
            e.stopPropagation();
            return;
          }
          if (accessTool === "drawQueue") {
            const p = mapXY(e);
            beginQueueDrag(p);
            e.preventDefault();
            e.stopPropagation();
            return;
          }
          if (accessTool !== "drawBarrier") return;
          const p = mapXY(e);
          beginBarrierDrag(p);
          e.preventDefault();
          e.stopPropagation();
        },
        true
      );
      mapWrap.addEventListener(
        "mousemove",
        (e) => {
          if (barrierDragState) {
            const p = mapXY(e);
            updateBarrierDrag(p);
            return;
          }
          if (pathDragState) {
            const p = mapXY(e);
            updatePathDrag(p);
          }
        },
        true
      );
      mapWrap.addEventListener(
        "mouseup",
        (e) => {
          if (barrierDragState) {
            endBarrierDrag();
            e.preventDefault();
            e.stopPropagation();
            return;
          }
          if (pathDragState) {
            endPathDrag();
            e.preventDefault();
            e.stopPropagation();
            return;
          }
          if (queueDragState) {
            endQueueDrag();
            e.preventDefault();
            e.stopPropagation();
          }
        },
        true
      );
      mapWrap.addEventListener(
        "mouseleave",
        () => {
          if (barrierDragState) endBarrierDrag();
          if (pathDragState) endPathDrag();
          if (queueDragState) endQueueDrag();
        },
        true
      );
      document.addEventListener("mouseup", () => {
        if (barrierDragState) endBarrierDrag();
        if (pathDragState) endPathDrag();
        if (queueDragState) endQueueDrag();
      });
      mapWrap.addEventListener(
        "click",
        (e) => {
          if (typeof currentTab === "undefined" || currentTab !== "access") return;
          if (
            accessTool !== "drawBarrier" &&
            accessTool !== "drawPath" &&
            accessTool !== "drawQueue" &&
            accessTool !== "fillZone" &&
            accessTool !== "workLocations" &&
            accessTool !== "placeSpawn"
          )
            return;
          if (accessTool === "drawBarrier" || accessTool === "drawPath") {
            e.stopImmediatePropagation();
            return;
          }
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
      accessLayerTileGrid: "tileGrid",
      accessLayerPaths: "paths",
      accessLayerSpawnPoints: "spawnPoints",
      accessLayerQueues: "queues",
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
  window.drawAccessLayers = drawAccessLayers;
  window.setAccessTool = setAccessTool;
  installAccessControl();
})();
