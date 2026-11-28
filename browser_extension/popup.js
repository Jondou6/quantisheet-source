// Open in QuantiSheet: the toolbar button's small window.
const go = document.getElementById("go");
const next = document.getElementById("next");
const nameEl = document.getElementById("name");
const note = document.getElementById("note");

document.getElementById("ver").textContent =
  chrome.runtime.getManifest().version;

const WAITING = "Now click the site's own Download button. The next PDF " +
  "you download opens in QuantiSheet (for the next 3 minutes).";

// No answer from the add-on's background part: it was updated but not
// reloaded (or is restarting). Say so instead of doing nothing.
function noAnswer() {
  if (!chrome.runtime.lastError) return false;
  note.textContent = "The add-on needs reloading: open your browser's " +
    "Extensions page, click the reload arrow on Open in QuantiSheet, " +
    "then try again.";
  go.disabled = false;
  return true;
}

function showWaiting(tab) {
  nameEl.textContent = "Waiting for your download";
  note.textContent = WAITING;
  go.hidden = true;
  next.textContent = "Stop waiting";
  next.onclick = () => {
    chrome.runtime.sendMessage({ type: "qs-stop", tabId: tab.id },
                               () => { void chrome.runtime.lastError;
                                       window.close(); });
  };
}

chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const tab = tabs && tabs[0];
  if (!tab) return;
  next.onclick = () => {
    chrome.runtime.sendMessage({ type: "qs-watch", tabId: tab.id },
                               () => { if (!noAnswer()) showWaiting(tab); });
  };
  // an add-on that was updated but not reloaded has no storage yet:
  // the main button must still work
  const store = chrome.storage && chrome.storage.session;
  if (!store) next.hidden = true;
  const getWatch = (cb) => store ? store.get("watch", cb) : cb({});
  getWatch((got) => {
    const w = got && got.watch;
    if (w && Date.now() <= w.until) {
      showWaiting(tab);
      return;
    }
    if (!canFetch(tab.url)) {
      nameEl.textContent = "This page isn't a PDF on the web.";
      note.textContent = "Open a plan PDF in this tab, right-click a " +
        "link to a PDF, or use the button below and then download the " +
        "PDF from the site.";
      go.disabled = true;
      return;
    }
    nameEl.textContent = pdfName(tab.url, tab.title);
    go.addEventListener("click", () => {
      go.disabled = true;
      note.textContent = "Sending to QuantiSheet...";
      chrome.runtime.sendMessage(
        { type: "qs-open", url: tab.url, title: tab.title, tabId: tab.id },
        (res) => {
          if (noAnswer()) return;
          if (res && res.ok && res.direct) {
            note.textContent = "Sent. It is opening in QuantiSheet.";
            return;
          }
          if (res && res.ok) {
            note.textContent = "Saving... If the browser asks where " +
              "to save, press Save. QuantiSheet opens when the " +
              "download finishes. If this site shows the PDF inside a " +
              "page, click the site's own Download button next: that " +
              "PDF opens in QuantiSheet.";
          } else {
            note.textContent = (res && res.why) || "That didn't work.";
            go.disabled = false;
          }
        });
    });
  });
});

// ---- View here: the PDF in the add-on's own viewer, to mark it up
const viewBtn = document.getElementById("view");
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const tab = tabs && tabs[0];
  if (!tab || !canFetch(tab.url)) {
    viewBtn.hidden = true;
    return;
  }
  viewBtn.addEventListener("click", () => {
    viewBtn.disabled = true;
    note.textContent = "Opening the viewer...";
    chrome.runtime.sendMessage(
      { type: "qs-view", url: tab.url, title: tab.title, tabId: tab.id },
      (res) => {
        if (noAnswer()) return;
        if (res && res.ok) {
          window.close();
          return;
        }
        viewBtn.disabled = false;
        note.textContent = (res && res.why) || "That didn't work.";
      });
  });
});

// ---- a web page as a PDF: the browser makes it, QuantiSheet opens it
const pageBtn = document.getElementById("page");
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const tab = tabs && tabs[0];
  if (!tab || !canFetch(tab.url)) {
    pageBtn.hidden = true;
    return;
  }
  pageBtn.addEventListener("click", () => {
    // asked for on this click, the first time only
    chrome.permissions.request({ permissions: ["debugger"] }, (ok) => {
      void chrome.runtime.lastError;
      if (!ok) {
        note.textContent = "That needs your OK so the browser can make " +
          "the PDF. Nothing was changed.";
        return;
      }
      pageBtn.disabled = true;
      note.textContent = "Making the PDF...";
      chrome.runtime.sendMessage(
        { type: "qs-page", url: tab.url, title: tab.title, tabId: tab.id },
        (res) => {
          if (noAnswer()) return;
          pageBtn.disabled = false;
          note.textContent = res && res.ok && res.saved
            ? "Saving the PDF... If the browser asks where to save, " +
              "press Save. QuantiSheet opens when the download finishes."
            : res && res.ok
              ? "Done. The page is opening in QuantiSheet as a PDF."
              : (res && res.why) || "That didn't work.";
        });
    });
  });
});

// ---- the two options: each needs the browser's OK to see which pages
// are PDFs, asked for here, when the box is ticked
const boxes = { button: document.getElementById("opt-button"),
                always: document.getElementById("opt-always"),
                viewer: document.getElementById("opt-viewer") };
const local = chrome.storage && chrome.storage.local;

function loadOptions() {
  if (!local) {
    document.getElementById("opts").hidden = true;
    return;
  }
  local.get("options", (got) => {
    const o = Object.assign({}, OPTIONS, got && got.options);
    chrome.permissions.contains(SITES, (has) => {
      boxes.button.checked = !!(has && o.button);
      boxes.always.checked = !!(has && o.always);
      boxes.viewer.checked = !!(has && o.viewer && !o.always);
    });
  });
}

function saveOptions() {
  const o = { button: boxes.button.checked, always: boxes.always.checked,
              viewer: boxes.viewer.checked };
  local.set({ options: o });
  if (!o.button && !o.always && !o.viewer) {
    chrome.permissions.remove(SITES, () => void chrome.runtime.lastError);
  }
}

// a PDF can go to one place: always to QuantiSheet, or the viewer here
const OTHER = { always: "viewer", viewer: "always" };

for (const key of ["button", "always", "viewer"]) {
  boxes[key].addEventListener("change", () => {
    if (boxes[key].checked && OTHER[key]) boxes[OTHER[key]].checked = false;
    if (!boxes[key].checked) {
      saveOptions();
      return;
    }
    chrome.permissions.request(SITES, (ok) => {
      if (!ok) {
        boxes[key].checked = false;
        note.textContent = "That needs your OK to see which pages are " +
          "PDFs. Nothing was changed.";
      }
      saveOptions();
    });
  });
}
loadOptions();
