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
  let simScannerFlash = {};

  const STATE_COLORS = {
    on_path: "#e53935",
    walking: "#e53935",
    in_queue: "#ff9800",
    queuing: "#ff9800",
    scanning: "#ffeb3b",
    idle: "#c62828",
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

  function updateScannerFlash() {
    const flashByGate = simScannerFlash || {};
    document.querySelectorAll(".marker.gate").forEach((el) => {
      const gid = el.dataset.gateId;
      const activity = gid ? flashByGate[gid] : null;
      const progress = activity != null ? Number(activity.progress ?? activity) : 0;
      if (progress > 0) {
        el.classList.add("sim-scanning");
        const glow = 6 + progress * 18;
        el.style.boxShadow = `0 0 ${glow}px rgba(171, 71, 188, ${0.45 + progress * 0.45}), 0 0 ${glow * 2}px rgba(255, 235, 59, ${progress * 0.35})`;
        el.style.filter = `brightness(${1 + progress * 0.45})`;
      } else {
        el.classList.remove("sim-scanning");
        el.style.boxShadow = "";
        el.style.filter = "";
      }
    });
  }

  function drawSimAgents() {
    if (typeof currentTab !== "undefined" && currentTab !== "sim") {
      clearSimSvg();
      return;
    }
    const svg = ensureSimSvg();
    if (!svg) return;
    svg.innerHTML = "";
    const baseR = agentRadiusPx() * 1.15;

    for (const agent of simAgents) {
      const { x, y } = toSvg(agent.tx, agent.ty);
      const state = agent.state || "on_path";
      const isQueue = state === "in_queue" || state === "queuing";
      const isScan = state === "scanning";
      const scanProgress = isScan ? Math.max(0, Math.min(1, Number(agent.scan_progress ?? 0))) : 0;
      const r = isScan ? baseR * 1.35 : isQueue ? baseR * 1.05 : baseR;

      const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
      g.setAttribute("data-agent-id", String(agent.id));

      if (isScan) {
        const ringR = r + 4 + scanProgress * 10;
        const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        ring.setAttribute("cx", String(x));
        ring.setAttribute("cy", String(y));
        ring.setAttribute("r", String(ringR));
        ring.setAttribute("fill", "none");
        ring.setAttribute("stroke", "#ab47bc");
        ring.setAttribute("stroke-width", "2.5");
        ring.setAttribute("opacity", String(0.35 + scanProgress * 0.55));
        g.appendChild(ring);

        const arcR = r + 2;
        const arc = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        arc.setAttribute("cx", String(x));
        arc.setAttribute("cy", String(y));
        arc.setAttribute("r", String(arcR));
        arc.setAttribute("fill", "none");
        arc.setAttribute("stroke", "#ffeb3b");
        arc.setAttribute("stroke-width", "3");
        arc.setAttribute(
          "stroke-dasharray",
          `${Math.max(1, scanProgress * 2 * Math.PI * arcR)} ${Math.max(1, 2 * Math.PI * arcR)}`
        );
        arc.setAttribute("transform", `rotate(-90 ${x} ${y})`);
        g.appendChild(arc);
      } else if (isQueue) {
        const halo = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        halo.setAttribute("cx", String(x));
        halo.setAttribute("cy", String(y));
        halo.setAttribute("r", String(r + 3));
        halo.setAttribute("fill", "none");
        halo.setAttribute("stroke", "#ffb74d");
        halo.setAttribute("stroke-width", "1.5");
        halo.setAttribute("stroke-dasharray", "3 2");
        halo.setAttribute("opacity", "0.9");
        g.appendChild(halo);
      }

      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", String(x));
      circle.setAttribute("cy", String(y));
      circle.setAttribute("r", String(r));
      circle.setAttribute("fill", STATE_COLORS[state] || "#e53935");
      circle.setAttribute("stroke", isScan ? "#fff" : isQueue ? "#ffe0b2" : "#fff");
      circle.setAttribute("stroke-width", isScan ? "2" : "1");
      g.appendChild(circle);

      if (isScan) {
        const check = document.createElementNS("http://www.w3.org/2000/svg", "text");
        check.setAttribute("x", String(x));
        check.setAttribute("y", String(y + 3));
        check.setAttribute("text-anchor", "middle");
        check.setAttribute("fill", "#5d4037");
        check.setAttribute("font-size", String(Math.max(6, r * 1.1)));
        check.setAttribute("font-weight", "700");
        check.textContent = scanProgress > 0.85 ? "✓" : "…";
        g.appendChild(check);
      }

      svg.appendChild(g);
    }
    const stage = document.getElementById("mapStage");
    if (simSvg && stage) stage.appendChild(simSvg);
    updateScannerFlash();
  }

  function updateSimStats() {
    const el = document.getElementById("simStats");
    if (!el) return;
    const s = simStats || {};
    const inQueue = simAgents.filter((a) => a.state === "in_queue" || a.state === "queuing").length;
    const scanning = simAgents.filter((a) => a.state === "scanning").length;
    const onPath = simAgents.filter((a) => a.state === "on_path" || a.state === "walking").length;
    let text = `Tick ${simTick} • spawned ${s.spawned || 0} • scanned ${s.scanned || 0} • path ${onPath} • queue ${inQueue} • scanning ${scanning}`;
    if (simPlaying) text += " • ▶ playing";
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
      if ((data.stats?.spawned || 0) > 0 || (data.spawn_remaining || 0) > 0) {
        simStart();
      }
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
    simScannerFlash = {};
    for (const item of data.scanner_activity || []) {
      if (item.gate_id) simScannerFlash[item.gate_id] = item;
    }
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
      simScannerFlash = {};
      updateScannerFlash();
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
