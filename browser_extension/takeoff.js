// Open in QuantiSheet: takeoff in the add-on's viewer (Jon, Nov 27,
// option B): set a scale, click out lengths, areas and counts.
//
// What is drawn here is a working picture. The numbers shown are a
// preview. Nothing is written into the PDF: Open in QuantiSheet sends
// where the clicks were and the scale that was set, and QuantiSheet works
// the quantities out itself (app/webmarks.py), so a quantity only ever
// comes from one place.
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const COLORS = { length: "#d91a1a", area: "#1a73d9", count: "#e68000" };
  const INCH = 72;                       // PDF points to the inch
  const PER_M = INCH / 0.0254;           // PDF points to the metre
  // name, points per unit, unit
  const PRESETS = [
    ['1/16" = 1\'-0"', INCH / 16, "ft"], ['3/32" = 1\'-0"', INCH * 3 / 32, "ft"],
    ['1/8" = 1\'-0"', INCH / 8, "ft"], ['3/16" = 1\'-0"', INCH * 3 / 16, "ft"],
    ['1/4" = 1\'-0"', INCH / 4, "ft"], ['3/8" = 1\'-0"', INCH * 3 / 8, "ft"],
    ['1/2" = 1\'-0"', INCH / 2, "ft"], ['3/4" = 1\'-0"', INCH * 3 / 4, "ft"],
    ['1" = 1\'-0"', INCH, "ft"], ['1 1/2" = 1\'-0"', INCH * 1.5, "ft"],
    ['3" = 1\'-0"', INCH * 3, "ft"],
    ['1" = 10\'', INCH / 10, "ft"], ['1" = 20\'', INCH / 20, "ft"],
    ['1" = 30\'', INCH / 30, "ft"], ['1" = 40\'', INCH / 40, "ft"],
    ['1" = 50\'', INCH / 50, "ft"], ['1" = 60\'', INCH / 60, "ft"],
    ['1" = 100\'', INCH / 100, "ft"],
    ["1:50", PER_M / 50, "m"], ["1:100", PER_M / 100, "m"],
    ["1:200", PER_M / 200, "m"], ["1:500", PER_M / 500, "m"]
  ];
  const UNITS = ["ft", "in", "yd", "m", "cm", "mm"];

  const state = {
    scales: {},          // page (from 0) -> { ppu, unit, name }
    everyPage: null,     // a scale set for all pages, or null
    marks: [],           // { page, type, pts: [[x, y]...], group } PDF coords
    tool: null,          // "length" | "area" | "count" | "calibrate" | null
    now: null            // the measurement being clicked out
  };
  let app = null;
  let panel = null;
  const KEY = "qs-takeoff:" +
    (typeof location !== "undefined" ? location.search : "");

  // ---- the arithmetic (also used by the tests) --------------------------
  function pathLength(pts) {
    let d = 0;
    for (let i = 1; i < pts.length; i++) {
      d += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    }
    return d;
  }

  function polygonArea(pts) {
    let s = 0;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], b = pts[(i + 1) % pts.length];
      s += a[0] * b[1] - b[0] * a[1];
    }
    return Math.abs(s) / 2;
  }

  function scaleFor(page) {
    return state.scales[page] || state.everyPage || null;
  }

  // A preview only: QuantiSheet's own figure is the one that counts.
  function preview(mark) {
    if (mark.type === "count") return "";
    const sc = scaleFor(mark.page);
    if (!sc) return "no scale";
    if (mark.type === "length") {
      return (pathLength(mark.pts) / sc.ppu).toFixed(2) + " " + sc.unit;
    }
    return (polygonArea(mark.pts) / (sc.ppu * sc.ppu)).toFixed(2) +
      " sq " + sc.unit;
  }

  function totals() {
    const rows = new Map();
    for (const m of state.marks) {
      const sc = scaleFor(m.page);
      const unit = m.type === "count" ? "ea"
        : !sc ? "?" : m.type === "length" ? sc.unit : "sq " + sc.unit;
      const key = m.type + "|" + (m.group || "") + "|" + unit;
      const v = m.type === "count" ? 1 : !sc ? 0
        : m.type === "length" ? pathLength(m.pts) / sc.ppu
          : polygonArea(m.pts) / (sc.ppu * sc.ppu);
      const row = rows.get(key) || { type: m.type, group: m.group || "",
                                     unit, value: 0, n: 0 };
      row.value += v;
      row.n += 1;
      rows.set(key, row);
    }
    return [...rows.values()];
  }

  // What goes to QuantiSheet: clicks and scales, never a quantity.
  function data() {
    const scales = [];
    if (state.everyPage) {
      scales.push(Object.assign({ page: 0, all: true }, state.everyPage));
    }
    for (const [page, sc] of Object.entries(state.scales)) {
      scales.push(Object.assign({ page: Number(page), all: false }, sc));
    }
    return {
      v: 1, scales,
      marks: state.marks.map((m) => ({
        page: m.page, type: m.type, group: m.group || "",
        pts: m.pts.map((p) => [p[0], p[1]])
      }))
    };
  }

  function keep() {
    try {
      sessionStorage.setItem(KEY, JSON.stringify({
        scales: state.scales, everyPage: state.everyPage, marks: state.marks
      }));
    } catch (e) { /* private window: kept for this page only */ }
  }

  function restore() {
    try {
      const got = JSON.parse(sessionStorage.getItem(KEY) || "null");
      if (!got) return;
      state.scales = got.scales || {};
      state.everyPage = got.everyPage || null;
      state.marks = Array.isArray(got.marks) ? got.marks : [];
    } catch (e) { /* nothing kept */ }
  }

  // ---- drawing ----------------------------------------------------------
  function view(page) {
    return app.pdfViewer.getPageView(page);
  }

  function overlay(page) {
    const pv = view(page);
    if (!pv || !pv.div || !pv.viewport) return null;
    let svg = pv.div.querySelector("svg.qsTakeoff");
    if (!svg) {
      svg = document.createElementNS(NS, "svg");
      svg.setAttribute("class", "qsTakeoff");
      svg.style.cssText = "position:absolute;left:0;top:0;width:100%;" +
        "height:100%;z-index:50;overflow:visible";
      svg.addEventListener("click", (e) => onClick(e, page, svg));
      svg.addEventListener("dblclick", (e) => {
        e.preventDefault();
        finish();
      });
      svg.addEventListener("mousemove", (e) => onMove(e, page, svg));
      pv.div.appendChild(svg);
    }
    svg.style.pointerEvents = state.tool ? "auto" : "none";
    svg.style.cursor = state.tool ? "crosshair" : "";
    return svg;
  }

  function toScreen(page, pt) {
    return view(page).viewport.convertToViewportPoint(pt[0], pt[1]);
  }

  function toPdf(page, svg, e) {
    const r = svg.getBoundingClientRect();
    return view(page).viewport.convertToPdfPoint(e.clientX - r.left,
                                                 e.clientY - r.top);
  }

  function el(name, attrs, text) {
    const n = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function label(svg, at, text, color) {
    if (!text) return;
    const t = el("text", {
      x: at[0] + 6, y: at[1] - 6, fill: color, "font-size": 13,
      "font-family": "system-ui, sans-serif", "font-weight": 600,
      stroke: "#fff", "stroke-width": 3, "paint-order": "stroke"
    }, text);
    svg.appendChild(t);
  }

  function drawMark(svg, m, live) {
    const pts = m.pts.map((p) => toScreen(m.page, p));
    const color = COLORS[m.type] || "#333";
    if (m.type === "count") {
      const [x, y] = pts[0];
      svg.appendChild(el("circle", { cx: x, cy: y, r: 9, fill: color,
                                     "fill-opacity": 0.75, stroke: color }));
      svg.appendChild(el("text", {
        x, y: y + 4, "text-anchor": "middle", "font-size": 11,
        "font-family": "system-ui, sans-serif", "font-weight": 700
      }, String(m.n || "")));
      return;
    }
    const d = pts.map((p) => p.join(",")).join(" ");
    if (m.type === "area" && pts.length > 2) {
      svg.appendChild(el("polygon", { points: d, fill: color,
                                      "fill-opacity": live ? 0.2 : 0.35,
                                      stroke: color, "stroke-width": 2 }));
    } else {
      svg.appendChild(el("polyline", {
        points: d, fill: "none", stroke: color, "stroke-width": 3.5,
        "stroke-opacity": 0.75, "stroke-linecap": "round",
        "stroke-dasharray": m.type === "calibrate" ? "6 4" : ""
      }));
    }
    for (const p of pts) {
      svg.appendChild(el("circle", { cx: p[0], cy: p[1], r: 3,
                                     fill: "#fff", stroke: color }));
    }
    if (m.type !== "calibrate") {
      label(svg, pts[pts.length - 1],
            (m.group ? m.group + ": " : "") + preview(m), color);
    }
  }

  function draw(page) {
    const svg = overlay(page);
    if (!svg) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const n = {};
    for (const m of state.marks) {
      if (m.type === "count") {
        const key = m.page + "|" + (m.group || "");
        n[key] = (n[key] || 0) + 1;
        m.n = n[key];
      }
      if (m.page === page) drawMark(svg, m, false);
    }
    if (state.now && state.now.page === page && state.now.pts.length) {
      const live = Object.assign({}, state.now);
      if (state.hover && state.hover.page === page) {
        live.pts = live.pts.concat([state.hover.pt]);
      }
      drawMark(svg, live, true);
    }
  }

  function drawAll() {
    if (!app || !app.pdfViewer) return;
    for (let p = 0; p < app.pagesCount; p++) {
      const pv = view(p);
      if (pv && pv.div && pv.viewport && pv.renderingState !== 0) draw(p);
      else if (pv && pv.div && pv.div.querySelector("svg.qsTakeoff")) draw(p);
    }
    showPanel();
  }

  // ---- clicking ---------------------------------------------------------
  function group() {
    const g = panel && panel.querySelector("#qsGroup");
    return g ? g.value.trim().slice(0, 60) : "";
  }

  function onClick(e, page, svg) {
    if (!state.tool) return;
    e.preventDefault();
    e.stopPropagation();
    const pt = toPdf(page, svg, e);
    if (state.tool === "count") {
      state.marks.push({ page, type: "count", pts: [pt], group: group() });
      changed();
      return;
    }
    if (!state.now || state.now.page !== page) {
      state.now = { page, type: state.tool, pts: [], group: group() };
    }
    if (e.detail > 1) return;            // the second click of a double
    state.now.pts.push(pt);
    if (state.tool === "calibrate" && state.now.pts.length === 2) {
      askCalibration();
      return;
    }
    draw(page);
    hint();
  }

  function onMove(e, page, svg) {
    if (!state.now || state.now.page !== page) return;
    state.hover = { page, pt: toPdf(page, svg, e) };
    draw(page);
  }

  function finish() {
    const now = state.now;
    state.now = null;
    state.hover = null;
    if (!now) return;
    const need = now.type === "area" ? 3 : 2;
    if (now.type !== "calibrate" && now.pts.length >= need) {
      state.marks.push(now);
      changed();
    } else {
      draw(now.page);
    }
    hint();
  }

  function cancel() {
    const page = state.now && state.now.page;
    state.now = null;
    state.hover = null;
    if (page !== null && page !== undefined) draw(page);
    hint();
  }

  function changed() {
    keep();
    drawAll();
  }

  function setTool(tool) {
    finish();
    state.tool = state.tool === tool ? null : tool;
    drawAll();
    hint();
  }

  // ---- scale ------------------------------------------------------------
  function setScale(page, sc, every) {
    if (every) {
      state.everyPage = sc;
      state.scales = {};
    } else {
      state.scales[page] = sc;
    }
    changed();
  }

  function askCalibration() {
    const now = state.now;
    const box = panel.querySelector("#qsCal");
    box.hidden = false;
    panel.querySelector("#qsCalLen").focus();
    panel.querySelector("#qsCalOk").onclick = () => {
      const real = parseFloat(panel.querySelector("#qsCalLen").value);
      const unit = panel.querySelector("#qsCalUnit").value;
      const dist = pathLength(now.pts);
      if (!(real > 0) || !(dist > 0) || !UNITS.includes(unit)) {
        say("Type the real length of the line you clicked, for example " +
            "20.");
        return;
      }
      box.hidden = true;
      state.now = null;
      state.tool = null;
      setScale(now.page, { ppu: dist / real, unit,
                           name: real + " " + unit + " by two points" },
               panel.querySelector("#qsEvery").checked);
      say("Scale set from the two points.");
    };
  }

  // ---- the panel --------------------------------------------------------
  function say(text) {
    const n = panel && panel.querySelector("#qsHint");
    if (n) n.textContent = text;
  }

  function hint() {
    const t = state.tool;
    say(t === "length" ? "Click along the run. Double-click (or Enter) to " +
      "finish. Esc cancels."
      : t === "area" ? "Click each corner. Double-click (or Enter) to " +
        "finish. Esc cancels."
        : t === "count" ? "Click each one. Click Count again when done."
          : t === "calibrate" ? "Click the two ends of a known dimension."
            : "Numbers here are a preview. QuantiSheet works out the " +
              "quantities when you press Open in QuantiSheet.");
    if (!panel) return;
    for (const b of panel.querySelectorAll("button[data-tool]")) {
      b.style.background = b.dataset.tool === t ? "#0e6a60" : "";
      b.style.color = b.dataset.tool === t ? "#fff" : "";
    }
  }

  function showPanel() {
    if (!panel) return;
    const page = (app.page || 1) - 1;
    const sc = scaleFor(page);
    panel.querySelector("#qsScaleNow").textContent = sc
      ? "Page " + (page + 1) + " scale: " + sc.name
      : "Page " + (page + 1) + ": no scale set";
    const list = panel.querySelector("#qsTotals");
    list.textContent = "";
    for (const r of totals()) {
      const li = document.createElement("div");
      const what = r.type === "count" ? r.n + " ea"
        : r.unit.startsWith("?") ? r.n + " without a scale"
          : r.value.toFixed(2) + " " + r.unit;
      li.textContent = (r.group || "(no name)") + " - " +
        r.type + ": " + what;
      list.appendChild(li);
    }
    if (!state.marks.length) list.textContent = "Nothing measured yet.";
  }

  function build() {
    panel = document.createElement("div");
    panel.id = "qsTakeoffPanel";
    panel.hidden = true;
    panel.style.cssText = "position:fixed;right:12px;top:44px;" +
      "z-index:100000;width:290px;padding:10px 12px;border-radius:8px;" +
      "background:#fff;color:#1d2b29;font:13px system-ui,sans-serif;" +
      "box-shadow:0 2px 14px rgba(0,0,0,.35);border:1px solid #cfd8d6";
    const btn = "padding:5px 9px;margin:2px 3px 2px 0;border:1px solid " +
      "#9fb1ae;border-radius:5px;background:#f3f6f5;cursor:pointer;" +
      "font:600 12px system-ui,sans-serif";
    const opts = PRESETS.map((p, i) => "<option value='" + i + "'></option>")
      .join("");
    panel.innerHTML =
      "<div id='qsGrip' title='Drag to move' style='font-weight:700;" +
      "margin-bottom:4px;cursor:move;user-select:none'>Takeoff " +
      "<span style='font-weight:400;color:#7a8a87'>(drag to move)</span>" +
      "</div>" +
      "<div id='qsScaleNow' style='margin-bottom:4px'></div>" +
      "<select id='qsPreset' style='max-width:150px'>" +
      "<option value=''>Set scale...</option>" + opts + "</select> " +
      "<button data-tool='calibrate' style=\"" + btn + "\">By two points" +
      "</button>" +
      "<label style='display:block;margin:3px 0'><input type='checkbox' " +
      "id='qsEvery'> for every page</label>" +
      "<div id='qsCal' hidden style='margin:4px 0'>Real length: " +
      "<input id='qsCalLen' size='6'> <select id='qsCalUnit'></select> " +
      "<button id='qsCalOk' style=\"" + btn + "\">Set</button></div>" +
      "<div style='margin-top:6px'>Name: <input id='qsGroup' size='18' " +
      "maxlength='60' placeholder='Walls, Doors...'></div>" +
      "<div style='margin-top:4px'>" +
      "<button data-tool='length' style=\"" + btn + "\">Length</button>" +
      "<button data-tool='area' style=\"" + btn + "\">Area</button>" +
      "<button data-tool='count' style=\"" + btn + "\">Count</button>" +
      "<button id='qsUndo' style=\"" + btn + "\">Undo</button>" +
      "<button id='qsClear' style=\"" + btn + "\">Clear</button></div>" +
      "<div id='qsTotals' style='margin-top:6px;max-height:120px;" +
      "overflow:auto;border-top:1px solid #e0e6e5;padding-top:4px'></div>" +
      "<div id='qsHint' style='margin-top:6px;color:#4d5f5c'></div>";
    document.body.appendChild(panel);
    // the panel sits over the drawing, so it can be dragged out of the way
    const grip = panel.querySelector("#qsGrip");
    grip.addEventListener("mousedown", (e) => {
      const r = panel.getBoundingClientRect();
      const dx = e.clientX - r.left, dy = e.clientY - r.top;
      const move = (m) => {
        panel.style.right = "auto";
        panel.style.left = Math.max(0, Math.min(
          window.innerWidth - 60, m.clientX - dx)) + "px";
        panel.style.top = Math.max(0, Math.min(
          window.innerHeight - 30, m.clientY - dy)) + "px";
      };
      const up = () => {
        document.removeEventListener("mousemove", move, true);
        document.removeEventListener("mouseup", up, true);
      };
      document.addEventListener("mousemove", move, true);
      document.addEventListener("mouseup", up, true);
      e.preventDefault();
    });
    const sel = panel.querySelector("#qsPreset");
    PRESETS.forEach((p, i) => { sel.options[i + 1].textContent = p[0]; });
    const cu = panel.querySelector("#qsCalUnit");
    for (const u of UNITS) {
      const o = document.createElement("option");
      o.value = o.textContent = u;
      cu.appendChild(o);
    }
    sel.addEventListener("change", () => {
      const p = PRESETS[Number(sel.value)];
      if (sel.value === "" || !p) return;
      setScale((app.page || 1) - 1, { ppu: p[1], unit: p[2], name: p[0] },
               panel.querySelector("#qsEvery").checked);
      sel.value = "";
      say("Scale set: " + p[0] + ".");
    });
    for (const b of panel.querySelectorAll("button[data-tool]")) {
      b.addEventListener("click", () => setTool(b.dataset.tool));
    }
    panel.querySelector("#qsUndo").addEventListener("click", () => {
      if (state.now && state.now.pts.length) state.now.pts.pop();
      else state.marks.pop();
      changed();
    });
    let sure = 0;
    panel.querySelector("#qsClear").addEventListener("click", (e) => {
      // no pop-up boxes in an add-on page: a second click confirms
      if (Date.now() - sure > 4000) {
        sure = Date.now();
        e.target.textContent = "Clear all?";
        setTimeout(() => { e.target.textContent = "Clear"; }, 4000);
        return;
      }
      state.marks = [];
      state.now = null;
      e.target.textContent = "Clear";
      changed();
    });
    hint();
  }

  function toolbarButton() {
    const right = document.getElementById("toolbarViewerRight");
    if (!right || document.getElementById("qsTakeoffBtn")) return;
    const b = document.createElement("button");
    b.id = "qsTakeoffBtn";
    b.type = "button";
    b.textContent = "Takeoff";
    b.title = "Set a scale and measure lengths, areas and counts";
    b.style.cssText = "margin:0 2px;padding:0 10px;height:28px;border:1px " +
      "solid #0e6a60;border-radius:4px;background:#fff;color:#0e6a60;" +
      "font:600 13px system-ui,sans-serif;cursor:pointer;white-space:nowrap";
    b.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      if (panel.hidden) setTool(null);
      showPanel();
    });
    const open = document.getElementById("qsOpen");
    right.insertBefore(b, open ? open.nextSibling : right.firstChild);
  }

  function start() {
    app = window.PDFViewerApplication;
    restore();
    build();
    toolbarButton();
    app.eventBus.on("pagerendered", (e) => draw(e.pageNumber - 1));
    app.eventBus.on("pagechanging", showPanel);
    app.eventBus.on("pagesloaded", drawAll);
    document.addEventListener("keydown", (e) => {
      if (!state.tool) return;
      if (e.key === "Escape") cancel();
      else if (e.key === "Enter") finish();
    }, true);
    if (state.marks.length) panel.hidden = false;
    showPanel();
  }

  if (typeof module !== "undefined") {          // the tests, outside a page
    module.exports = { pathLength, polygonArea, PRESETS, data, totals,
                       state };
    return;
  }
  document.addEventListener("webviewerloaded", () => {
    window.PDFViewerApplication.initializedPromise.then(start)
      .catch((e) => console.error("takeoff:", e));
  });
  window.QSTakeoff = { data, count: () => state.marks.length };
})();
