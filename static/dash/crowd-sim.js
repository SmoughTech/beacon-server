(function () {
  const SVG_W = 1000;
  const SVG_H = 562.5;
  const TILE_COLS = 400;
  const TILE_ROWS = 225;
  const TICK_MS = 1000 / 30;

  let simPlaying = false;
  let simTimer = null;
  let simAgents = [];
  let simStats = {};
  let simWarnings = [];
  let simSpawnRemaining = 0;
  let simTick = 0;
  let simSvg = null;

  const STATE_COLORS = {
    walking: "#42a5f5",
    queuing: "#ffb300",
    scanning: "#ab47bc",
    idle: "#66bb6a",
  };

  function getEventId() {
    if (typeof currentEvent !== "undefined" && currentEvent && currentEvent.id) {
      return currentEvent.id;
    }
    return null;
  }

  function toSvg(tx, ty) {
    const x = ((tx + 0.5) / TILE_COLS) * SVG_W;
    const y = ((ty + 0.5) / TILE_ROWS) * SVG_H;
    return { x, y };
  }

  function agentRadiusPx() {
    return Math.max(2.2, (SVG_W / TILE_COLS) * 0.42);
  }

  function ensureSimSvg() {
    const stage = document.getElementById("mapStage");
    if (!stage) return null;
    if (!simSvg) {
      simSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      simSvg.id = "simAgentSvg";
      simSvg.setAttribute("viewBox", `0 0 ${SVG_W} ${SVG_H}`);
      simSvg.setAttribute("preserveAspectRatio", "none");
      simSvg.classList.add("accessOverlay");
      simSvg.style.pointerEvents = "none";
      stage.appendChild(simSvg);
    }
    return simSvg;
  }

  function clearSimSvg() {
    if (simSvg) simSvg.innerHTML = "";
  }

  async function refreshSimMap() {
    if (typeof loadGates === "function") {
      await loadGates();
    }
    if (typeof loadAccessLayout === "function") {
      await loadAccessLayout();
    }
    if (typeof drawBase === "function") drawBase();
    else if (typeof drawAccessLayers === "function") drawAccessLayers();
    drawSimAgents();
  }

  function drawSimAgents() {
    if (typeof currentTab !== "undefined" && currentTab !== "sim") {
      clearSimSvg();
      return;
    }
    const svg = ensureSimSvg();
    if (!svg) return;
    svg.innerHTML = "";
    const r = agentRadiusPx();
    for (const agent of simAgents) {
      const { x, y } = toSvg(agent.tx, agent.ty);
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", String(x));
      circle.setAttribute("cy", String(y));
      circle.setAttribute("r", String(r));
      circle.setAttribute("fill", STATE_COLORS[agent.state] || "#90caf9");
      circle.setAttribute("stroke", "#111");
      circle.setAttribute("stroke-width", "0.6");
      svg.appendChild(circle);
    }
    const stage = document.getElementById("mapStage");
    if (simSvg && stage) stage.appendChild(simSvg);
  }

  function updateSimStats() {
    const el = document.getElementById("simStats");
    if (!el) return;
    const s = simStats || {};
    let text = `Tick ${simTick} • spawned ${s.spawned || 0} • scanned ${s.scanned || 0} • idle ${s.idle || 0} • on map ${simAgents.length}`;
    if (simWarnings.length) {
      text += " • ⚠ " + simWarnings.join(" ");
    }
    el.textContent = text;
  }

  async function simReset() {
    const eventId = getEventId();
    if (!eventId) {
      setStatus("Select an event first.");
      return;
    }
    const ga = parseInt(document.getElementById("simGaCount")?.value || "30", 10);
    const vip = parseInt(document.getElementById("simVipCount")?.value || "0", 10);
    const spawnInterval = parseInt(document.getElementById("simSpawnInterval")?.value || "12", 10);
    try {
      await refreshSimMap();
      const data = await api(`/events/${eventId}/sim/reset`, {
        method: "POST",
        body: JSON.stringify({
          ga_count: ga,
          vip_count: vip,
          spawn_interval_ticks: spawnInterval,
        }),
      });
      applySimState(data);
      if ((data.stats?.spawned || 0) === 0 && (data.warnings || []).length) {
        setStatus("Sim reset: " + data.warnings.join(" "));
      } else {
        setStatus(`Sim reset: ${data.stats?.spawned || 0} guest(s) on map, ${data.spawn_remaining || 0} queued.`);
      }
    } catch (e) {
      setStatus("Sim reset failed: " + e.message);
    }
  }

  async function simReloadLayout() {
    const eventId = getEventId();
    if (!eventId) return;
    try {
      const data = await api(`/events/${eventId}/sim/reload`, { method: "POST" });
      await refreshSimMap();
      applySimState(data);
      setStatus("Sim layout reloaded from database.");
    } catch (e) {
      setStatus("Sim reload failed: " + e.message);
    }
  }

  async function simTickOnce() {
    const eventId = getEventId();
    if (!eventId) return;
    const data = await api(`/events/${eventId}/sim/tick`, {
      method: "POST",
      body: JSON.stringify({ steps: 1 }),
    });
    applySimState(data);
  }

  function applySimState(data) {
    simAgents = data.agents || [];
    simStats = data.stats || {};
    simWarnings = data.warnings || [];
    simTick = data.tick || 0;
    simSpawnRemaining = data.spawn_remaining || 0;
    updateSimStats();
    drawSimAgents();
  }

  function simStop() {
    simPlaying = false;
    if (simTimer) {
      clearInterval(simTimer);
      simTimer = null;
    }
    const btn = document.getElementById("simPlayBtn");
    if (btn) btn.textContent = "Play";
  }

  function simStart() {
    if (!simAgents.length && !simSpawnRemaining && !(simStats.spawned || 0)) {
      setStatus("Click Reset & Spawn first.");
      return;
    }
    simPlaying = true;
    const btn = document.getElementById("simPlayBtn");
    if (btn) btn.textContent = "Pause";
    if (simTimer) clearInterval(simTimer);
    simTimer = setInterval(() => {
      simTickOnce().catch((e) => {
        simStop();
        setStatus("Sim tick failed: " + e.message);
      });
    }, TICK_MS);
  }

  function simTogglePlay() {
    if (simPlaying) simStop();
    else simStart();
  }

  function onSimTabChange(tab) {
    if (tab !== "sim") {
      simStop();
      clearSimSvg();
      return;
    }
    refreshSimMap().catch(() => {});
  }

  async function loadSimPanel() {
    const eventId = getEventId();
    if (!eventId) return;
    await refreshSimMap();
    try {
      const data = await api(`/events/${eventId}/sim/state`);
      applySimState(data);
    } catch (e) {
      setStatus("Could not load sim state.");
    }
  }

  function installCrowdSim() {
    if (typeof drawBase !== "function") {
      setTimeout(installCrowdSim, 100);
      return;
    }
    const origDraw = drawBase;
    drawBase = function () {
      origDraw();
      drawSimAgents();
    };
  }

  window.simReset = simReset;
  window.simReloadLayout = simReloadLayout;
  window.simTogglePlay = simTogglePlay;
  window.loadSimPanel = loadSimPanel;
  window.onSimTabChange = onSimTabChange;
  window.drawSimAgents = drawSimAgents;
  window.refreshSimMap = refreshSimMap;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", installCrowdSim);
  } else {
    installCrowdSim();
  }
})();
