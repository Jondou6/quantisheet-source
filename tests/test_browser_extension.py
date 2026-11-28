"""The browser add-on "Open in QuantiSheet" (browser_extension/): Manifest
V3, the fewest permissions, no remote code, and its file-name and hand-off
rules (run with Node.js when it is installed)."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT = os.path.join(ROOT, "browser_extension")


def _read(name):
    with open(os.path.join(EXT, name), encoding="utf-8") as f:
        return f.read()


def test_manifest_is_v3_with_the_fewest_permissions():
    m = json.loads(_read("manifest.json"))
    assert m["manifest_version"] == 3
    assert m["name"] == "Open in QuantiSheet"
    # scripting only ever runs in the tab the user clicked the add-on on
    # (activeTab), to save the PDF that tab is already showing
    # nativeMessaging: the direct line to QuantiSheet on this computer
    assert sorted(m["permissions"]) == [
        "activeTab", "contextMenus", "downloads", "nativeMessaging",
        "scripting", "storage"]
    assert "host_permissions" not in m and "content_scripts" not in m
    # seeing which pages are PDFs (the on-page button, "always open") is
    # asked for only when the user ticks one of those boxes
    # debugger: only for Make this page a PDF, asked for on first use
    assert m["optional_permissions"] == ["webRequest", "debugger"]
    assert m["optional_host_permissions"] == ["http://*/*", "https://*/*"]
    assert m["background"] == {"service_worker": "sw.js"}
    for size, rel in m["icons"].items():
        assert os.path.isfile(os.path.join(EXT, rel)), rel
    # store rules: no other company's product names in the listing text
    text = json.dumps(m)
    for bad in ("Adobe", "Acrobat", "Bluebeam", "Chrome", "Google"):
        assert bad not in text


def test_no_remote_code_and_nothing_sent_anywhere():
    for name in ("sw.js", "core.js", "direct.js", "page.js", "popup.js",
                 "popup.html", "open.js", "open.html", "viewer-qs.js",
                 "takeoff.js"):
        src = _read(name)
        assert "eval(" not in src and "new Function" not in src
        # the only fetches: the PDF's tab asking its own address for the
        # PDF it is already showing (grabPdf in sw.js)
        # the only fetches: the PDF's tab asking its own address for the
        # PDF it is showing, and the add-on asking for the one PDF the
        # user pointed at (direct.js viaFetch) - a GET, nothing sent
        own = src.count("fetch(location.href, ")
        assert own == {"sw.js": 2, "direct.js": 2}.get(name, 0)
        assert src.count("fetch(") - own == (1 if name == "direct.js"
                                             else 0)
        assert "method:" not in src and "body:" not in src
        assert "XMLHttpRequest" not in src
        assert not re.search(r"<script[^>]+src=[\"']https?:", src)
        # the only addresses in the code are the app's own link type
        for url in re.findall(r"[a-z]+://[^\s\"'<>)]+", src):
            assert url.startswith("quantisheet://") or \
                url in ("http://*/*", "https://*/*",
                        # the name of the drawing format, never fetched
                        "http://www.w3.org/2000/svg"), (name, url)


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_names_and_hand_off_rules():
    js = r"""
