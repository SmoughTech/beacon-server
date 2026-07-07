(function () {
  // Live crowd-counts Dash panel. Reads the aggregation endpoints served by
  // camera_counting.py and renders the reconciled occupancy, per-source status,
  // and a density heatmap overlaid on the shared map (SVG inside #mapStage).
  const SVG_W = 1000;
  const SVG_H = 562.5;
  const POLL_MS = 3000;

  let countsAuto = true;
  let countsTimer = null;
  let countsSvg = null;
  let lastHeatmap = { sources: [] };

  function getEventId() {
    if (typeof currentEvent !== "undefined" && currentEvent && currentEvent.id) {
      return currentEvent.id;
    }
    return null;
  }

  function fmt(n) {
    return n === null || n === undefined ? "\u2014" : Number(n).toLocaleString();
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] || c)
    );
  }

  // ----- heatmap overlay ------------------------------------------------- //
  function ensureCountsSvg() {
    const stage = document.getElementById("mapStage");
    if (!stage) return null;
    if (!countsSvg) {
      countsSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      countsSvg.id = "countsHeatSvg";
      countsSvg.setAttribute("viewBox", `0 0 ${SVG_W} ${SVG_H}`);
      countsSvg.setAttribute("preserveAspectRatio", "none");
      countsSvg.classList.add("accessOverlay");
      countsSvg.style.pointerEvents = "none";
      const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
      defs.innerHTML =
        '<radialGradient id="countsHeatGrad" cx="50%" cy="50%" r="50%">' +
        '<stop offset="0%" stop-color="#ff5028" stop-opacity="0.85"/>' +
        '<stop offset="100%" stop-color="#ff5028" stop-opacity="0"/>' +
        "</radialGradient>";
      countsSvg.appendChild(defs);
    }
    stage.appendChild(countsSvg);
    return countsSvg;
  }

  function clearCountsSvg() {
    if (countsSvg) {
      // keep <defs>, drop drawn circles
      [...countsSvg.querySelectorAll("circle")].forEach((c) => c.remove());
    }
  }

  function drawCountsHeatmap() {
    if (typeof currentTab !== "undefined" && currentTab !== "counts") {
      clearCountsSvg();
      return;
    }
    const svg = ensureCountsSvg();
    if (!svg) return;
    clearCountsSvg();
    for (const src of lastHeatmap.sources || []) {
      const maxW = src.max_weight || 1;
      for (const cell of src.cells || []) {
        const r = 26; // SVG units; ~2.6% of width
        const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("cx", String(cell.x * SVG_W));
        c.setAttribute("cy", String(cell.y * SVG_H));
        c.setAttribute("r", String(r));
        c.setAttribute("fill", "url(#countsHeatGrad)");
        c.setAttribute("opacity", String(Math.min(1, (cell.w / maxW) * 0.9)));
        svg.appendChild(c);
      }
    }
  }

  // ----- rendering ------------------------------------------------------- //
  function divergenceBadge(sum) {
    if (!sum.has_density || sum.divergence.absolute === null) return "";
    const a = sum.divergence.absolute;
    const p = sum.divergence.pct;
    const mag = p === null ? null : Math.abs(p);
    const color = mag === null ? "#ffd166" : mag <= 10 ? "#6df7a7" : mag <= 25 ? "#ffd166" : "#ff6b6b";
    const txt = `${a > 0 ? "+" : ""}${fmt(a)}${p === null ? "" : " (" + p + "%)"}`;
    return `<span style="display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700;background:${color}22;color:${color}">${txt}</span>`;
  }

  function renderSummary(sum) {
    const el = document.getElementById("countsSummary");
    if (!el) return;
    const dens = sum.has_density ? fmt(sum.density_observed) : "\u2014";
    el.innerHTML =
      `<div class="row" style="align-items:stretch">
        <div class="card" style="flex:1">
          <p class="small" style="margin:0">Occupancy &middot; gate ledger (authoritative)</p>
          <div style="font-size:38px;font-weight:800;line-height:1.05">${fmt(sum.occupancy_ledger)}</div>
          <p class="small" style="margin:4px 0 0">In ${fmt(sum.total_in)} &middot; Out ${fmt(sum.total_out)} &middot; ${sum.gate_source_count} gate src</p>
        </div>
        <div class="card" style="flex:1">
          <p class="small" style="margin:0">Density observed (cross-check)</p>
          <div style="font-size:38px;font-weight:800;line-height:1.05">${dens}</div>
          <p class="small" style="margin:4px 0 0">vs ledger ${divergenceBadge(sum)} &middot; ${sum.density_source_count} density src</p>
        </div>
      </div>`;
  }

  function sourceCard(s) {
    const dotColor = s.stale ? "#ff6b6b" : "#6df7a7";
    const seen = s.age_seconds === null ? "never" : Math.round(s.age_seconds) + "s ago";
    const value =
      s.kind === "gate"
        ? `${fmt(s.cumulative_in)} in / ${fmt(s.cumulative_out)} out`
        : `${fmt(s.heads)} heads`;
    const manual =
      s.kind === "gate"
        ? `<input id="ci_${s.source_id}" type="number" placeholder="in" style="max-width:80px" />
           <input id="co_${s.source_id}" type="number" placeholder="out" style="max-width:80px" />`
        : `<input id="ch_${s.source_id}" type="number" placeholder="heads" style="max-width:90px" />`;
    return `<div class="card">
      <div class="row" style="justify-content:space-between;align-items:center">
        <h3 style="margin:0"><span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${dotColor};margin-right:7px"></span>${esc(s.name)}</h3>
        <span class="small">${esc(s.kind)} &middot; ${seen}</span>
      </div>
      <p style="margin:6px 0 8px">${value}</p>
      <div class="row">
        ${manual}
        <button onclick="pushCountSample('${s.source_id}','${s.kind}')">Push</button>
        <button class="danger" onclick="deleteCountSource('${s.source_id}')">Delete</button>
      </div>
    </div>`;
  }

  function renderSources(sum) {
    const el = document.getElementById("countsSourceList");
    if (!el) return;
    const rows = sum.sources || [];
    el.innerHTML = rows.length
      ? rows.map(sourceCard).join("")
      : '<p class="muted">No counting sources yet. Add one below, then push samples from your external counter (or manually here to test).</p>';
  }

  async function loadZoneOptions() {
    const eventId = getEventId();
    const sel = document.getElementById("countsNewZone");
    if (!eventId || !sel) return;
    try {
      const zones = await api(`/events/${eventId}/access-zones`);
      const current = sel.value;
      sel.innerHTML =
        '<option value="">Site-wide</option>' +
        zones.map((z) => `<option value="${z.id}">${esc(z.name)}</option>`).join("");
      sel.value = current;
    } catch (e) {
      /* zones optional */
    }
  }

  // ----- data ------------------------------------------------------------ //
  async function refreshCounts() {
    const eventId = getEventId();
    if (!eventId) {
      if (typeof setStatus === "function") setStatus("Select an event first.");
      return;
    }
    try {
      const [sum, heat] = await Promise.all([
        api(`/events/${eventId}/counts/summary`),
        api(`/events/${eventId}/counts/heatmap`),
      ]);
      lastHeatmap = heat || { sources: [] };
      renderSummary(sum);
      renderSources(sum);
      drawCountsHeatmap();
    } catch (e) {
      if (typeof setStatus === "function") setStatus("Counts refresh failed: " + e.message);
    }
  }

  async function createCountSource() {
    const eventId = getEventId();
    const status = document.getElementById("countsAddStatus");
    if (!eventId) return;
    const name = (document.getElementById("countsNewName")?.value || "").trim();
    const kind = document.getElementById("countsNewKind")?.value || "density";
    const zoneId = document.getElementById("countsNewZone")?.value || "";
    if (!name) {
      if (status) status.textContent = "Name required.";
      return;
    }
    try {
      await api(`/events/${eventId}/count-sources`, {
        method: "POST",
        body: JSON.stringify({ name, kind, zone_id: zoneId || null }),
      });
      document.getElementById("countsNewName").value = "";
      if (status) status.textContent = "Source added.";
      await refreshCounts();
    } catch (e) {
      if (status) status.textContent = "Add failed: " + e.message;
    }
  }

  async function deleteCountSource(sourceId) {
    const eventId = getEventId();
    if (!eventId) return;
    if (!confirm("Delete this counting source and its samples?")) return;
    try {
      await api(`/events/${eventId}/count-sources/${sourceId}`, { method: "DELETE" });
      await refreshCounts();
    } catch (e) {
      if (typeof setStatus === "function") setStatus("Delete failed: " + e.message);
    }
  }

  async function pushCountSample(sourceId, kind) {
    const eventId = getEventId();
    if (!eventId) return;
    let body = {};
    if (kind === "gate") {
      const ci = document.getElementById(`ci_${sourceId}`)?.value;
      const co = document.getElementById(`co_${sourceId}`)?.value;
      if (ci === "" && co === "") return;
      if (ci !== "") body.cumulative_in = parseInt(ci, 10);
      if (co !== "") body.cumulative_out = parseInt(co, 10);
    } else {
      const h = document.getElementById(`ch_${sourceId}`)?.value;
      if (h === "" || h == null) return;
      body.heads = parseInt(h, 10);
    }
    try {
      await api(`/events/${eventId}/count-sources/${sourceId}/samples`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      await refreshCounts();
    } catch (e) {
      if (typeof setStatus === "function") setStatus("Push failed: " + e.message);
    }
  }

  function openCountsLivePage() {
    const eventId = getEventId();
    if (!eventId) return;
    window.open(`/events/${eventId}/counts/live`, "_blank");
  }

  // ----- lifecycle ------------------------------------------------------- //
  function startPolling() {
    stopPolling();
    if (!countsAuto) return;
    countsTimer = setInterval(() => {
      if (typeof currentTab !== "undefined" && currentTab === "counts") {
        refreshCounts();
      }
    }, POLL_MS);
  }

  function stopPolling() {
    if (countsTimer) {
      clearInterval(countsTimer);
      countsTimer = null;
    }
  }

  function toggleCountsAuto() {
    countsAuto = !countsAuto;
    const btn = document.getElementById("countsAutoBtn");
    if (btn) {
      btn.textContent = "Auto: " + (countsAuto ? "On" : "Off");
      btn.classList.toggle("good", countsAuto);
      btn.classList.toggle("ghost", !countsAuto);
    }
    if (countsAuto) {
      startPolling();
      refreshCounts();
    } else {
      stopPolling();
    }
  }

  function onCountsTabChange(tab) {
    if (tab !== "counts") {
      stopPolling();
      clearCountsSvg();
      return;
    }
    loadZoneOptions();
    refreshCounts();
    startPolling();
  }

  function installCrowdCounts() {
    if (typeof drawBase !== "function") {
      setTimeout(installCrowdCounts, 100);
      return;
    }
    const origDraw = drawBase;
    drawBase = function () {
      origDraw();
      drawCountsHeatmap();
    };
  }

  window.refreshCounts = refreshCounts;
  window.createCountSource = createCountSource;
  window.deleteCountSource = deleteCountSource;
  window.pushCountSample = pushCountSample;
  window.openCountsLivePage = openCountsLivePage;
  window.toggleCountsAuto = toggleCountsAuto;
  window.onCountsTabChange = onCountsTabChange;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installCrowdCounts);
  } else {
    installCrowdCounts();
  }
})();
