// Open in QuantiSheet: what the add-on adds to Mozilla's PDF.js viewer
// page (Jon, Nov 27: view and mark up in the browser, option A).
//
// It opens the PDF the add-on was asked to show and puts one button on
// the toolbar, Open in QuantiSheet, which hands the PDF as it now is -
// highlights, drawings and text notes included - to the program on this
// computer. Nothing goes anywhere else.
(function () {
  const VIEWER = "pdfjs/web/viewer.html";
  let origin = { name: "drawing.pdf", url: "" };

  function setUp() {
    const o = window.PDFViewerApplicationOptions;
    o.set("defaultUrl", "");            // no sample document
    o.set("enableScripting", false);    // scripts inside a PDF never run
    o.set("isEvalSupported", false);
    o.set("externalLinkTarget", 2);     // links in a PDF open a new tab
    o.set("disableHistory", true);
    const app = window.PDFViewerApplication;
    app.initializedPromise.then(() => {
      addButton(app);
      return openAsked(app);
    }).catch((e) => console.error("viewer:", e));
  }

  async function openAsked(app) {
    const q = new URLSearchParams(location.search);
    const id = q.get("id");
    const src = q.get("src");
    if (id) {
      const rec = await stashGet(id);
      if (!rec) {
        say("This PDF is no longer kept by the add-on. Open it again " +
            "from its web page.");
        return;
      }
      origin = { name: rec.name, url: rec.url || "" };
      const data = new Uint8Array(await rec.blob.arrayBuffer());
      await app.open({ data, filename: rec.name });
      app.setTitleUsingUrl(rec.name, "");
    } else if (src && canFetch(src)) {
      origin = { name: pdfName(src, ""), url: src };
      await app.open({ url: src, withCredentials: true });
    }
  }

  function takeoffCount() {
    return window.QSTakeoff ? window.QSTakeoff.count() : 0;
  }

  // "1.1.38" is older than 1.1.39 (the first with browser takeoff)
  function olderThan(version, patch) {
    const p = String(version).split(".").map(Number);
    return p[0] === 1 && p[1] === 1 && p[2] < patch;
  }

  let noteEl = null;

  function say(text) {
    if (!noteEl) return;
    noteEl.textContent = text;
    noteEl.hidden = !text;
  }

  function addButton(app) {
    const right = document.getElementById("toolbarViewerRight");
    if (!right || document.getElementById("qsOpen")) return;
    const btn = document.createElement("button");
    btn.id = "qsOpen";
    btn.type = "button";
    btn.textContent = "Open in QuantiSheet";
    btn.title = "Open this PDF, with the marks made here, in QuantiSheet";
    btn.style.cssText = "margin:0 6px;padding:0 12px;height:28px;" +
      "border:0;border-radius:4px;background:#0e6a60;color:#fff;" +
      "font:600 13px system-ui,sans-serif;cursor:pointer;white-space:nowrap";
    noteEl = document.createElement("div");
    noteEl.id = "qsNote";
    noteEl.hidden = true;
    noteEl.style.cssText = "position:fixed;right:12px;top:40px;z-index:" +
      "100000;max-width:340px;padding:8px 12px;border-radius:6px;" +
      "background:#1d2b29;color:#fff;font:13px system-ui,sans-serif;" +
      "box-shadow:0 2px 10px rgba(0,0,0,.35)";
    document.body.appendChild(noteEl);
    btn.addEventListener("click", () => toApp(app, btn));
    right.insertBefore(btn, right.firstChild);
  }

  async function toApp(app, btn) {
    if (!app.pdfDocument) {
      say("No PDF is open here yet.");
      return;
    }
    btn.disabled = true;
    say("Sending to QuantiSheet...");
    let line = null;
    try {
      // the PDF as it is now: the marks made here are written into it
      const data = await app.pdfDocument.saveDocument();
      line = new Line();
      const hello = await line.ask({ type: "hello" });
      if (!hello || !hello.ok) {
        // no direct line (the Store copy of QuantiSheet): the browser
        // saves the PDF and the saved file is handed over
        const url = URL.createObjectURL(
          new Blob([data], { type: "application/pdf" }));
        const res = await new Promise((resolve) =>
          chrome.runtime.sendMessage(
            { type: "qs-save", url, name: origin.name },
            (x) => resolve(chrome.runtime.lastError ? null : x)));
        setTimeout(() => URL.revokeObjectURL(url), 120000);
        say(res && res.ok ? (takeoffCount() ? "The takeoff measured " +
          "here can't go along with this copy of QuantiSheet (it needs " +
          "the setup copy). " : "") + "Saving... If the browser asks " +
          "where to save, press Save. QuantiSheet opens when the " +
          "download finishes."
          : "The PDF couldn't be saved. Try again.");
        return;
      }
      let r = await line.ask({ type: "begin", name: origin.name });
      for (let at = 0; r && r.ok && at < data.length; at += PIECE) {
        r = await line.ask({ type: "data",
                             b64: b64(data.subarray(at, at + PIECE)) });
      }
      // takeoff clicked out here goes along as clicks and scales;
      // QuantiSheet works out the quantities (app/webmarks.py)
      const marks = takeoffCount() ? window.QSTakeoff.data() : null;
      if (r && r.ok) {
        r = await line.ask(marks ? { type: "end", marks } : { type: "end" });
      }
      const newer = marks && hello.version && olderThan(hello.version, 39);
      say(!(r && r.ok) ? "QuantiSheet didn't take the PDF. Try again."
        : newer ? "Sent, but the takeoff needs QuantiSheet 1.1.39 or " +
          "newer: this one only got the PDF."
          : marks ? "Sent with " + takeoffCount() + " takeoff " +
            "measurement(s). QuantiSheet is working out the quantities."
            : "Sent. It is opening in QuantiSheet.");
      if (r && r.ok) setTimeout(() => say(""), 6000);
    } catch (e) {
      say("That didn't work: " + (e && e.message ? e.message : e));
    } finally {
      if (line) line.close();
      btn.disabled = false;
    }
  }

  document.addEventListener("webviewerloaded", setUp);
  window.__qsViewer = { VIEWER };
})();
