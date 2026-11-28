// Open in QuantiSheet: background worker (Manifest V3). No remote code,
// no network requests of its own. The only thing kept is, for up to
// three minutes, "the user asked for the next PDF download to open in
// QuantiSheet" (session storage, gone when the browser closes).
importScripts("core.js", "direct.js", "page.js");

const MENU_LINK = "qs-open-link";
const MENU_PAGE = "qs-open-page";
const MENU_WEB = "qs-page-to-pdf";
// Our own downloads (download id -> tab id). Kept in session storage as
// well: the browser may put this worker to sleep while a big plan set is
// still downloading, and what is only in memory is gone when it wakes.
const waiting = new Map();

function remember(id, tabId, job) {
  const what = { tabId: tabId === undefined ? -1 : tabId, job };
  waiting.set(id, what);
  if (!store()) return;
  chrome.storage.session.get("mine", (got) => {
    const mine = (got && got.mine) || {};
    mine[id] = what;
    chrome.storage.session.set({ mine });
  });
}

// { tabId, job } when the download is ours, else null; forgets it.
// `job` is what was asked for: { url, title, place, own }.
function takeMine(id) {
  const tidy = (w) => w && { tabId: w.tabId < 0 ? undefined : w.tabId,
                             job: w.job || {} };
  return new Promise((resolve) => {
    const had = waiting.get(id);
    waiting.delete(id);
    if (!store()) {
      resolve(tidy(had) || null);
      return;
    }
    chrome.storage.session.get("mine", (got) => {
      const mine = (got && got.mine) || {};
      const kept = mine[id];
      if (kept !== undefined) {
        delete mine[id];
        chrome.storage.session.set({ mine });
      }
      resolve(tidy(had || kept) || null);
    });
  });
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_LINK, title: "Open linked PDF in QuantiSheet",
    contexts: ["link"]
  });
  chrome.contextMenus.create({
    id: MENU_PAGE, title: "Open this PDF in QuantiSheet",
    contexts: ["page", "frame"]
  });
  chrome.contextMenus.create({
    id: MENU_WEB, title: "Make this page a PDF in QuantiSheet",
    contexts: ["page"], documentUrlPatterns: ["http://*/*", "https://*/*"]
  });
});

function say(text, tabId) {
  chrome.action.setBadgeBackgroundColor({ color: "#b8312b" });
  chrome.action.setBadgeText({ text: text ? "!" : "", tabId });
  chrome.action.setTitle({
    title: text ? "Open in QuantiSheet - " + text : "Open in QuantiSheet",
    tabId
  });
}

function handOver(path, tabId) {
  // Nov 25 (Jon, Brave): sending the tab itself to the quantisheet://
  // link did nothing - a browser may not start another program from the
  // background. The add-on's own small page does it, with a button to
  // click if the browser wants a click.
  const url = chrome.runtime.getURL("open.html") + "?path=" +
    encodeURIComponent(path);
  const props = { url, active: true };
  if (tabId !== undefined && tabId >= 0) props.openerTabId = tabId;
  chrome.tabs.create(props, () => {
    if (chrome.runtime.lastError) chrome.tabs.create({ url });
  });
}

// "Open my next PDF download": for sites that show the PDF inside a page
// and only give the file through their own Download button.
const store = () => chrome.storage && chrome.storage.session;

function watch(tabId) {
  say("", tabId);
  if (!store()) {
    say("use the site's Download button, then open the PDF from " +
        "QuantiSheet", tabId);
    return Promise.resolve();
  }
  chrome.action.setBadgeBackgroundColor({ color: "#0e6a60" });
  chrome.action.setBadgeText({ text: "...", tabId });
  return chrome.storage.session.set({
    watch: { tabId, until: Date.now() + WATCH_MS }
  });
}

function stopWatching(tabId) {
  if (tabId !== undefined) chrome.action.setBadgeText({ text: "", tabId });
  return store() ? chrome.storage.session.remove("watch") :
    Promise.resolve();
}

// Where the PDF is saved, first choice first: the QuantiSheet folder in
// Downloads; straight into Downloads when the browser may not write
// there (Nov 25, Jon: "Needs permission to download"); then ask where.
const PLACES = ["folder", "downloads", "ask"];

