/* Beacon Crowd-Counting operator panel (/count).
 *
 * Talks to the Beacon API (same origin) for feed/region/line config and live
 * state, and to a separate crowd-counter inference service (configurable URL)
 * for on-screen density counts on browser-captured frames.
 *
 * Two counting capabilities are surfaced:
 *   - Density (on-screen headcount + heatmap): CSRNet via the inference service.
 *   - Line crossing (in/out ledger): needs a detector+tracker. Until that ships,
 *     crossings can be pushed manually (+in / +out) so the ledger is usable.
 */
(function () {
  "use strict";

  var REGION_COLORS = {
    zone: "rgba(88,166,255,0.28)",
    outside: "rgba(210,153,34,0.26)",
    exclude: "rgba(248,81,73,0.26)",
  };

  var state = {
    events: [],
    eventId: null,
    feeds: [],
    selectedFeedId: null,
    regions: [],
    lines: [],
    tool: "pan", // pan | region | line
    draft: null, // {type:'region', points:[{x,y}]} | {type:'line', points:[...]}
    media: { stream: null, kind: null, ready: false },
    inferUrl: localStorage.getItem("beaconInferUrl") || "http://127.0.0.1:8100",
    inferOnline: null,
    density: { running: false, timer: null, intervalMs: 3000, lastCells: [], lastCount: null, busy: false },
  };

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var el = function (tag, attrs, kids) {
    var node = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") node.className = attrs[k];
      else if (k === "html") node.innerHTML = attrs[k];
      else if (k.slice(0, 2) === "on") node.addEventListener(k.slice(2), attrs[k]);
      else node.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { node.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return node;
  };

  function api(path, opts) {
    opts = opts || {};
    return fetch(path, {
      headers: { "Content-Type": "application/json" },
      method: opts.method || "GET",
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    }).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error(t.slice(0, 200) || r.statusText); });
      return r.status === 204 ? null : r.json();
    });
  }

  function fmt(n) { return (n === null || n === undefined) ? "\u2014" : Number(n).toLocaleString(); }

  // ---------------------------------------------------------------- layout
  function boot() {
    var app = $("#app");
    app.innerHTML = "";
    app.appendChild(el("header", {}, [
      el("h1", {}, ["Beacon \u00b7 Crowd Counting"]),
      el("span", { class: "muted" }, ["Event"]),
      selectEvents(),
      el("span", { class: "spacer" }),
      el("span", { class: "muted", id: "inferStatus" }, ["inference: \u2026"]),
      el("button", { class: "ghost", onclick: openInferSettings }, ["Inference URL"]),
      el("a", { href: "/dash", class: "ghost", style: "text-decoration:none;padding:7px 9px;border:1px solid var(--line);border-radius:8px;" }, ["\u2190 Dash"]),
    ]));

    var main = el("div", { class: "main" }, [
      el("div", { class: "col left", id: "colLeft" }),
      el("div", { class: "col center", id: "colCenter" }, [
        el("div", { class: "toolbar", id: "toolbar" }),
        el("div", { class: "stage", id: "stage" }),
      ]),
      el("div", { class: "col right", id: "colRight" }),
    ]);
    app.appendChild(main);

    renderToolbar();
    renderStage();
    checkInference();
    loadEvents();
    window.addEventListener("resize", drawOverlay);
  }

  function selectEvents() {
    var sel = el("select", { id: "eventSel", style: "max-width:220px",
      onchange: function () { selectEvent(sel.value); } });
    return sel;
  }

  function loadEvents() {
    api("/events").then(function (evts) {
      state.events = evts || [];
      var sel = $("#eventSel");
      sel.innerHTML = "";
      state.events.forEach(function (e) {
        sel.appendChild(el("option", { value: e.id }, [e.name || e.id]));
      });
      var initial = localStorage.getItem("beaconCountEvent");
      if (initial && state.events.some(function (e) { return e.id === initial; })) sel.value = initial;
      if (state.events.length) selectEvent(sel.value || state.events[0].id);
      else renderLeft();
    }).catch(function () { renderLeft(); });
  }

  function selectEvent(id) {
    state.eventId = id;
    localStorage.setItem("beaconCountEvent", id);
    state.selectedFeedId = null;
    stopMedia();
    loadFeeds();
  }

  // ---------------------------------------------------------------- feeds
  function loadFeeds() {
    if (!state.eventId) return;
    api("/events/" + state.eventId + "/camera-feeds").then(function (feeds) {
      state.feeds = feeds || [];
      if (!state.selectedFeedId && state.feeds.length) selectFeed(state.feeds[0].id);
      else { renderLeft(); renderRight(); }
    }).catch(function () { state.feeds = []; renderLeft(); });
  }

  function selectFeed(feedId) {
    state.selectedFeedId = feedId;
    state.draft = null;
    stopDensity();
    stopMedia();
    Promise.all([
      api("/events/" + state.eventId + "/camera-feeds/" + feedId + "/regions").catch(function () { return []; }),
      api("/events/" + state.eventId + "/camera-feeds/" + feedId + "/lines").catch(function () { return []; }),
    ]).then(function (res) {
      state.regions = res[0] || [];
      state.lines = res[1] || [];
      renderLeft();
      renderStage();
      renderRight();
      startMedia();
    });
  }

  function currentFeed() {
    return state.feeds.filter(function (f) { return f.id === state.selectedFeedId; })[0] || null;
  }

  function renderLeft() {
    var c = $("#colLeft");
    c.innerHTML = "";
    c.appendChild(el("div", { class: "section-title" }, [
      el("span", {}, ["Camera feeds"]), el("span", { class: "spacer" }),
      el("button", { class: "primary", onclick: openAddFeed }, ["+ Add"]),
    ]));
    if (!state.eventId) { c.appendChild(el("p", { class: "hint" }, ["No event selected."])); return; }
    if (!state.feeds.length) {
      c.appendChild(el("p", { class: "hint" }, ["No feeds yet. Add a webcam, screen share, or IP camera to start counting."]));
      return;
    }
    state.feeds.forEach(function (f) {
      var sub = f.kind === "ip" ? (f.url || "") : (f.location_note || (f.kind + " feed"));
      c.appendChild(el("div", {
        class: "feed-item" + (f.id === state.selectedFeedId ? " active" : ""),
        onclick: function () { selectFeed(f.id); },
      }, [
        el("b", {}, [f.name]),
        el("div", { class: "sub" }, [
          el("span", { class: "pill " + f.kind }, [f.kind]),
          " " + (sub || ""),
        ]),
      ]));
    });
  }

  // ---------------------------------------------------------------- toolbar
  function renderToolbar() {
    var t = $("#toolbar");
    t.innerHTML = "";
    var tools = [
      { id: "pan", label: "Select" },
      { id: "region", label: "Draw zone" },
      { id: "line", label: "Draw line" },
    ];
    tools.forEach(function (tool) {
      t.appendChild(el("button", {
        class: state.tool === tool.id ? "active" : "",
        onclick: function () { setTool(tool.id); },
      }, [tool.label]));
    });
    t.appendChild(el("span", { class: "spacer" }));
    t.appendChild(el("span", { class: "hint", id: "drawHint" }, [drawHintText()]));
    t.appendChild(el("button", { class: "ghost", id: "finishBtn", onclick: finishDraft,
      style: state.draft ? "" : "display:none" }, ["Finish"]));
    t.appendChild(el("button", { class: "ghost", onclick: cancelDraft,
      style: state.draft ? "" : "display:none" }, ["Cancel"]));
  }

  function drawHintText() {
    if (state.tool === "region") return "Click to add points \u00b7 Finish to close the zone (min 3).";
    if (state.tool === "line") return "Click two points to place a threshold line.";
    return "Select a tool to draw zones or threshold lines on the feed.";
  }

  function setTool(id) {
    state.tool = id;
    state.draft = null;
    renderToolbar();
    drawOverlay();
  }

  // ---------------------------------------------------------------- stage / media
  function renderStage() {
    var stage = $("#stage");
    stage.innerHTML = "";
    var feed = currentFeed();
    if (!feed) {
      stage.appendChild(el("div", { class: "placeholder" }, [
        el("h2", {}, ["No feed selected"]),
        el("p", { class: "hint" }, ["Add and select a camera feed on the left. Then draw zones and threshold lines here, and run live density counting from the right panel."]),
      ]));
      return;
    }
    var box = el("div", { class: "media-box", id: "mediaBox" });
    if (feed.kind === "webcam" || feed.kind === "screen") {
      box.appendChild(el("video", { id: "media", autoplay: "", muted: "", playsinline: "" }));
    } else {
      box.appendChild(el("img", { id: "media", class: "feed", crossorigin: "anonymous", alt: feed.name }));
    }
    box.appendChild(el("canvas", { class: "overlay", id: "overlay" }));
    stage.appendChild(box);
    var canvas = $("#overlay");
    canvas.addEventListener("pointerdown", onCanvasPointer);
    canvas.addEventListener("pointermove", onCanvasHover);
  }

  function startMedia() {
    var feed = currentFeed();
    if (!feed) return;
    var media = $("#media");
    if (!media) return;
    if (feed.kind === "webcam" || feed.kind === "screen") {
      var getter = feed.kind === "screen"
        ? navigator.mediaDevices.getDisplayMedia({ video: true })
        : navigator.mediaDevices.getUserMedia({
            video: feed.device_id ? { deviceId: { exact: feed.device_id } } : true });
      getter.then(function (stream) {
        state.media.stream = stream;
        state.media.kind = feed.kind;
        media.srcObject = stream;
        media.onloadedmetadata = function () { media.play(); state.media.ready = true; drawOverlay(); };
      }).catch(function (e) {
        showStagePlaceholderError("Could not open " + feed.kind + ": " + e.message);
      });
    } else if (feed.kind === "ip") {
      // Snapshot/MJPEG. Refresh periodically to keep it live.
      media.onload = function () { state.media.ready = true; drawOverlay(); };
      media.onerror = function () { showStagePlaceholderError("Could not load IP camera. Browsers block RTSP and cross-origin frames; use an MJPEG/HTTP snapshot URL, or let the inference service pull the stream server-side."); };
      var refresh = function () {
        if (currentFeed() !== feed) return;
        var sep = feed.url.indexOf("?") >= 0 ? "&" : "?";
        media.src = feed.url + sep + "_t=" + Date.now();
        state.media._ipTimer = setTimeout(refresh, 1000);
      };
      refresh();
    } else if (feed.kind === "file") {
      // Prompt for a local still image to work with.
      var input = el("input", { type: "file", accept: "image/*", style: "display:none",
        onchange: function () {
          if (input.files && input.files[0]) {
            media.src = URL.createObjectURL(input.files[0]);
            media.onload = function () { state.media.ready = true; drawOverlay(); };
          }
        } });
      document.body.appendChild(input);
      input.click();
      setTimeout(function () { input.remove(); }, 60000);
    }
    drawOverlay();
  }

  function stopMedia() {
    if (state.media.stream) {
      state.media.stream.getTracks().forEach(function (t) { t.stop(); });
    }
    if (state.media._ipTimer) clearTimeout(state.media._ipTimer);
    state.media = { stream: null, kind: null, ready: false };
  }

  function showStagePlaceholderError(msg) {
    var stage = $("#stage");
    stage.innerHTML = "";
    stage.appendChild(el("div", { class: "placeholder" }, [
      el("h2", {}, ["Feed unavailable"]),
      el("p", { class: "hint" }, [msg]),
    ]));
  }

  // ---------------------------------------------------------------- drawing
  function canvasPoint(evt) {
    var canvas = $("#overlay");
    var r = canvas.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (evt.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (evt.clientY - r.top) / r.height)),
    };
  }

  function onCanvasPointer(evt) {
    if (state.tool === "pan") return;
    evt.preventDefault();
    var p = canvasPoint(evt);
    if (!state.draft) state.draft = { type: state.tool, points: [] };
    state.draft.points.push(p);
    if (state.tool === "line" && state.draft.points.length >= 2) { finishDraft(); return; }
    renderToolbar();
    drawOverlay();
  }

  function onCanvasHover(evt) {
    if (!state.draft) return;
    state.draft.hover = canvasPoint(evt);
    drawOverlay();
  }

  function cancelDraft() { state.draft = null; renderToolbar(); drawOverlay(); }

  function finishDraft() {
    var d = state.draft;
    if (!d) return;
    if (d.type === "region") {
      if (d.points.length < 3) { alert("A zone needs at least 3 points."); return; }
      var name = prompt("Zone name (e.g. \"Outside\", \"Zone 1\"):", "Zone " + (state.regions.length + 1));
      if (name === null) { cancelDraft(); return; }
      var role = "zone";
      var lower = name.trim().toLowerCase();
      if (lower.indexOf("outside") >= 0) role = "outside";
      api("/events/" + state.eventId + "/camera-feeds/" + state.selectedFeedId + "/regions", {
        method: "POST", body: { name: name.trim() || "Zone", role: role, polygon: d.points },
      }).then(function (reg) { state.regions.push(reg); state.draft = null; renderToolbar(); renderRight(); drawOverlay(); })
        .catch(function (e) { alert("Save failed: " + e.message); });
    } else if (d.type === "line") {
      if (d.points.length < 2) return;
      var lname = prompt("Threshold line name (e.g. \"Main gate\"):", "Threshold " + (state.lines.length + 1));
      if (lname === null) { cancelDraft(); return; }
      var a = d.points[0], b = d.points[1];
      api("/events/" + state.eventId + "/camera-feeds/" + state.selectedFeedId + "/lines", {
        method: "POST", body: { name: lname.trim() || "Threshold", ax: a.x, ay: a.y, bx: b.x, by: b.y },
      }).then(function (ln) { state.lines.push(ln); state.draft = null; renderToolbar(); renderRight(); drawOverlay(); })
        .catch(function (e) { alert("Save failed: " + e.message); });
    }
  }

  function drawOverlay() {
    var canvas = $("#overlay");
    if (!canvas) return;
    var w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    canvas.width = w; canvas.height = h;
    var ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, w, h);

    // Heatmap (density) under the geometry.
    if (state.density.lastCells && state.density.lastCells.length) {
      var maxW = 0;
      state.density.lastCells.forEach(function (c) { if (c.w > maxW) maxW = c.w; });
      maxW = maxW || 1;
      state.density.lastCells.forEach(function (c) {
        var alpha = Math.min(0.7, (c.w / maxW) * 0.7);
        var rad = Math.max(8, w * 0.018);
        var g = ctx.createRadialGradient(c.x * w, c.y * h, 0, c.x * w, c.y * h, rad);
        g.addColorStop(0, "rgba(255,90,40," + alpha + ")");
        g.addColorStop(1, "rgba(255,90,40,0)");
        ctx.fillStyle = g;
        ctx.fillRect(c.x * w - rad, c.y * h - rad, rad * 2, rad * 2);
      });
    }

    // Regions.
    state.regions.forEach(function (reg) {
      var poly = reg.polygon || [];
      if (poly.length < 2) return;
      ctx.beginPath();
      poly.forEach(function (p, i) { i ? ctx.lineTo(p.x * w, p.y * h) : ctx.moveTo(p.x * w, p.y * h); });
      ctx.closePath();
      ctx.fillStyle = reg.color || REGION_COLORS[reg.role] || REGION_COLORS.zone;
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.55)"; ctx.lineWidth = 1.5; ctx.stroke();
      var cx = poly.reduce(function (s, p) { return s + p.x; }, 0) / poly.length * w;
      var cy = poly.reduce(function (s, p) { return s + p.y; }, 0) / poly.length * h;
      label(ctx, reg.name, cx, cy);
    });

    // Tripwire lines.
    state.lines.forEach(function (ln) {
      drawLine(ctx, w, h, ln.ax, ln.ay, ln.bx, ln.by, "#58a6ff", ln.name + "  \u2191" + ln.cumulative_in + " \u2193" + ln.cumulative_out);
    });

    // Draft.
    if (state.draft) {
      var pts = state.draft.points.slice();
      if (state.draft.hover) pts = pts.concat([state.draft.hover]);
      if (state.draft.type === "region" && pts.length) {
        ctx.beginPath();
        pts.forEach(function (p, i) { i ? ctx.lineTo(p.x * w, p.y * h) : ctx.moveTo(p.x * w, p.y * h); });
        ctx.strokeStyle = "#3fb950"; ctx.lineWidth = 2; ctx.stroke();
        state.draft.points.forEach(function (p) { dot(ctx, p.x * w, p.y * h, "#3fb950"); });
      } else if (state.draft.type === "line" && pts.length) {
        if (pts.length >= 2) drawLine(ctx, w, h, pts[0].x, pts[0].y, pts[1].x, pts[1].y, "#3fb950", "");
        state.draft.points.forEach(function (p) { dot(ctx, p.x * w, p.y * h, "#3fb950"); });
      }
    }
  }

  function drawLine(ctx, w, h, ax, ay, bx, by, color, text) {
    ctx.beginPath();
    ctx.moveTo(ax * w, ay * h); ctx.lineTo(bx * w, by * h);
    ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.stroke();
    dot(ctx, ax * w, ay * h, color); dot(ctx, bx * w, by * h, color);
    // Direction arrow (normal pointing to "in" side).
    var mx = (ax + bx) / 2 * w, my = (ay + by) / 2 * h;
    var dx = (bx - ax) * w, dy = (by - ay) * h;
    var len = Math.hypot(dx, dy) || 1;
    var nx = -dy / len, ny = dx / len;
    ctx.beginPath(); ctx.moveTo(mx, my); ctx.lineTo(mx + nx * 22, my + ny * 22);
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();
    if (text) label(ctx, text, mx, my - 10);
  }

  function dot(ctx, x, y, color) {
    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
    ctx.strokeStyle = "#000"; ctx.lineWidth = 1; ctx.stroke();
  }

  function label(ctx, text, x, y) {
    ctx.font = "600 12px -apple-system, Segoe UI, sans-serif";
    var tw = ctx.measureText(text).width;
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(x - tw / 2 - 5, y - 16, tw + 10, 18);
    ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(text, x, y - 7);
    ctx.textAlign = "start";
  }

  // ---------------------------------------------------------------- right panel
  function renderRight() {
    var c = $("#colRight");
    c.innerHTML = "";
    var feed = currentFeed();

    // Density card.
    var dCard = el("div", { class: "card" });
    dCard.appendChild(el("div", { class: "stat" }, [
      el("span", { class: "label" }, ["On-screen (density)"]),
      el("span", { class: "badge " + (state.density.running ? "ok" : "off") }, [state.density.running ? "live" : "idle"]),
    ]));
    dCard.appendChild(el("div", { class: "big", id: "densCount" }, [fmt(state.density.lastCount)]));
    dCard.appendChild(el("div", { class: "row" }, [
      el("button", {
        class: state.density.running ? "warn" : "good",
        disabled: feed ? null : "",
        onclick: toggleDensity, id: "densBtn", style: "flex:1",
      }, [state.density.running ? "Stop counting" : "Run density counting"]),
    ]));
    dCard.appendChild(el("div", { class: "hint", style: "margin-top:6px" }, [
      "Captures a frame every 3s, runs CSRNet on the inference service, and stores the headcount + heatmap on this feed.",
    ]));
    c.appendChild(dCard);

    // Occupancy ledger card (from tripwire lines).
    var oCard = el("div", { class: "card" });
    var totIn = state.lines.reduce(function (s, l) { return s + (l.cumulative_in || 0); }, 0);
    var totOut = state.lines.reduce(function (s, l) { return s + (l.cumulative_out || 0); }, 0);
    oCard.appendChild(el("div", { class: "stat" }, [
      el("span", { class: "label" }, ["Occupancy (line ledger)"]),
    ]));
    oCard.appendChild(el("div", { class: "big" }, [fmt(totIn - totOut)]));
    oCard.appendChild(el("div", { class: "row" }, [el("span", {}, ["In"]), el("span", {}, [fmt(totIn)])]));
    oCard.appendChild(el("div", { class: "row" }, [el("span", {}, ["Out"]), el("span", {}, [fmt(totOut)])]));
    c.appendChild(oCard);

    // Per-line controls.
    c.appendChild(el("div", { class: "section-title" }, [el("span", {}, ["Threshold lines"])]));
    if (!state.lines.length) {
      c.appendChild(el("p", { class: "hint" }, ["No lines yet. Use \u201cDraw line\u201d to place a threshold across an entrance."]));
    }
    state.lines.forEach(function (ln) {
      var row = el("div", { class: "line-row" });
      row.appendChild(el("div", { class: "stat" }, [
        el("b", {}, [ln.name]),
        el("span", { class: "line-net" }, [fmt(ln.cumulative_in - ln.cumulative_out)]),
      ]));
      row.appendChild(el("div", { class: "row" }, [
        el("span", {}, ["\u2191 in " + ln.cumulative_in]),
        el("span", {}, ["\u2193 out " + ln.cumulative_out]),
      ]));
      row.appendChild(el("div", { class: "ctr" }, [
        el("button", { class: "good", onclick: function () { pushCrossing(ln, "in"); } }, ["+ In"]),
        el("button", { class: "warn", onclick: function () { pushCrossing(ln, "out"); } }, ["+ Out"]),
        el("button", { class: "ghost", onclick: function () { resetLine(ln); } }, ["Reset"]),
        el("button", { class: "danger ghost", onclick: function () { deleteLine(ln); } }, ["\u2715"]),
      ]));
      c.appendChild(row);
    });

    // Regions list.
    c.appendChild(el("div", { class: "section-title" }, [el("span", {}, ["Zones"])]));
    if (!state.regions.length) {
      c.appendChild(el("p", { class: "hint" }, ["No zones. Use \u201cDraw zone\u201d to label areas (e.g. Outside, Zone 1) or exclude regions from counting."]));
    }
    state.regions.forEach(function (reg) {
      c.appendChild(el("div", { class: "line-row" }, [
        el("div", { class: "stat" }, [
          el("b", {}, [reg.name]),
          el("span", { class: "pill" }, [reg.role]),
        ]),
        el("div", { class: "ctr" }, [
          el("button", { class: "danger ghost", onclick: function () { deleteRegion(reg); } }, ["Delete"]),
        ]),
      ]));
    });

    if (feed) {
      c.appendChild(el("div", { style: "margin-top:12px" }, [
        el("button", { class: "danger ghost", style: "width:100%", onclick: function () { deleteFeed(feed); } }, ["Delete this feed"]),
      ]));
    }
  }

  // ---------------------------------------------------------------- crossings/lines
  function pushCrossing(ln, dir) {
    api("/events/" + state.eventId + "/camera-feeds/" + state.selectedFeedId + "/lines/" + ln.id + "/crossings", {
      method: "POST", body: { direction: dir, track_id: "manual" },
    }).then(function (res) {
      Object.assign(ln, res.line);
      renderRight(); drawOverlay();
    }).catch(function (e) { alert("Failed: " + e.message); });
  }

  function resetLine(ln) {
    api("/events/" + state.eventId + "/camera-feeds/" + state.selectedFeedId + "/lines/" + ln.id + "/reset", { method: "POST" })
      .then(function (row) { Object.assign(ln, row); renderRight(); drawOverlay(); });
  }

  function deleteLine(ln) {
    if (!confirm("Delete line \"" + ln.name + "\"?")) return;
    api("/events/" + state.eventId + "/camera-feeds/" + state.selectedFeedId + "/lines/" + ln.id, { method: "DELETE" })
      .then(function () { state.lines = state.lines.filter(function (x) { return x.id !== ln.id; }); renderRight(); drawOverlay(); });
  }

  function deleteRegion(reg) {
    if (!confirm("Delete zone \"" + reg.name + "\"?")) return;
    api("/events/" + state.eventId + "/camera-feeds/" + state.selectedFeedId + "/regions/" + reg.id, { method: "DELETE" })
      .then(function () { state.regions = state.regions.filter(function (x) { return x.id !== reg.id; }); renderRight(); drawOverlay(); });
  }

  function deleteFeed(feed) {
    if (!confirm("Delete feed \"" + feed.name + "\" and its zones/lines?")) return;
    api("/events/" + state.eventId + "/camera-feeds/" + feed.id, { method: "DELETE" }).then(function () {
      state.feeds = state.feeds.filter(function (f) { return f.id !== feed.id; });
      state.selectedFeedId = null; stopMedia(); stopDensity();
      state.regions = []; state.lines = [];
      if (state.feeds.length) selectFeed(state.feeds[0].id);
      else { renderLeft(); renderStage(); renderRight(); }
    });
  }

  // ---------------------------------------------------------------- density inference
  function toggleDensity() { state.density.running ? stopDensity() : startDensity(); }

  function startDensity() {
    if (!currentFeed()) return;
    state.density.running = true;
    renderRight();
    var loop = function () {
      captureAndInfer().finally(function () {
        if (state.density.running) state.density.timer = setTimeout(loop, state.density.intervalMs);
      });
    };
    loop();
  }

  function stopDensity() {
    state.density.running = false;
    if (state.density.timer) clearTimeout(state.density.timer);
    state.density.timer = null;
    var btn = $("#densBtn"); if (btn) { btn.textContent = "Run density counting"; btn.className = "good"; }
  }

  function grabFrame() {
    var media = $("#media");
    if (!media) return null;
    var vw = media.videoWidth || media.naturalWidth;
    var vh = media.videoHeight || media.naturalHeight;
    if (!vw || !vh) return null;
    var maxDim = 1280, scale = Math.min(1, maxDim / Math.max(vw, vh));
    var cw = Math.round(vw * scale), ch = Math.round(vh * scale);
    var cv = document.createElement("canvas"); cv.width = cw; cv.height = ch;
    try { cv.getContext("2d").drawImage(media, 0, 0, cw, ch); } catch (e) { return null; }
    return cv;
  }

  function captureAndInfer() {
    if (state.density.busy) return Promise.resolve();
    var cv = grabFrame();
    if (!cv) return Promise.resolve();
    state.density.busy = true;
    return new Promise(function (resolve) {
      cv.toBlob(function (blob) {
        if (!blob) { state.density.busy = false; return resolve(); }
        var fd = new FormData();
        fd.append("image", blob, "frame.jpg");
        fetch(state.inferUrl.replace(/\/$/, "") + "/infer/density", { method: "POST", body: fd })
          .then(function (r) { if (!r.ok) throw new Error("infer " + r.status); return r.json(); })
          .then(function (res) {
            state.density.lastCount = res.count;
            state.density.lastCells = res.cells || [];
            var dc = $("#densCount"); if (dc) dc.textContent = fmt(res.count);
            drawOverlay();
            // Persist to Beacon for the dashboard/history.
            return api("/events/" + state.eventId + "/camera-feeds/" + state.selectedFeedId + "/density", {
              method: "PUT", body: { heads: res.count, cells: res.cells || [], confidence: res.confidence },
            }).catch(function () {});
          })
          .catch(function (e) {
            setInferStatus(false, e.message);
            stopDensity();
            alert("Inference service unreachable at " + state.inferUrl + ".\n\nStart it in the crowd-counter folder:\n  python server.py --weights csrnet.pth\n\n(" + e.message + ")");
          })
          .finally(function () { state.density.busy = false; resolve(); });
      }, "image/jpeg", 0.85);
    });
  }

  // ---------------------------------------------------------------- inference status + settings
  function checkInference() {
    fetch(state.inferUrl.replace(/\/$/, "") + "/health").then(function (r) {
      setInferStatus(r.ok, r.ok ? "" : "http " + r.status);
    }).catch(function () { setInferStatus(false, "offline"); });
  }

  function setInferStatus(online, msg) {
    state.inferOnline = online;
    var s = $("#inferStatus");
    if (s) s.innerHTML = '<span class="status-dot ' + (online ? "on" : "off") + '"></span>inference ' +
      (online ? "online" : "offline" + (msg ? " (" + msg + ")" : ""));
  }

  function openInferSettings() {
    modal("Inference service URL", [
      el("label", { class: "field" }, ["Crowd-counter server URL"]),
      el("input", { id: "inferInput", value: state.inferUrl, placeholder: "http://127.0.0.1:8100" }),
      el("p", { class: "hint" }, ["This is the crowd-counter HTTP service (server.py). It runs CSRNet on frames this panel captures. It can run on this PC or a GPU box on your network."]),
    ], function () {
      var v = $("#inferInput").value.trim();
      if (v) { state.inferUrl = v; localStorage.setItem("beaconInferUrl", v); checkInference(); }
    });
  }

  // ---------------------------------------------------------------- add feed modal
  function openAddFeed() {
    if (!state.eventId) { alert("Select an event first."); return; }
    var kindSel = el("select", { id: "afKind", onchange: onKindChange }, [
      el("option", { value: "webcam" }, ["Local webcam"]),
      el("option", { value: "screen" }, ["Screen / window share"]),
      el("option", { value: "ip" }, ["IP camera (MJPEG/HTTP snapshot)"]),
      el("option", { value: "file" }, ["Still image file"]),
    ]);
    var body = [
      el("label", { class: "field" }, ["Name"]),
      el("input", { id: "afName", value: "Camera " + (state.feeds.length + 1) }),
      el("label", { class: "field" }, ["Type"]),
      kindSel,
      el("div", { id: "afExtra" }),
      el("label", { class: "field" }, ["Location note (optional)"]),
      el("input", { id: "afNote", placeholder: "North entrance, overhead" }),
    ];
    modal("Add camera feed", body, saveNewFeed);
    onKindChange();
  }

  function onKindChange() {
    var kind = $("#afKind").value;
    var extra = $("#afExtra");
    extra.innerHTML = "";
    if (kind === "ip") {
      extra.appendChild(el("label", { class: "field" }, ["Stream URL"]));
      extra.appendChild(el("input", { id: "afUrl", placeholder: "http://192.168.1.50:8080/video or /snapshot.jpg" }));
      extra.appendChild(el("p", { class: "hint" }, ["Browsers can't open RTSP. Use an MJPEG or JPEG-snapshot HTTP URL here, or point the inference service at the RTSP stream directly (server-side pull)."]));
    } else if (kind === "webcam") {
      var sel = el("select", { id: "afDevice" }, [el("option", { value: "" }, ["Default / ask each time"])]);
      extra.appendChild(el("label", { class: "field" }, ["Device"]));
      extra.appendChild(sel);
      // Enumerate after a permission prompt so labels are populated.
      navigator.mediaDevices.getUserMedia({ video: true }).then(function (stream) {
        stream.getTracks().forEach(function (t) { t.stop(); });
        return navigator.mediaDevices.enumerateDevices();
      }).then(function (devices) {
        devices.filter(function (d) { return d.kind === "videoinput"; }).forEach(function (d) {
          sel.appendChild(el("option", { value: d.deviceId }, [d.label || ("Camera " + d.deviceId.slice(0, 6))]));
        });
      }).catch(function () {});
    }
  }

  function saveNewFeed() {
    var kind = $("#afKind").value;
    var payload = {
      name: $("#afName").value.trim() || "Camera",
      kind: kind,
      location_note: $("#afNote").value.trim() || null,
    };
    if (kind === "ip") payload.url = ($("#afUrl") ? $("#afUrl").value.trim() : "");
    if (kind === "webcam" && $("#afDevice")) payload.device_id = $("#afDevice").value || null;
    return api("/events/" + state.eventId + "/camera-feeds", { method: "POST", body: payload })
      .then(function (feed) { state.feeds.push(feed); renderLeft(); selectFeed(feed.id); })
      .catch(function (e) { alert("Could not add feed: " + e.message); throw e; });
  }

  // ---------------------------------------------------------------- modal helper
  function modal(title, bodyNodes, onSave) {
    var back = el("div", { class: "modal-back", onclick: function (e) { if (e.target === back) close(); } });
    function close() { back.remove(); }
    var box = el("div", { class: "modal" }, [el("h3", {}, [title])]);
    var form = el("div", { class: "stack" }, bodyNodes);
    box.appendChild(form);
    box.appendChild(el("div", { class: "actions" }, [
      el("button", { class: "ghost", onclick: close }, ["Cancel"]),
      el("button", { class: "primary", onclick: function () {
        var res = onSave && onSave();
        if (res && res.then) res.then(close).catch(function () {}); else close();
      } }, ["Save"]),
    ]));
    back.appendChild(box);
    document.body.appendChild(back);
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
