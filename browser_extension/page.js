// Open in QuantiSheet: a web page as a PDF (Jon, Nov 25: "It also needs
// to work like adobe" - Web page to PDF).
//
// The browser itself makes the PDF, the same one its own Print > Save as
// PDF makes, and it goes down the direct line to QuantiSheet (direct.js).
// To ask the browser for that, the add-on needs the "debugger" access,
// which it asks for the first time this is used and uses for this one
// request on the one tab; the browser shows its own notice while it runs.
const PAGE_ACCESS = { permissions: ["debugger"] };

function pageName(url, title) {
  let host = "";
  try {
    host = new URL(url).hostname.replace(/^www\./, "");
  } catch (e) {
    host = "";
  }
  // pdfName keeps a ".pdf" address's own name; a page is named by title
  return pdfName("", (title || "").trim() || host || "web page");
}

// Stands in for the program's line: keeps the pieces and, at the end,
// has the browser save the PDF (saveHeld in sw.js).
class Held {
  constructor(tabId) {
    this.tabId = tabId;
    this.name = "web page.pdf";
    this.parts = [];
  }

  async ask(msg) {
    if (msg.type === "begin") {
      this.name = msg.name;
      this.parts = [];
    } else if (msg.type === "data") {
      this.parts.push(msg.b64);       // whole base64 pieces (see PIECE)
    } else if (msg.type === "end") {
      const url = "data:application/pdf;base64," + this.parts.join("");
      this.parts = [];
      return saveHeld(url, this.name, this.tabId);
    } else if (msg.type === "abort") {
      this.parts = [];
    }
    return { ok: true };
  }

  close() {}
}

async function pageToPdf(tabId, url, title) {
  if (!canFetch(url)) {
    return { ok: false, why: "Only a web page can be made into a PDF." };
  }
  if (!chrome.debugger) {
    return { ok: false, why: "The browser's OK is needed first: use " +
      "the add-on's toolbar button > Make this page a PDF." };
  }
  let line = new Line();
  const hello = await line.ask({ type: "hello" });
  if (hello && hello.off) {
    line.close();
    return { ok: false, why: OFF_BY_IT };
  }
  const held = !hello || !hello.ok;
  if (held) {
    // no direct line (the Store copy of QuantiSheet): keep the PDF and
    // let the browser save it, then hand the saved file over
    line.close();
    line = new Held(tabId);
  }
  const target = { tabId };
  try {
    await chrome.debugger.attach(target, "1.3");
  } catch (e) {
    line.close();
    return { ok: false, why: "The browser wouldn't let this page be " +
      "made into a PDF (its own pages and the add-on store can't be)." };
  }
  let out = { ok: false, why: "The page couldn't be made into a PDF." };
  try {
    const made = await chrome.debugger.sendCommand(target, "Page.printToPDF",
      { printBackground: true, preferCSSPageSize: true,
        transferMode: "ReturnAsStream" });
    let r = await line.ask({ type: "begin", name: pageName(url, title) });
    let eof = false;
    while (r && r.ok && !eof) {
      // a multiple of 3 bytes, so each piece is whole base64 on its own
      const part = await chrome.debugger.sendCommand(target, "IO.read",
        { handle: made.stream, size: PIECE });
      eof = !!part.eof;
      const data = part.base64Encoded ? part.data : btoa(part.data || "");
      if (data) r = await line.ask({ type: "data", b64: data });
    }
    chrome.debugger.sendCommand(target, "IO.close",
                                { handle: made.stream }).catch(() => {});
    if (r && r.ok) {
      r = await line.ask({ type: "end" });
      if (r && r.ok) out = held ? r : { ok: true, direct: true };
    }
    if (!out.ok) await line.ask({ type: "abort" });
  } catch (e) {
    await line.ask({ type: "abort" });
  }
  chrome.debugger.detach(target).catch(() => {});
  line.close();
  return out;
}