const c = require(process.argv[1]);
const out = {
  a: c.pdfName('https://x.example/plans/A-101%20Plan.PDF?x=1', ''),
  b: c.pdfName('https://x.example/view?id=7', 'Bid Set: Sheet 1/2'),
  c: c.pdfName('https://x.example/con.pdf', ''),
  d: c.pdfName('not a url', ''),
  web: [c.canFetch('https://a/b.pdf'), c.canFetch('file:///c:/a.pdf'),
        c.canFetch('chrome://settings'), c.canFetch('')],
  pdf: [c.isPdf({filename: 'C:\\a\\b.pdf', mime: 'application/pdf'}),
        c.isPdf({filename: 'C:\\a\\b.pdf', mime: 'text/html'}),
        c.isPdf({filename: 'C:\\a\\b.exe', mime: 'application/pdf'}),
        c.isPdf(null)],
  drop: [c.directUrl('https://www.dropbox.com/scl/fi/abc/Plan.pdf?rlkey=x&dl=0'),
         c.directUrl('https://www.dropbox.com/home/Jobs?preview=Plan.pdf'),
         c.directUrl('https://notdropbox.com/s/abc/Plan.pdf?dl=0'),
         c.directUrl('not a url')],
  watch: c.WATCH_MS,
  link: c.appLink('D:\\Made-up\\Downloads\\QuantiSheet\\A 1.pdf'),
};
console.log(JSON.stringify(out));
"""
    r = subprocess.run(["node", "-e", js, os.path.join(EXT, "core.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert o["a"] == "A-101 Plan.pdf"
    assert o["b"] == "Bid Set Sheet 1 2.pdf"
    assert o["c"] == "drawing.pdf" and o["d"] == "drawing.pdf"
    assert o["web"] == [True, False, False, False]
    assert o["pdf"] == [True, False, False, False]
    # a Dropbox shared link is fetched as the file itself; nothing else
    # is rewritten
    assert o["drop"] == [
        "https://www.dropbox.com/scl/fi/abc/Plan.pdf?rlkey=x&dl=1",
        "https://www.dropbox.com/home/Jobs?preview=Plan.pdf",
        "https://notdropbox.com/s/abc/Plan.pdf?dl=0", "not a url"]
    assert o["watch"] == 180000
    assert o["link"] == ("quantisheet://open?path=D%3A%5CMade-up"
                         "%5CDownloads%5CQuantiSheet%5CA%201.pdf")
    # and QuantiSheet reads that same link back to the same path
    from urllib.parse import parse_qs, urlsplit
    assert parse_qs(urlsplit(o["link"]).query)["path"] == [
        "D:\\Made-up\\Downloads\\QuantiSheet\\A 1.pdf"]


def test_a_page_that_is_not_a_pdf_is_thrown_away_and_the_next_download_opens():
    """Nov 25 (Jon tried a Dropbox preview page: the site sent an error
    page, saved as .htm): the junk file is removed and the add-on waits
    for the user's own download from the site."""
    sw = _read("sw.js")
    assert "chrome.downloads.removeFile(delta.id" in sw
    assert "chrome.downloads.erase({ id: delta.id })" in sw
    assert sw.count("fromTab(mine.tabId, ") >= 2
    assert "return watch(tabId).then(" in sw
    # the wait is kept for this browser session only (the two on/off
    # options are the only thing kept longer)
    assert 'chrome.storage.session.set({\n    watch:' in sw
    assert "Open my next PDF download instead" in _read("popup.html")
    assert "site's own Download button" in _read("popup.js")


def test_hand_off_goes_through_the_add_ons_own_page():
    """Nov 25 (Jon, Brave: the PDF saved but QuantiSheet never opened):
    the worker opens open.html, which opens the quantisheet:// link and
    has a button for a browser that wants a click."""
    sw = _read("sw.js")
    assert 'chrome.runtime.getURL("open.html")' in sw
    # the hand-off to the program never navigates a tab to the link
    # (the only tabs.update calls open the add-on's own viewer page)
    assert sw.count("chrome.tabs.update(") == 2
    assert sw.count("VIEWER_URL + ") == 2
    o = _read("open.js")
    assert "appLink(path)" in o and "location.href = link" in o
    assert 'id="go"' in _read("open.html")


def test_options_are_off_until_ticked():
    core = _read("core.js")
    assert ("const OPTIONS = { button: false, always: false, "
            "viewer: false };") in core
    pop = _read("popup.js")
    assert "chrome.permissions.request(SITES" in pop
    assert "chrome.permissions.remove(SITES" in pop
    sw = _read("sw.js")
    assert 'types: ["main_frame"]' in sw and "isPdfResponse(" in sw


def test_its_own_downloads_are_remembered_while_the_worker_sleeps():
    """Nov 25: the browser may stop the background worker while a big
    plan set is still downloading; what was only in memory was lost and
    the finished PDF never opened. Tried in a test browser: worker memory
    cleared mid-download, the hand-off page still opened."""
    sw = _read("sw.js")
    assert "function remember(id, tabId, job)" in sw
    assert "function takeMine(id)" in sw
    assert 'chrome.storage.session.get("mine"' in sw
    assert "remember(id, tabId, { url, title, place, own })" in sw
    assert "waiting.set(id, tabId);\n      resolve" not in sw