// own: the address is the tab's own page (not a link on it), so if the
// website refuses to send the PDF a second time, the copy the tab already
// has can be saved instead (fromTab).
function send(url, title, tabId, opt) {
  const place = (opt && opt.place) || PLACES[0];
  const own = !!(opt && opt.own);
  if (!canFetch(url)) {
    say("this page isn't a web PDF", tabId);
    return Promise.resolve({ ok: false, why: "This page isn't a PDF on " +
      "the web. Open a PDF that is already on your computer from " +
      "QuantiSheet itself." });
  }
  say("", tabId);
  if (!(opt && opt.place)) {
    // first choice: straight into QuantiSheet, no download at all
    return direct(url, title, tabId, own).then((r) => {
      if (r.ok) return { ok: true, direct: true };
      return download(url, title, tabId, place, own);
    });
  }
  return download(url, title, tabId, place, own);
}

// The older way, for a QuantiSheet without the direct line: the browser
// downloads the PDF and the finished file is handed over.
function download(url, title, tabId, place, own) {
  return new Promise((resolve) => {
    chrome.downloads.download({
      url: directUrl(url),
      filename: (place === "folder" ? QS_FOLDER + "/" : "") +
        pdfName(url, title),
      conflictAction: "uniquify", saveAs: place === "ask"
    }, (id) => {
      if (chrome.runtime.lastError || id === undefined) {
        say("couldn't save the PDF", tabId);
        resolve({ ok: false, why: "The PDF couldn't be saved." });
        return;
      }
      remember(id, tabId, { url, title, place, own });
      resolve({ ok: true });
    });
  });
}

// Runs inside the PDF's tab: saves the PDF the tab is already showing
// (from the browser's own copy where it has one) as an ordinary download.
// Nothing else on the page is read, and nothing is sent anywhere.
async function grabPdf(name) {
  try {
    let r = await fetch(location.href, { credentials: "include",
                                         cache: "force-cache" });
    if (!r.ok) r = await fetch(location.href, { credentials: "include" });
    const type = (r.headers.get("content-type") || "").toLowerCase();
    if (!r.ok || !/application\/(pdf|x-pdf|octet-stream)|binary\/octet/
      .test(type)) return { ok: false };
    const blob = new Blob([await r.blob()], { type: "application/pdf" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.style.display = "none";
    document.documentElement.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 120000);
    return { ok: true };
  } catch (e) {
    return { ok: false };
  }
}

// The second way to get the PDF. Either way the add-on then waits for
// the next PDF download: the one grabPdf starts, or the user's own from
// the site's Download button.
function fromTab(tabId, job) {
  return watch(tabId).then(() => {
    if (!job || !job.own || tabId === undefined || tabId < 0 ||
        !chrome.scripting) return;
    chrome.scripting.executeScript({
      target: { tabId }, func: grabPdf,
      args: [pdfName(job.url, job.title)]
    }, () => void chrome.runtime.lastError);
  });
}

chrome.downloads.onChanged.addListener((delta) => {
  if (!delta.state) return;
  const state = delta.state.current;
  if (state !== "complete" && state !== "interrupted") return;
  takeMine(delta.id).then((mine) => {
    if (mine && state === "interrupted") {
      const why = (delta.error && delta.error.current) || "";
      const job = mine.job;
      const next = PLACES[PLACES.indexOf(job.place) + 1];
      if (cannotWrite(why) && next) {
        // the browser couldn't write the file there: try the next place
        chrome.downloads.erase({ id: delta.id });
        send(job.url, job.title, mine.tabId, { place: next, own: job.own });
        return;
      }
      if (why === "USER_CANCELED" || job.held) return;
      // the website wouldn't send it again (Nov 25, Jon: "Needs
      // permission to download"): save the copy the tab already has
      chrome.downloads.erase({ id: delta.id });
      fromTab(mine.tabId, job);
      return;
    }
    if (state !== "complete") return;
    if (mine) {
      chrome.downloads.search({ id: delta.id }, (items) => {
        const item = items && items[0];
        if (isPdf(item)) {
          handOver(item.filename, mine.tabId);
          return;
        }
        // the site sent a web page, not the PDF (a viewer or a sign-in
        // page): throw that file away and wait for the user's own download
        chrome.downloads.removeFile(delta.id, () => {
          void chrome.runtime.lastError;
          chrome.downloads.erase({ id: delta.id });
        });
        fromTab(mine.tabId, mine.job);
      });
      return;
    }
    // somebody else's download: ours to open only while the user asked
    if (!store()) return;
    chrome.storage.session.get("watch", (got) => {
      const w = got && got.watch;
      if (!w) return;
      if (Date.now() > w.until) {
        stopWatching(w.tabId);
        return;
      }
      chrome.downloads.search({ id: delta.id }, (items) => {
        const item = items && items[0];
        if (!isPdf(item)) return;
        stopWatching(w.tabId);
        handOver(item.filename, w.tabId);
      });
    });
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === MENU_WEB) {
    if (!tab) return;
    // the browser's OK is asked for here, on the user's own click
    chrome.permissions.request(PAGE_ACCESS, (ok) => {
      void chrome.runtime.lastError;
      if (!ok) return;
      say("", tab.id);
      pageToPdf(tab.id, tab.url, tab.title).then((r) => {
        if (!r.ok) say(r.why || "couldn't make the page a PDF", tab.id);
      });
    });
    return;
  }
  const url = info.menuItemId === MENU_LINK ? info.linkUrl :
    (info.frameUrl || info.pageUrl);
  const own = info.menuItemId !== MENU_LINK && !info.frameUrl;
  send(url, own ? (tab && tab.title) : "", tab && tab.id, { own });
});

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg && msg.type === "qs-open") {
    send(msg.url, msg.title, msg.tabId, { own: true }).then(reply);
    return true;                     // the reply comes later
  }
  if (msg && msg.type === "qs-view") {
    viewHere(msg.url, msg.title, msg.tabId).then(reply);
    return true;
  }
  if (msg && msg.type === "qs-page") {
    pageToPdf(msg.tabId, msg.url, msg.title).then(reply);
    return true;
  }
  if (msg && msg.type === "qs-watch") {
    watch(msg.tabId).then(() => reply({ ok: true }));
    return true;
  }
  if (msg && msg.type === "qs-stop") {
    stopWatching(msg.tabId).then(() => reply({ ok: true }));
    return true;
  }
  return false;
});

