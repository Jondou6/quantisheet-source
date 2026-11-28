// Open in QuantiSheet: the direct line to the program (no downloads).
//
// Nov 26 (Jon, Brave: every download the add-on started brought up the
// browser's Save As window and nothing reached QuantiSheet): the PDF is
// handed straight to QuantiSheet on this computer through the browser's
// "native messaging" (the setup of QuantiSheet 1.1.38 or newer registers
// it). The PDF goes to the program on this computer and nowhere else.
// (HOST, PIECE, b64, looksPdf and Line are in core.js: the viewer page
// uses them too.)

// ---- the PDF the add-on asks the website for itself ---------------------
async function viaFetch(line, url, name) {
  let res;
  try {
    res = await fetch(url, { credentials: "include" });
  } catch (e) {
    return { ok: false };           // no access to that site, or offline
  }
  if (!res.ok || !res.body) return { ok: false };
  const reader = res.body.getReader();
  let held = new Uint8Array(0);
  let begun = false;
  const add = (more) => {
    const all = new Uint8Array(held.length + more.length);
    all.set(held);
    all.set(more, held.length);
    held = all;
  };
  const flush = async (everything) => {
    if (!begun) {
      if (!looksPdf(held)) return false;     // a web page, not the PDF
      const r = await line.ask({ type: "begin", name });
      if (!r || !r.ok) return false;
      begun = true;
    }
    while (held.length >= PIECE || (everything && held.length)) {
      const r = await line.ask({ type: "data",
                                 b64: b64(held.subarray(0, PIECE)) });
      if (!r || !r.ok) return false;
      held = held.slice(Math.min(PIECE, held.length));
    }
    return true;
  };
  for (;;) {
    const { done, value } = await reader.read().catch(() => ({ done: true,
                                                               bad: true }));
    if (value) add(value);
    if (!done && held.length < Math.max(PIECE, 1024)) continue;
    if (!(await flush(done))) {
      reader.cancel().catch(() => {});
      return { ok: false };
    }
    if (done) break;
  }
  const end = await line.ask({ type: "end" });
  return end && end.ok ? { ok: true, path: end.path } : { ok: false };
}

// ---- the PDF the tab is already showing ---------------------------------
// Runs inside the PDF's tab (so it must not use anything outside itself):
// reads the PDF from the page's own address, from the browser's own copy
// where it has one, and passes it to the add-on piece by piece.
async function grabToApp(name, piece) {
  const port = chrome.runtime.connect({ name: "qs-grab" });
  const ask = (m) => new Promise((resolve) => {
    const h = (r) => {
      port.onMessage.removeListener(h);
      resolve(r);
    };
    port.onMessage.addListener(h);
    port.postMessage(m);
  });
  try {
    let r = await fetch(location.href, { credentials: "include",
                                         cache: "force-cache" });
    if (!r.ok) r = await fetch(location.href, { credentials: "include" });
    if (!r.ok) throw new Error("refused");
    const all = new Uint8Array(await r.arrayBuffer());
    let pdf = false;
    for (let i = 0; i + 4 < Math.min(all.length, 1024); i++) {
      if (all[i] === 0x25 && all[i + 1] === 0x50 && all[i + 2] === 0x44 &&
          all[i + 3] === 0x46 && all[i + 4] === 0x2d) {
        pdf = true;
        break;
      }
    }
    if (!pdf) throw new Error("not a PDF");
    let a = await ask({ type: "begin", name });
    for (let at = 0; a && a.ok && at < all.length; at += piece) {
      const part = all.subarray(at, at + piece);
      let s = "";
      for (let i = 0; i < part.length; i += 0x8000) {
        s += String.fromCharCode.apply(null, part.subarray(i, i + 0x8000));
      }
      a = await ask({ type: "data", b64: btoa(s) });
    }
    if (a && a.ok) await ask({ type: "end" });
  } catch (e) {
    port.postMessage({ type: "fail" });
  }
  port.disconnect();
}

const grabbing = new Map();          // tab id -> { line, done }

function viaTab(line, tabId, name) {
  return new Promise((resolve) => {
    let over = false;
    const done = (r) => {
      if (over) return;
      over = true;
      grabbing.delete(tabId);
      clearTimeout(timer);
      resolve(r);
    };
    // a page that never answers must not hold things up for ever
    const timer = setTimeout(() => done({ ok: false }), 10 * 60 * 1000);
    grabbing.set(tabId, { line, done });
    chrome.scripting.executeScript({
      target: { tabId }, func: grabToApp, args: [name, PIECE]
    }, () => {
      if (chrome.runtime.lastError) done({ ok: false });
    });
  });
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "qs-grab" || !port.sender || !port.sender.tab ||
      port.sender.id !== chrome.runtime.id) return;
  const g = grabbing.get(port.sender.tab.id);
  if (!g) {
    port.disconnect();
    return;
  }
  port.onDisconnect.addListener(() => g.done({ ok: false }));
  port.onMessage.addListener(async (m) => {
    const kind = m && m.type;
    if (kind !== "begin" && kind !== "data" && kind !== "end") {
      g.done({ ok: false });
      return;
    }
    const send = kind === "begin" ? { type: "begin", name: m.name }
      : kind === "data" ? { type: "data", b64: m.b64 } : { type: "end" };
    const r = await g.line.ask(send);
    if (!r || !r.ok) {
      g.done({ ok: false });
      try {
        port.postMessage({ ok: false });
      } catch (e) { /* the tab has gone */ }
      return;
    }
    if (kind === "end") g.done({ ok: true, path: r.path });
    try {
      port.postMessage({ ok: true });
    } catch (e) { /* the tab has gone */ }
  });
});

// The PDF straight into QuantiSheet. { ok: true, path } when the program
// took it; { ok: false, noApp } when this computer's QuantiSheet has no
// direct line (older than 1.1.38, or not installed).
async function direct(url, title, tabId, own) {
  if (!chrome.runtime.connectNative) return { ok: false, noApp: true };
  const line = new Line();
  const hello = await line.ask({ type: "hello" });
  if (!hello || !hello.ok) {
    line.close();
    return { ok: false, noApp: true };
  }
  const name = pdfName(url, title);
  let r = { ok: false };
  if (own && tabId !== undefined && tabId >= 0 && chrome.scripting) {
    r = await viaTab(line, tabId, name);
    if (!r.ok) await line.ask({ type: "abort" });
  }
  if (!r.ok) {
    r = await viaFetch(line, directUrl(url), name);
    if (!r.ok) await line.ask({ type: "abort" });
  }
  line.close();
  return r;
}