def test_a_folder_the_browser_may_not_write_to_is_not_the_end():
    """Nov 25 (Jon: "Needs permission to download", nothing opened): when
    the browser can't write into Downloads\\QuantiSheet the add-on saves
    straight into Downloads, and after that asks where. Tried in a test
    browser with a made-up refusal."""
    sw = _read("sw.js")
    assert 'const PLACES = ["folder", "downloads", "ask"];' in sw
    assert "cannotWrite(why) && next" in sw
    assert 'saveAs: place === "ask"' in sw
    assert 'if (why === "USER_CANCELED" || job.held) return;' in sw
    core = _read("core.js")
    assert "function cannotWrite(error)" in core
    assert "FILE_(ACCESS_DENIED|" in core


def test_a_website_that_refuses_a_second_download_still_works():
    """Nov 25 (Jon and Chief: "Needs permission to download", nothing
    opened): the website refused to send the PDF again to the add-on's
    own download. The copy the tab is already showing is saved instead,
    as an ordinary download, and that one opens. Tried in a test browser
    against a made-up site that answers 403 (and one that answers with a
    "checking your browser" page) to anything but the tab itself."""
    sw = _read("sw.js")
    assert "async function grabPdf(name)" in sw
    assert 'cache: "force-cache"' in sw
    assert "a.download = name;" in sw
    assert "func: grabPdf" in sw
    assert "!job.own" in sw               # never for a link on a page
    # the add-on's own page message, the on-page button, "always open"
    # and the page menu are the tab's own address; a link is not
    assert sw.count("own: true") >= 3
    assert "info.menuItemId !== MENU_LINK && !info.frameUrl" in sw
    # nothing in the grab sends anything anywhere but back to the page's
    # own address
    grab = sw[sw.index("async function grabPdf"):sw.index("function fromTab")]
    assert grab.count("fetch(") == 2 and grab.count("location.href") == 2
    assert "XMLHttpRequest" not in sw and "sendBeacon" not in sw


def test_the_pdf_goes_straight_to_the_program_first():
    """Nov 26 (Jon, Brave: every download the add-on started brought up
    the browser's Save As window; seen on his PC). The PDF is handed to
    QuantiSheet over the browser's native messaging, from the tab's own
    copy first; the download way is only for a QuantiSheet without it.
    Tried in a test browser both with and without the program's side."""
    sw = _read("sw.js")
    assert 'importScripts("core.js", "direct.js", "page.js");' in sw
    assert sw.index("direct(url, title, tabId, own)") < \
        sw.index("chrome.downloads.download(")
    d = _read("direct.js")
    core = _read("core.js")           # shared with the viewer page
    assert 'const HOST = "com.quantisheet.open";' in core
    assert "chrome.runtime.connectNative(HOST)" in core
    # the tab's copy first, then the add-on's own request
    assert d.index("r = await viaTab(line, tabId, name);") < \
        d.index("r = await viaFetch(line, directUrl(url), name);")
    # a page that is not a PDF is never sent to the program
    assert "if (!looksPdf(held)) return false;" in d
    assert 'if (!pdf) throw new Error("not a PDF");' in d
    # only our own script in a tab may feed the line, three messages only
    assert "port.sender.id !== chrome.runtime.id" in d
    assert 'kind !== "begin" && kind !== "data" && kind !== "end"' in d
    assert "Sent. It is opening in QuantiSheet." in _read("popup.js")
    m = json.loads(_read("manifest.json"))
    assert len(m["key"]) > 300        # a fixed id: setup names it


def test_a_web_page_becomes_a_pdf_in_quantisheet():
    """Jon, Nov 25/26: "It also needs to work like adobe" - Web page to
    PDF. The browser makes the PDF (the one its own Print > Save as PDF
    makes) and it goes down the direct line. Tried in a test browser: a
    made-up 400-line page arrived as a 14-page PDF."""
    page = _read("page.js")
    assert '"Page.printToPDF"' in page and "printBackground: true" in page
    assert 'transferMode: "ReturnAsStream"' in page
    # the browser's debugger access: asked for on the user's click only,
    # one tab, let go of again whatever happens
    assert page.count("chrome.debugger.attach(target") == 1
    assert "chrome.debugger.detach(target)" in page
    used = set(re.findall(r'sendCommand\(target,\s*"([A-Za-z.]+)"', page))
    assert used == {"Page.printToPDF", "IO.read", "IO.close"}
    assert "Only a web page can be made into a PDF." in page
    pop = _read("popup.js")
    assert 'chrome.permissions.request({ permissions: ["debugger"] }' in pop
    assert 'id="page"' in _read("popup.html")
    sw = _read("sw.js")
    assert 'title: "Make this page a PDF in QuantiSheet"' in sw
    assert "chrome.permissions.request(PAGE_ACCESS" in sw
    assert "debugger" not in json.loads(_read("manifest.json"))["permissions"]


