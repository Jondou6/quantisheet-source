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
  const COLORS = { length: "#d91a1a", area: "#1a73d9", count: "#e68000",
                   cutout: "#1a73d9" };
  // A named item keeps one colour, the same one QuantiSheet gives it
  // (app/webmarks.py PALETTE; the tests compare the two lists).
  const PALETTE = [[0.85, 0.1, 0.1], [0.1, 0.45, 0.85], [0.1, 0.6, 0.3],
                   [0.9, 0.5, 0.0], [0.55, 0.25, 0.75], [0.0, 0.6, 0.65],
                   [0.8, 0.2, 0.55], [0.45, 0.35, 0.15]];

  function colorFor(mark) {
    const name = mark.group || "";
    if (!name || mark.type === "cutout" || mark.type === "calibrate") {
      return COLORS[mark.type] || "#333";
    }
    let sum = 0;
    for (const ch of name) sum += ch.codePointAt(0);
    const c = PALETTE[sum % PALETTE.length];
    return "rgb(" + c.map((v) => Math.round(v * 255)).join(",") + ")";
  }

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

  // A length typed the way it is written on drawings: "20", "12.5 m",
  // "10'", "10' 6\"", "10'-6 1/2\"", "54\"", "4ft 6in". { value, unit }
  // (unit null when none was typed), or null when it isn't a length.
  function parseLength(text) {
    const s = String(text || "").replace(/[\u2018\u2019\u2032]/g, "'")
      .replace(/[\u201c\u201d\u2033]/g, '"').trim().toLowerCase();
    if (!s) return null;
    let m = /^(\d+(?:\.\d+)?)\s*(ft|in|yd|m|cm|mm)?$/.exec(s);
    if (m) return { value: parseFloat(m[1]), unit: m[2] || null };
    m = /^(?:(\d+(?:\.\d+)?)\s*(?:'|ft))?\s*-?\s*(?:(\d+(?:\.\d+)?)?(?:\s+(\d+)\/(\d+))?\s*(?:"|in))?$/
      .exec(s);
    if (!m || (m[1] === undefined && m[2] === undefined &&
               m[3] === undefined)) return null;
    let inches = parseFloat(m[2] || "0");
    if (m[3] && Number(m[4])) inches += Number(m[3]) / Number(m[4]);
    if (m[1] !== undefined) {
      return { value: parseFloat(m[1]) + inches / 12, unit: "ft" };
    }
    return inches > 0 ? { value: inches, unit: "in" } : null;
  }

  // The drawing scale a page's own words state, when they state exactly
  // one: { name, ppu, unit } or null. Offered, never applied by itself.
  function scaleInText(text) {
    const found = new Map();
    const s = String(text || "").replace(/[\u2018\u2019\u2032]/g, "'")
      .replace(/[\u201c\u201d\u2033]/g, '"');
    // 1/4" = 1'-0"   3/16"=1'-0"   1 1/2" = 1'-0"   3" = 1'-0"
    const arch = /(?:^|[\s:(=])(?:(\d{1,2})[ -])?(\d{1,2})(?:\/(\d{1,2}))?"\s*=\s*1'\s*-?\s*0"?/g;
    let m;
    while ((m = arch.exec(s))) {
      let inches;
      if (m[3] && Number(m[2]) >= Number(m[3])) continue;   // not "11/4"
      if (m[3]) inches = Number(m[1] || 0) + Number(m[2]) / Number(m[3]);
      else if (m[1]) continue;                 // "2 3" = ..." is not a scale
      else inches = Number(m[2]);
      if (inches > 0 && inches <= 12) found.set(inches.toFixed(5), inches);
    }
    // 1" = 20'    1"=40 ft
    const eng = /(?:^|[\s:(=])1"\s*=\s*(\d{1,4})\s*(?:'|ft\b|feet\b)(?!\s*-?\s*\d)/gi;
    while ((m = eng.exec(s))) {
      const feet = Number(m[1]);
      if (feet >= 2) found.set((1 / feet).toFixed(5), 1 / feet);
    }
    if (found.size !== 1) return null;
    const inches = [...found.values()][0];
    const ppu = INCH * inches;
    const known = PRESETS.find((p) => p[2] === "ft" &&
                               Math.abs(p[1] - ppu) < 1e-6);
    return { ppu, unit: "ft",
             name: known ? known[0] : (inches >= 1 / 12 + 1e-9
               ? inches + '" = 1\'-0"' : '1" = ' + Math.round(1 / inches) +
                 "'") };
  }

  // ---- snapping to the drawing ------------------------------------------
  // The ends of the lines a PDF page draws, in the page's own
  // coordinates, read from the viewer's record of what the page draws.
  // `ops` and `args` are that record; OPS names its codes.
  const SNAP_MOST = 400000;

  function times(m, n) {
    return [m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
            m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
            m[0] * n[4] + m[2] * n[5] + m[4],
            m[1] * n[4] + m[3] * n[5] + m[5]];
  }

  function lineEnds(ops, args, OPS) {
    const out = [];
    let m = [1, 0, 0, 1, 0, 0];
    const stack = [];
    const add = (x, y) => {
      if (out.length < SNAP_MOST) {
        out.push([m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]]);
      }
    };
    for (let i = 0; i < ops.length; i++) {
      const op = ops[i], a = args[i];
      if (op === OPS.save) {
        stack.push(m);
      } else if (op === OPS.restore) {
        if (stack.length) m = stack.pop();
      } else if (op === OPS.transform) {
        m = times(m, a);
      } else if (op === OPS.paintFormXObjectBegin) {
        stack.push(m);
        if (a && Array.isArray(a[0]) && a[0].length === 6) m = times(m, a[0]);
      } else if (op === OPS.paintFormXObjectEnd) {
        if (stack.length) m = stack.pop();
      } else if (op === OPS.constructPath && a) {
        const kinds = a[0], n = a[1];
        for (let k = 0, j = 0; k < kinds.length; k++) {
          const kind = kinds[k] | 0;
          if (kind === OPS.rectangle) {
            const x = n[j++], y = n[j++], w = n[j++], h = n[j++];
            add(x, y);
            add(x + w, y);
            add(x + w, y + h);
            add(x, y + h);
          } else if (kind === OPS.moveTo || kind === OPS.lineTo) {
            add(n[j++], n[j++]);
          } else if (kind === OPS.curveTo) {
            j += 4;
            add(n[j++], n[j++]);           // where the curve ends
          } else if (kind === OPS.curveTo2 || kind === OPS.curveTo3) {
            j += 2;
            add(n[j++], n[j++]);
          }
        }
      }
    }
    return out;
  }

  const CELL = 24;

  function gridOf(points) {
    const grid = new Map();
    for (const p of points) {
      const key = Math.floor(p[0] / CELL) + "," + Math.floor(p[1] / CELL);
      const cell = grid.get(key);
      if (cell) cell.push(p);
      else grid.set(key, [p]);
    }
    return grid;
  }

  // The drawn line end nearest to p within `reach`, or null.
  function nearest(grid, p, reach) {
    let best = null, d = reach;
    const cx = Math.floor(p[0] / CELL), cy = Math.floor(p[1] / CELL);
    const span = Math.ceil(reach / CELL);
    for (let x = cx - span; x <= cx + span; x++) {
      for (let y = cy - span; y <= cy + span; y++) {
        for (const q of grid.get(x + "," + y) || []) {
          const dist = Math.hypot(q[0] - p[0], q[1] - p[1]);
          if (dist <= d) {
            d = dist;
            best = q;
          }
        }
      }
    }
    return best;
  }

  // With Shift held: p pulled onto the straight, level or 45-degree line
  // from the last corner clicked.
  function square(from, p) {
    const dx = p[0] - from[0], dy = p[1] - from[1];
    const len = Math.hypot(dx, dy);
    if (!len) return p;
    const step = Math.PI / 4;
    const ang = Math.round(Math.atan2(dy, dx) / step) * step;
    return [from[0] + len * Math.cos(ang), from[1] + len * Math.sin(ang)];
  }

  const snaps = new Map();             // page -> grid, or "loading"

  function loadSnaps(page) {
    if (snaps.has(page) || !app.pdfDocument || !window.pdfjsLib) return;
    snaps.set(page, "loading");
    app.pdfDocument.getPage(page + 1).then((p) => p.getOperatorList())
      .then((list) => snaps.set(page, gridOf(
        // a sheet with millions of drawing steps is left alone: reading
        // them all would hold the page up
        list.fnArray.length > 3000000 ? []
          : lineEnds(list.fnArray, list.argsArray, window.pdfjsLib.OPS))))
      .catch(() => snaps.set(page, new Map()));
  }

  // p moved onto a drawn line end (or one of the measurements' own
  // corners) when one is close; p itself when not, or when Snap is off.
  function snap(page, p) {
    const on = panel && panel.querySelector("#qsSnap");
    if (on && !on.checked) return p;
    const reach = 9 / (view(page).viewport.scale || 1);
    const own = [];
    for (const m of state.marks) if (m.page === page) own.push(...m.pts);
    let best = nearest(gridOf(own), p, reach);
    const grid = snaps.get(page);
    if (!grid) loadSnaps(page);
    else if (grid !== "loading") {
      const drawn = nearest(grid, p, best
        ? Math.hypot(best[0] - p[0], best[1] - p[1]) : reach);
      if (drawn) best = drawn;
    }
    return best ? [best[0], best[1]] : p;
  }

  // Where a click at p lands: squared up with Shift, else snapped.
  function aim(page, p, e) {
    const now = state.now;
    if (e && e.shiftKey && now && now.page === page && now.pts.length) {
      return square(now.pts[now.pts.length - 1], p);
    }
    return snap(page, p);
  }

  // How far point p is from the line a-b.
  function nearLine(p, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = dx * dx + dy * dy;
    let k = len ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len : 0;
    k = Math.max(0, Math.min(1, k));
    return Math.hypot(p[0] - (a[0] + k * dx), p[1] - (a[1] + k * dy));
  }

  function inside(p, pts) {
    let hit = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const a = pts[i], b = pts[j];
      if ((a[1] > p[1]) !== (b[1] > p[1]) &&
          p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0]) {
        hit = !hit;
      }
    }
    return hit;
  }

  // The measurement on `page` under point `p` (the last drawn wins), or
  // -1. `reach` is how close counts as on it, in PDF points.
  function markAt(marks, page, p, reach) {
    for (let i = marks.length - 1; i >= 0; i--) {
      const m = marks[i];
      if (m.page !== page) continue;
      if (m.type === "count") {
        if (Math.hypot(p[0] - m.pts[0][0], p[1] - m.pts[0][1]) <= reach * 1.5) {
          return i;
        }
        continue;
      }
      const closed = m.type === "area" || m.type === "cutout";
      if (closed && inside(p, m.pts)) return i;
      const n = m.pts.length;
      const last = closed ? n : n - 1;
      for (let k = 0; k < last; k++) {
        if (nearLine(p, m.pts[k], m.pts[(k + 1) % n]) <= reach) return i;
      }
    }
    return -1;
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
    return (mark.type === "cutout" ? "Cutout -" : "") +
      (polygonArea(mark.pts) / (sc.ppu * sc.ppu)).toFixed(2) +
      " sq " + sc.unit;
  }

  // The area a cut-out comes off: the smallest one on its page that its
  // middle is inside (the way QuantiSheet's own Cutout tool picks it).
  function areaOf(cut) {
    let cx = 0, cy = 0;
    for (const p of cut.pts) {
      cx += p[0] / cut.pts.length;
      cy += p[1] / cut.pts.length;
    }
    let best = null, size = Infinity;
    for (const m of state.marks) {
      if (m.type !== "area" || m.page !== cut.page ||
          !inside([cx, cy], m.pts)) continue;
      const a = polygonArea(m.pts);
      if (a < size) {
        size = a;
        best = m;
      }
    }
    return best;
  }

  function totals() {
    const rows = new Map();
    for (const m of state.marks) {
      const sc = scaleFor(m.page);
      // a cut-out comes off its area's line; one outside every area is
      // shown on its own, because QuantiSheet will leave it out
      const of = m.type === "cutout" ? areaOf(m) : null;
      const type = of ? "area" : m.type;
      const group = of ? of.group : m.group;
      const unit = type === "count" ? "ea"
        : type === "cutout" ? "not inside an area"
          : !sc ? "?" : type === "length" ? sc.unit : "sq " + sc.unit;
      const key = type + "|" + (group || "") + "|" + unit;
      const size = type === "count" ? 1 : !sc ? 0
        : type === "length" ? pathLength(m.pts) / sc.ppu
          : polygonArea(m.pts) / (sc.ppu * sc.ppu);
      const row = rows.get(key) || { type, group: group || "", unit,
                                     value: 0, n: 0 };
      row.value += of ? -size : size;
      if (!of) row.n += 1;
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

  // A PDF opened by its web address keeps its takeoff until it is sent
  // or cleared, even if the browser is closed; one the add-on is holding
  // (View here) keeps it for this browser session.
  function shelf() {
    return localStorage;
  }

  // Takeoff kept for a PDF the add-on was holding (View here) goes when
  // that PDF does: after a day. One kept for a PDF opened by its address
  // stays until it is cleared.
  function prune() {
    try {
      const old = Date.now() - 24 * 60 * 60 * 1000;
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const k = localStorage.key(i);
        if (!k || !k.startsWith("qs-takeoff:") || /[?&]src=/.test(k)) {
          continue;
        }
        let at = 0;
        try {
          at = JSON.parse(localStorage.getItem(k)).at || 0;
        } catch (e) { /* not ours to read: removed */ }
        if (at < old) localStorage.removeItem(k);
      }
    } catch (e) { /* no storage here */ }
  }

  function keep() {
    try {
      if (!state.marks.length && !state.everyPage &&
          !Object.keys(state.scales).length) {
        shelf().removeItem(KEY);
        return;
      }
      shelf().setItem(KEY, JSON.stringify({
        at: Date.now(),
        scales: state.scales, everyPage: state.everyPage, marks: state.marks
      }));
    } catch (e) { /* private window: kept for this page only */ }
  }

  function restore() {
    prune();
    try {
      const got = JSON.parse(shelf().getItem(KEY) || "null");
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
      svg.addEventListener("mousedown", (e) => onDown(e, page, svg));
      svg.addEventListener("mouseup", () => onUp());
      svg.addEventListener("mouseleave", () => onUp());
      pv.div.appendChild(svg);
    }
    svg.style.pointerEvents = state.tool ? "auto" : "none";
    svg.style.cursor = state.tool === "move" ? "move"
      : state.tool ? "crosshair" : "";
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
    const color = colorFor(m);
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
    if (m.type === "cutout" && pts.length > 2) {
      svg.appendChild(el("polygon", { points: d, fill: "#fff",
                                      "fill-opacity": 0.85, stroke: color,
                                      "stroke-width": 1.5,
                                      "stroke-dasharray": "5 3" }));
    } else if (m.type === "area" && pts.length > 2) {
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
    if (state.tool && state.tool !== "erase" && state.tool !== "move" &&
        state.at &&
        state.at.page === page) {
      const [x, y] = toScreen(page, state.at.pt);
      svg.appendChild(el("rect", { x: x - 4, y: y - 4, width: 8, height: 8,
                                   fill: "none", stroke: "#0e6a60",
                                   "stroke-width": 1.5 }));
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

  // Move: drag a corner of a measurement to where it should be.
  function cornerAt(marks, page, p, reach) {
    let best = null, d = reach;
    marks.forEach((m, i) => {
      if (m.page !== page) return;
      m.pts.forEach((q, k) => {
        const dist = Math.hypot(q[0] - p[0], q[1] - p[1]);
        if (dist <= d) {
          d = dist;
          best = { mark: i, corner: k };
        }
      });
    });
    return best;
  }

  function onDown(e, page, svg) {
    if (state.tool !== "move") return;
    e.preventDefault();
    const hit = cornerAt(state.marks, page, toPdf(page, svg, e),
                         9 / (view(page).viewport.scale || 1));
    state.drag = hit ? Object.assign({ page }, hit) : null;
  }

  function onUp() {
    if (!state.drag) return;
    state.drag = null;
    changed();
  }

  function onClick(e, page, svg) {
    if (!state.tool || state.tool === "move") return;
    e.preventDefault();
    e.stopPropagation();
    let pt = toPdf(page, svg, e);
    if (state.tool !== "erase") pt = aim(page, pt, e);
    if (state.tool === "erase") {
      const i = markAt(state.marks, page, pt,
                       8 / (view(page).viewport.scale || 1));
      if (i >= 0) {
        state.marks.splice(i, 1);
        changed();
      }
      return;
    }
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
    if (!state.tool || state.tool === "erase") return;
    if (state.tool === "move") {
      const d = state.drag;
      if (!d || d.page !== page) return;
      // snapped to the drawing, but not to the corner being dragged
      const m = state.marks[d.mark];
      const held = m.pts[d.corner];
      m.pts[d.corner] = [1e9, 1e9];
      const to = snap(page, toPdf(page, svg, e));
      m.pts[d.corner] = held;
      m.pts[d.corner] = to;
      draw(page);
      showPanel();
      return;
    }
    const pt = aim(page, toPdf(page, svg, e), e);
    state.at = { page, pt };             // where a click would land
    if (!state.now || state.now.page !== page) {
      draw(page);
      return;
    }
    state.hover = { page, pt };
    draw(page);
  }

  function finish() {
    const now = state.now;
    state.now = null;
    state.hover = null;
    if (!now) return;
    const need = now.type === "area" || now.type === "cutout" ? 3 : 2;
    if (now.type !== "calibrate" && now.pts.length >= need) {
      state.marks.push(now);
      changed();
    } else {
      draw(now.page);
    }
    hint();
    if (now.type !== "calibrate" && now.pts.length >= need &&
        !scaleFor(now.page)) {
      say("This page has no scale yet. Set it (above), or QuantiSheet " +
          "will use the drawing's own scale if it has one and leave " +
          "this measurement out if it doesn't.");
    }
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
    state.at = null;
    if (state.tool) loadSnaps((app.page || 1) - 1);
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
    panel.querySelector("#qsCalLen").onkeydown = (e) => {
      if (e.key === "Enter") panel.querySelector("#qsCalOk").click();
    };
    panel.querySelector("#qsCalOk").onclick = () => {
      const typed = parseLength(panel.querySelector("#qsCalLen").value);
      const real = typed ? typed.value : 0;
      const unit = (typed && typed.unit) ||
        panel.querySelector("#qsCalUnit").value;
      const dist = pathLength(now.pts);
      if (!(real > 0) || !(dist > 0) || !UNITS.includes(unit)) {
        say("Type the real length of the line you clicked, for example " +
            "20 or 12' 6\".");
        return;
      }
      box.hidden = true;
      state.now = null;
      state.tool = null;
      setScale(now.page, { ppu: dist / real, unit,
                           name: Number(real.toFixed(4)) + " " + unit +
                             " by two points" },
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
      "finish. Esc cancels. Hold Shift for a straight or 45-degree line."
      : t === "area" ? "Click each corner. Double-click (or Enter) to " +
        "finish. Esc cancels. Hold Shift to square up."
        : t === "cutout" ? "Click each corner of the opening, inside an " +
          "area you measured. Double-click (or Enter) to finish."
        : t === "count" ? "Click each one. Click Count again when done."
          : t === "calibrate" ? "Click the two ends of a known dimension."
            : t === "erase" ? "Click a measurement to remove it. Click " +
              "Erase again when done."
              : t === "move" ? "Drag a corner of a measurement to where " +
                "it should be. Click Move again when done."
            : "Numbers here are a preview. QuantiSheet works out the " +
              "quantities when you press Open in QuantiSheet. Keys: " +
              "Shift+L length, Shift+A area, Shift+C count.");
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
    suggest(page, !!sc);
    const list = panel.querySelector("#qsTotals");
    list.textContent = "";
    for (const r of totals()) {
      const li = document.createElement("div");
      const what = r.type === "count" ? r.n + " ea"
        : r.type === "cutout" ? r.n + " " + r.unit + " (won't be taken off)"
        : r.unit.startsWith("?") ? r.n + " without a scale"
          : r.value.toFixed(2) + " " + r.unit;
      li.textContent = (r.group || "(no name)") + " - " +
        r.type + ": " + what;
      list.appendChild(li);
    }
    if (!state.marks.length) list.textContent = "Nothing measured yet.";
  }

  // What the page's own words say its scale is, offered as a button.
  const said = new Map();              // page -> scale or null

  function suggest(page, has) {
    const box = panel.querySelector("#qsSaid");
    const show = (sc) => {
      if ((app.page || 1) - 1 !== page) return;
      box.hidden = !sc || has;
      if (box.hidden) return;
      box.querySelector("span").textContent = "This page says " + sc.name +
        ". ";
      box.querySelector("button").onclick = () => {
        setScale(page, sc, panel.querySelector("#qsEvery").checked);
        say("Scale set: " + sc.name + ". Check it against a dimension.");
      };
    };
    if (has || !app.pdfDocument) {
      box.hidden = true;
      return;
    }
    if (said.has(page)) {
      show(said.get(page));
      return;
    }
    box.hidden = true;
    app.pdfDocument.getPage(page + 1).then((p) => p.getTextContent())
      .then((tc) => {
        const sc = scaleInText(tc.items.map((i) => i.str).join(" "));
        said.set(page, sc);
        show(sc);
      }).catch(() => said.set(page, null));
  }

  const DOCK = 300;

  // Show or hide the takeoff column; the page area gives it the room.
  function dock(show) {
    panel.hidden = !show;
    const area = document.getElementById("viewerContainer");
    if (area) area.style.right = show ? DOCK + "px" : "";
    window.dispatchEvent(new Event("resize"));
  }

  function build() {
    panel = document.createElement("div");
    panel.id = "qsTakeoffPanel";
    panel.hidden = true;
    // a column of its own down the right side: the drawing is never
    // covered (Nov 28: floating, it sat on top of what was being measured)
    panel.style.cssText = "position:fixed;right:0;top:32px;bottom:0;" +
      "z-index:100000;width:" + DOCK + "px;box-sizing:border-box;" +
      "padding:10px 12px;overflow:auto;background:#fff;color:#1d2b29;" +
      "font:13px system-ui,sans-serif;border-left:1px solid #b8c4c2";
    const btn = "padding:5px 9px;margin:2px 3px 2px 0;border:1px solid " +
      "#9fb1ae;border-radius:5px;background:#f3f6f5;cursor:pointer;" +
      "font:600 12px system-ui,sans-serif";
    const opts = PRESETS.map((p, i) => "<option value='" + i + "'></option>")
      .join("");
    panel.innerHTML =
      "<div style='font-weight:700;margin-bottom:4px'>Takeoff</div>" +
      "<div id='qsScaleNow' style='margin-bottom:4px'></div>" +
      "<div id='qsSaid' hidden style='margin-bottom:4px'><span></span>" +
      "<button style=\"" + btn + "\">Use it</button></div>" +
      "<select id='qsPreset' style='max-width:150px'>" +
      "<option value=''>Set scale...</option>" + opts + "</select> " +
      "<button data-tool='calibrate' style=\"" + btn + "\">By two points" +
      "</button>" +
      "<label style='display:block;margin:3px 0'><input type='checkbox' " +
      "id='qsEvery'> for every page</label>" +
      "<label style='display:block;margin:3px 0'><input type='checkbox' " +
      "id='qsSnap' checked> Snap to the drawing's line ends</label>" +
      "<div id='qsCal' hidden style='margin:4px 0'>Real length: " +
      "<input id='qsCalLen' size='6'> <select id='qsCalUnit'></select> " +
      "<button id='qsCalOk' style=\"" + btn + "\">Set</button></div>" +
      "<div style='margin-top:6px'>Name: <input id='qsGroup' size='18' " +
      "maxlength='60' placeholder='Walls, Doors...'></div>" +
      "<div style='margin-top:4px'>" +
      "<button data-tool='length' style=\"" + btn + "\">Length</button>" +
      "<button data-tool='area' style=\"" + btn + "\">Area</button>" +
      "<button data-tool='cutout' style=\"" + btn + "\">Cut-out</button>" +
      "<button data-tool='count' style=\"" + btn + "\">Count</button>" +
      "<button data-tool='move' style=\"" + btn + "\">Move</button>" +
      "<button data-tool='erase' style=\"" + btn + "\">Erase</button>" +
      "<button id='qsUndo' style=\"" + btn + "\">Undo</button>" +
      "<button id='qsClear' style=\"" + btn + "\">Clear</button></div>" +
      "<div id='qsTotals' style='margin-top:6px;" +
      "border-top:1px solid #e0e6e5;padding-top:4px'></div>" +
      "<div id='qsHint' style='margin-top:6px;color:#4d5f5c'></div>";
    document.body.appendChild(panel);
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
      dock(panel.hidden);
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
      // the same keys as QuantiSheet: Shift+L, Shift+A, Shift+C (while
      // the takeoff column is open, and not while typing in a box)
      const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(
        (e.target && e.target.tagName) || "") ||
        (e.target && e.target.isContentEditable);
      const key = { L: "length", A: "area", C: "count" }[e.key];
      if (key && e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey &&
          !typing && !panel.hidden) {
        e.preventDefault();
        e.stopPropagation();
        setTool(key);
        return;
      }
      if (!state.tool) return;
      if (e.key === "Escape") cancel();
      else if (e.key === "Enter" && !typing) finish();
    }, true);
    if (state.marks.length) dock(true);
    showPanel();
  }

  if (typeof module !== "undefined") {          // the tests, outside a page
    module.exports = { pathLength, polygonArea, PRESETS, data, totals,
                       state, markAt, parseLength, scaleInText, lineEnds,
                       gridOf, nearest, square, cornerAt, PALETTE,
                       colorFor };
    return;
  }
  document.addEventListener("webviewerloaded", () => {
    window.PDFViewerApplication.initializedPromise.then(start)
      .catch((e) => console.error("takeoff:", e));
  });
  window.QSTakeoff = { data, count: () => state.marks.length };
})();