// A PDF the add-on itself holds (a web page made into a PDF, the viewer's
// marked-up copy) for a QuantiSheet without the direct line - the Store
// copy: the browser saves it, then it is handed over like any finished
// download.
function saveHeld(url, name, tabId) {
  return new Promise((resolve) => {
    chrome.downloads.download({
      url, filename: QS_FOLDER + "/" + pdfName("", name),
      conflictAction: "uniquify", saveAs: false
    }, (id) => {
      if (chrome.runtime.lastError || id === undefined) {
        resolve({ ok: false, why: "The PDF couldn't be saved." });
        return;
      }
      remember(id, tabId, { held: true, place: "ask" });
      resolve({ ok: true, saved: true });
    });
  });
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  // from the add-on's own viewer page only, and only a PDF it holds
  if (!msg || msg.type !== "qs-save" || !sender.tab ||
      sender.id !== chrome.runtime.id ||
      !String(sender.url || "").startsWith(VIEWER_URL) ||
      !String(msg.url || "").startsWith("blob:" + self.location.origin)) {
    return false;
  }
  saveHeld(msg.url, msg.name, sender.tab.id).then(reply);
  return true;
});

// ---- optional: a button on every PDF, and "always open PDFs" ------------
// Both are off until the user ticks them in the popup, which is also when
// the browser asks for access to see which pages are PDFs.
const recent = new Map();           // tab id -> [url, time] (no repeats)

function options() {
  return new Promise((resolve) => {
    if (!chrome.storage || !chrome.storage.local) {
      resolve(Object.assign({}, OPTIONS));
      return;
    }
    chrome.storage.local.get("options", (got) => resolve(
      Object.assign({}, OPTIONS, got && got.options)));
  });
}

// Runs inside the PDF's tab: a small button, top right, that asks the
// add-on to send this PDF to QuantiSheet. Nothing else on the page is
// read or changed.
function pageButton() {
  if (document.getElementById("qs-open-btn")) return;
  const host = document.createElement("div");
  host.id = "qs-open-btn";
  host.style.cssText = "position:fixed;top:64px;right:24px;" +
    "z-index:2147483647;";
  const root = host.attachShadow({ mode: "closed" });
  const b = document.createElement("button");
  b.textContent = "Open in QuantiSheet";
  b.style.cssText = "font:600 13px 'Segoe UI',Arial,sans-serif;" +
    "padding:9px 14px;border:0;border-radius:6px;background:#0e6a60;" +
    "color:#fff;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.35);";
  const x = document.createElement("button");
  x.textContent = "\u00d7";
  x.title = "Hide";
  x.style.cssText = "margin-left:6px;font:600 14px Arial;padding:8px 10px;" +
    "border:0;border-radius:6px;background:#2b3534;color:#fff;" +
    "cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.35);";
  b.addEventListener("click", () => {
    b.textContent = "Opening...";
    chrome.runtime.sendMessage({ type: "qs-open-here" }, () => {
      void chrome.runtime.lastError;
      setTimeout(() => { b.textContent = "Open in QuantiSheet"; }, 4000);
    });
  });
  x.addEventListener("click", () => host.remove());
  root.append(b, x);
  document.documentElement.appendChild(host);
}