def test_view_and_mark_up_in_the_browser():
    """Jon, Nov 27: view and mark up in the browser, option A - a viewer
    with basic markup (Mozilla's PDF.js, Apache-2.0), opened by View here
    in the popup or, with a tick-box, for every PDF; Open in QuantiSheet
    on its toolbar sends the PDF with the marks made there. Tried in a
    test browser: a text note typed in the viewer arrived in the PDF."""
    m = json.loads(_read("manifest.json"))
    # the viewer decodes some images with WebAssembly; nothing else is
    # loosened, and no code comes from anywhere but the add-on itself
    assert m["content_security_policy"]["extension_pages"] == \
        "script-src 'self' 'wasm-unsafe-eval'; object-src 'self'"
    for part in ("pdfjs/LICENSE", "pdfjs/build/pdf.mjs",
                 "pdfjs/build/pdf.worker.mjs", "pdfjs/web/viewer.mjs",
                 "pdfjs/web/viewer.html", "pdfjs/web/viewer.css"):
        assert os.path.isfile(os.path.join(EXT, *part.split("/"))), part
    # not shipped: the PDF-script sandbox, the sample PDF, source maps
    names = [n for _b, _d, fs in os.walk(os.path.join(EXT, "pdfjs"))
             for n in fs]
    assert not [n for n in names if n.endswith((".map", ".pdf"))
                or "sandbox" in n or "debugger" in n]
    html = _read("pdfjs/web/viewer.html")
    assert html.index('src="../../viewer-qs.js"') < \
        html.index('src="viewer.mjs"')
    v = _read("viewer-qs.js")
    assert 'o.set("enableScripting", false);' in v   # PDF scripts never run
    assert 'o.set("defaultUrl", "");' in v
    assert "app.pdfDocument.saveDocument()" in v     # marks go along
    assert "new Line()" in v and "fetch(" not in v
    sw = _read("sw.js")
    assert 'msg.type === "qs-view"' in sw and "class Stash" in sw
    assert "if (o.viewer) {" in sw
    pop = _read("popup.js")
    assert 'const OTHER = { always: "viewer", viewer: "always" };' in pop
    page = _read("popup.html")
    assert page.index('id="go"') < page.index('id="view"') < \
        page.index('id="next"')
    assert 'id="opt-viewer"' in page


def test_a_note_made_in_the_browser_viewer_is_a_quantisheet_markup():
    """The question before building: do marks made in the browser show up
    in QuantiSheet as its own markups? Yes - both write standard PDF
    annotations. tests/data/browser_viewer_note.pdf is a made-up page
    with one text note typed in the add-on's viewer."""
    fitz = pytest.importorskip("fitz")
    from app import annotate
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    doc = fitz.open(os.path.join(root, "tests", "data",
                                 "browser_viewer_note.pdf"))
    page = doc[0]                    # kept: its annotations need it
    annots = list(page.annots())
    assert len(annots) == 1
    a = annots[0]
    assert annotate.friendly_type(a, doc=doc) == "Text Box"
    assert "check drain at C-4" in a.info["content"]
    doc.close()


def test_every_viewer_tool_arrives_as_a_quantisheet_markup():
    """Nov 27: highlight, draw, text note and image were each used in the
    add-on's viewer on a made-up page (tests/data/
    browser_viewer_marks.pdf) and sent; QuantiSheet names all four."""
    fitz = pytest.importorskip("fitz")
    from app import annotate
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    doc = fitz.open(os.path.join(root, "tests", "data",
                                 "browser_viewer_marks.pdf"))
    page = doc[0]
    kinds = sorted(annotate.friendly_type(a, doc=doc) for a in page.annots())
    assert kinds == ["Highlight", "Pen", "Stamp", "Text Box"]
    assert "Roof drain at grid C-4" in page.get_text()
    doc.close()


