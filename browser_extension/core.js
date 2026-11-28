// Open in QuantiSheet: the part with no browser calls in it, so it can be
// tested on its own (tests/test_browser_extension.py).
//
// What the add-on does, and all it does: saves the PDF the user points at
// into Downloads\QuantiSheet on this computer, then opens the link
// quantisheet://open?path=<that file>, which QuantiSheet (if installed)
// turns into "open this PDF". Nothing is sent anywhere.

const QS_FOLDER = "QuantiSheet";

// A file name that is safe on Windows, always ending in .pdf.
function pdfName(url, title) {
  let name = "";
  try {
    const u = new URL(url);
    name = decodeURIComponent(u.pathname.split("/").pop() || "");
  } catch (e) {
    name = "";
  }
  if (!/\.pdf$/i.test(name)) {
    name = (title || "").trim() || name || "drawing";
  }
  name = name.replace(/\.pdf$/i, "")
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ")
    .replace(/\s+/g, " ").trim().replace(/[. ]+$/, "").slice(0, 120);
  if (!name || /^(con|prn|aux|nul|com\d|lpt\d)$/i.test(name)) {
    name = "drawing";
  }
  return name + ".pdf";
}

// Only web addresses can be fetched; a PDF already on disk needs no add-on.
function canFetch(url) {
  return /^https?:\/\//i.test(url || "");
}

// The saved file must be a PDF before it is handed over.
function isPdf(item) {
  if (!item || !item.filename) return false;
  return /\.pdf$/i.test(item.filename) &&
    (!item.mime || item.mime === "application/pdf" ||
     item.mime === "application/octet-stream" ||
     item.mime === "binary/octet-stream" ||
     item.mime === "application/x-pdf");
}

// Some sites show a PDF inside a web page. Where the direct file has a
// known address, use it: a Dropbox shared link downloads with dl=1.
function directUrl(url) {
  try {
    const u = new URL(url);
    if (/(^|\.)dropbox\.com$/i.test(u.hostname) &&
        /^\/(s|scl|sh)\//.test(u.pathname)) {
      u.searchParams.set("dl", "1");
      return u.toString();
    }
  } catch (e) {
    return url;
  }
  return url;
}

// How long "open my next PDF download" stays on.
const WATCH_MS = 3 * 60 * 1000;

// The two things a user can turn on (popup): both need to see which pages
// are PDFs, so the browser asks for that access when one is ticked.
const OPTIONS = { button: false, always: false, viewer: false };
const SITES = { origins: ["http://*/*", "https://*/*"],
                permissions: ["webRequest"] };

// Is this answer from a website a PDF being shown in the tab?
function isPdfResponse(url, headers) {
  let type = "", disp = "";
  for (const h of headers || []) {
    const n = (h.name || "").toLowerCase();
    if (n === "content-type") type = (h.value || "").toLowerCase();
    if (n === "content-disposition") disp = (h.value || "").toLowerCase();
  }
  if (/^\s*attachment/.test(disp)) return false;   // a download, not a view
  if (type.startsWith("application/pdf")) return true;
  return /\.pdf($|[?#])/i.test(url || "") &&
    (type.startsWith("application/octet-stream") ||
     type.startsWith("binary/octet-stream"));
}

// The browser could not write the file where it was told to (a folder
// it may not write to, a name too long, no room): another place may work.
function cannotWrite(error) {
  return /^FILE_(ACCESS_DENIED|FAILED|NAME_TOO_LONG|NO_SPACE|TRANSIENT_ERROR|BLOCKED)$/
    .test(error || "");
}

function appLink(path) {
  return "quantisheet://open?path=" + encodeURIComponent(path);
}

// ---- the direct line to the program (used by the background part and
// by the viewer page) --------------------------------------------------
const HOST = "com.quantisheet.open";
const PIECE = 384 * 1024;           // bytes of the PDF per message

function b64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(s);
}

function looksPdf(bytes) {
  const n = Math.min(bytes.length, 1024);
  for (let i = 0; i + 4 < n; i++) {
    if (bytes[i] === 0x25 && bytes[i + 1] === 0x50 && bytes[i + 2] === 0x44 &&
        bytes[i + 3] === 0x46 && bytes[i + 4] === 0x2d) return true;
  }
  return false;
}

// One conversation with the program: ask() sends a message and gives the
// program's answer, or null when the program isn't there (not installed,
// too old, or it stopped).
class Line {
  constructor() {
    this.waiting = [];
    this.dead = false;
    try {
      this.port = chrome.runtime.connectNative(HOST);
    } catch (e) {
      this.dead = true;
      return;
    }
    this.port.onMessage.addListener((m) => {
      const w = this.waiting.shift();
      if (w) w(m);
    });
    this.port.onDisconnect.addListener(() => {
      void chrome.runtime.lastError;
      this.dead = true;
      this.waiting.splice(0).forEach((w) => w(null));
    });
  }

  ask(msg) {
    return new Promise((resolve) => {
      if (this.dead) {
        resolve(null);
        return;
      }
      this.waiting.push(resolve);
      try {
        this.port.postMessage(msg);
      } catch (e) {
        this.waiting.pop();
        resolve(null);
      }
    });
  }

  close() {
    this.dead = true;
    try {
      this.port.disconnect();
    } catch (e) { /* already closed */ }
  }
}

const OFF_BY_IT = "Your IT department has turned off opening PDFs from " +
  "the browser in QuantiSheet.";

// ---- a PDF kept inside the add-on for its viewer page ------------------
// (the browser's own storage for this add-on; nothing leaves the computer)
const STASH_DB = "qs-view";
const STASH_KEEP_MS = 24 * 60 * 60 * 1000;

function stashDb() {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(STASH_DB, 1);
    open.onupgradeneeded = () => open.result.createObjectStore("pdf");
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  });
}

async function stashPut(id, rec) {
  const db = await stashDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction("pdf", "readwrite");
    const store = tx.objectStore("pdf");
    // yesterday's PDFs are not kept
    store.openCursor().onsuccess = (e) => {
      const cur = e.target.result;
      if (!cur) return;
      if (Date.now() - (cur.value.at || 0) > STASH_KEEP_MS) cur.delete();
      cur.continue();
    };
    store.put(Object.assign({ at: Date.now() }, rec), id);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

async function stashGet(id) {
  const db = await stashDb();
  const rec = await new Promise((resolve, reject) => {
    const req = db.transaction("pdf").objectStore("pdf").get(id);
    req.onsuccess = () => resolve(req.result || null);
    req.onerror = () => reject(req.error);
  });
  db.close();
  return rec;
}

if (typeof module !== "undefined") {
  module.exports = { QS_FOLDER, WATCH_MS, OPTIONS, SITES, pdfName, canFetch,
                     isPdf, appLink, directUrl, isPdfResponse,
                     cannotWrite };
}