// ---- the add-on's own viewer (Mozilla's PDF.js, viewer-qs.js) ----------
const VIEWER_URL = chrome.runtime.getURL("pdfjs/web/viewer.html");

// Takes the pieces of a PDF the way the program's line does, and keeps
// the PDF inside the add-on for its viewer page.
class Stash {
  constructor(url) {
    this.id = Date.now().toString(36) + Math.random().toString(36).slice(2);
    this.url = url;
    this.parts = [];
    this.name = "drawing.pdf";
  }

  async ask(msg) {
    if (msg.type === "begin") {
      this.parts = [];
      this.name = msg.name || this.name;
    } else if (msg.type === "data") {
      const bin = atob(msg.b64 || "");
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      this.parts.push(bytes);
    } else if (msg.type === "end") {
      if (!this.parts.length) return { ok: false };
      await stashPut(this.id, {
        name: this.name, url: this.url,
        blob: new Blob(this.parts, { type: "application/pdf" })
      });
      this.parts = [];
      return { ok: true, path: this.id };
    } else if (msg.type === "abort") {
      this.parts = [];
    }
    return { ok: true };
  }
}

// View here (popup): the PDF this tab is showing, in the add-on's viewer.
async function viewHere(url, title, tabId) {
  if (!canFetch(url)) {
    return { ok: false, why: "This page isn't a PDF on the web." };
  }
  const stash = new Stash(url);
  const name = pdfName(url, title);
  let r = { ok: false };
  if (tabId !== undefined && tabId >= 0 && chrome.scripting) {
    r = await viaTab(stash, tabId, name);
    if (!r.ok) await stash.ask({ type: "abort" });
  }
  if (!r.ok) r = await viaFetch(stash, directUrl(url), name);
  if (!r.ok) {
    return { ok: false, why: "This page isn't a PDF. Open the PDF itself " +
      "in the tab first." };
  }
  await new Promise((resolve) => chrome.tabs.update(
    tabId, { url: VIEWER_URL + "?id=" + stash.id },
    () => resolve(void chrome.runtime.lastError)));
  return { ok: true };
}

function onPdfShown(details) {
  if (details.tabId < 0 || !isPdfResponse(details.url,
                                          details.responseHeaders)) return;
  options().then((o) => {
    if (o.always || o.viewer) {
      // Back from the add-on's viewer lands on the PDF's own address
      // again: within half a minute that is left alone, so Back works
      const last = recent.get(details.tabId);
      if (last && last[0] === details.url && Date.now() - last[1] < 30000) {
        return;
      }
      recent.set(details.tabId, [details.url, Date.now()]);
      if (o.viewer) {
        chrome.tabs.update(details.tabId, {
          url: VIEWER_URL + "?src=" + encodeURIComponent(details.url)
        }, () => void chrome.runtime.lastError);
        return;
      }
      send(details.url, "", details.tabId, { own: true });
      return;
    }
    if (o.button && chrome.scripting) {
      // once the browser's own viewer is up
      setTimeout(() => {
        chrome.scripting.executeScript({
          target: { tabId: details.tabId }, func: pageButton
        }, () => void chrome.runtime.lastError);
      }, 800);
    }
  });
}

function listenForPdfs() {
  if (!chrome.webRequest || !chrome.webRequest.onHeadersReceived) return;
  if (chrome.webRequest.onHeadersReceived.hasListener(onPdfShown)) return;
  chrome.webRequest.onHeadersReceived.addListener(
    onPdfShown, { urls: ["http://*/*", "https://*/*"],
                  types: ["main_frame"] }, ["responseHeaders"]);
}

listenForPdfs();
chrome.permissions.onAdded.addListener(listenForPdfs);
chrome.tabs.onRemoved.addListener((id) => recent.delete(id));

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === "qs-open-here" && sender.tab) {
    send(sender.tab.url, sender.tab.title, sender.tab.id,
         { own: true }).then(reply);
    return true;
  }
  return false;
});