def test_without_the_direct_line_the_browser_saves_what_the_add_on_holds():
    """Nov 27: the Store copy of QuantiSheet has no direct line (Jon's
    decision). Make this page a PDF and the viewer's Open in QuantiSheet
    said "needs QuantiSheet 1.1.38 or newer", which was wrong for someone
    who has it. Now the browser saves the PDF the add-on holds and the
    saved file is handed over. Tried in a test browser with no program
    side: both ended at the hand-off page."""
    sw = _read("sw.js")
    assert "function saveHeld(url, name, tabId)" in sw
    # only the add-on's own viewer page may ask, and only for its own PDF
    assert '!String(sender.url || "").startsWith(VIEWER_URL)' in sw
    assert 'startsWith("blob:" + self.location.origin)' in sw
    assert 'if (why === "USER_CANCELED" || job.held) return;' in sw
    page = _read("page.js")
    assert "line = new Held(tabId);" in page
    assert '"data:application/pdf;base64," + this.parts.join("")' in page
    v = _read("viewer-qs.js")
    assert 'type: "qs-save"' in v
    for name in ("page.js", "viewer-qs.js", "popup.js"):
        assert "needs QuantiSheet 1.1.38" not in _read(name)
    assert "press Save" in v and "press Save" in _read("popup.js")


def test_takeoff_in_the_viewer_sends_clicks_not_quantities():
    """Jon, Nov 27 (option B): scale, length, area and count in the
    add-on's viewer. The browser shows a preview; what it sends is where
    the clicks were and the scale, and QuantiSheet works the quantities
    out (tests/test_webmarks.py), so a quantity comes from one place.
    Tried in a test browser: a 10 ft run, a 100 sq ft square and three
    counts were clicked out at 1/4 inch to the foot and arrived as
    exactly those points."""
    t = _read("takeoff.js")
    html = _read("pdfjs/web/viewer.html")
    assert html.index('src="../../viewer-qs.js"') < \
        html.index('src="../../takeoff.js"') < html.index('src="viewer.mjs"')
    i = t.index("function data()")
    sent = t[i:t.index("function keep()")]
    assert "page: m.page, type: m.type, group:" in sent
    assert "value" not in sent and "preview(" not in sent
    assert "Numbers here are a preview." in t
    v = _read("viewer-qs.js")
    assert '{ type: "end", marks }' in v
    assert "needs QuantiSheet 1.1.39" in v      # an older program: said so
    assert "can't go along with this copy" in v  # the Store copy: said so
    # no pop-up boxes (they are not shown in an add-on page)
    for word in ("alert(", "confirm(", "prompt("):
        assert word not in t


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_the_viewers_preview_agrees_with_quantisheets_figures():
    js = r"""
const t = require(process.argv[1]);
t.state.everyPage = { ppu: 18, unit: 'ft', name: 'quarter inch' };
t.state.marks = [
  { page: 0, type: 'length', pts: [[72, 700], [252, 700]], group: 'Walls' },
  { page: 0, type: 'area', group: 'Slab',
    pts: [[72, 400], [252, 400], [252, 580], [72, 580]] },
  { page: 2, type: 'count', pts: [[1, 1]], group: 'Doors' }];
const quarter = t.PRESETS.find((p) => p[0].startsWith('1/4'));
const d = t.data();
console.log(JSON.stringify({ totals: t.totals(), quarter,
  scales: d.scales, first: d.marks[0], keys: Object.keys(d.marks[1]) }));
"""
    r = subprocess.run(["node", "-e", js, os.path.join(EXT, "takeoff.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    # the same made-up clicks as tests/test_webmarks.py: 10 ft, 100 sq ft
    assert [(x["group"], x["value"], x["unit"]) for x in out["totals"]] == [
        ["Walls", 10, "ft"], ["Slab", 100, "sq ft"], ["Doors", 1, "ea"]] or \
        [[x["group"], x["value"], x["unit"]] for x in out["totals"]] == [
        ["Walls", 10, "ft"], ["Slab", 100, "sq ft"], ["Doors", 1, "ea"]]
    assert out["quarter"][1:] == [18, "ft"]
    assert out["scales"] == [{"page": 0, "all": True, "ppu": 18,
                              "unit": "ft", "name": "quarter inch"}]
    assert out["first"] == {"page": 0, "type": "length", "group": "Walls",
                            "pts": [[72, 700], [252, 700]]}
    assert sorted(out["keys"]) == ["group", "page", "pts", "type"]
