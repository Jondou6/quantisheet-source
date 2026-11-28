"""Try the browser add-on in the real Brave on this PC, in a throw-away
profile (nothing of the user's own browser profile is read or changed).

    python tools/diag_addon_brave.py [url]

Starts Brave with an empty temporary profile and the add-on from
browser_extension\\ (a temporary copy that is given site access up front,
because nobody is there to click the toolbar button), opens the PDF in a
tab, asks the add-on to send it, and prints what the browser reported for
each download and whether the hand-off page opened. Closes that Brave."""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 9557
URL = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"


SOURCE_HOST = False
PAGE = False
VIEW = False
TAKEOFF = False
KEYS = (r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts"
        r"\com.quantisheet.open",
        r"Software\Google\Chrome\NativeMessagingHosts\com.quantisheet.open")


def source_host(tmp):
    """Point the browser at the program run from source (before a build
    exists); returns the function that puts the registry back."""
    import winreg
    bat = os.path.join(tmp, "host.bat")
    py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    with open(bat, "w") as f:
        f.write(f'@echo off\r\n"{py}" "{os.path.join(ROOT, "quantisheet.py")}"'
                ' %*\r\n')
    with open(os.path.join(ROOT, "installer", "browser-host.json")) as f:
        m = json.load(f)
    m["path"] = bat
    mp = os.path.join(tmp, "host.json")
    with open(mp, "w") as f:
        json.dump(m, f)
    before = {}
    for key in KEYS:
        try:
            before[key] = winreg.QueryValue(winreg.HKEY_CURRENT_USER, key)
        except OSError:
            before[key] = None
        winreg.SetValue(winreg.HKEY_CURRENT_USER, key, winreg.REG_SZ, mp)

    def undo():
        for key, was in before.items():
            if was is None:
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
                except OSError:
                    pass
            else:
                winreg.SetValue(winreg.HKEY_CURRENT_USER, key,
                                winreg.REG_SZ, was)
    return undo


def newest_saved():
    sys.path.insert(0, ROOT)
    from app import browserhost
    d = browserhost.folder()
    try:
        names = [n for n in os.listdir(d) if n.lower().endswith(".pdf")]
    except OSError:
        return "no folder"
    if not names:
        return "nothing"
    n = max(names, key=lambda n: os.path.getmtime(os.path.join(d, n)))
    st = os.stat(os.path.join(d, n))
    pages = ""
    try:
        import fitz
        with fitz.open(os.path.join(d, n)) as doc:
            pages = f", {doc.page_count} page(s), first words: " + \
                " ".join(doc[0].get_text().split()[:6])
    except Exception as e:                                # noqa: BLE001
        pages = f", unreadable: {e}"
    return (f"{n} ({st.st_size} bytes, {int(time.time() - st.st_mtime)} s "
            f"ago{pages})")


class WS:
    """Just enough WebSocket for the browser's debugging port."""

    def __init__(self, url):
        rest = url.split("://", 1)[1]
        host, path = rest.split("/", 1)
        h, p = host.split(":")
        self.s = socket.create_connection((h, int(p)), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host}\r\n"
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\n"
                        "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self.n = 0

    def _read(self, n):
        out = b""
        while len(out) < n:
            got = self.s.recv(n - len(out))
            if not got:
                raise ConnectionError("closed")
            out += got
        return out

    def recv(self):
        data = b""
        while True:
            b1, b2 = self._read(2)
            n = b2 & 127
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            data += self._read(n)
            if b1 & 0x80:
                return json.loads(data.decode("utf-8", "replace"))

    def call(self, method, **params):
        self.n += 1
        msg = json.dumps({"id": self.n, "method": method,
                          "params": params}).encode()
        mask = os.urandom(4)
        head = b"\x81"
        if len(msg) < 126:
            head += bytes([0x80 | len(msg)])
        elif len(msg) < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", len(msg))
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", len(msg))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4]
                                           for i, b in enumerate(msg)))
        while True:
            got = self.recv()
            if got.get("id") == self.n:
                return got.get("result") or got

    def js(self, code):
        r = self.call("Runtime.evaluate", expression=code,
                      awaitPromise=True, returnByValue=True)
        res = r.get("result", {})
        return res.get("value", res.get("description", r))


def targets():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json",
                                timeout=5) as r:
        return json.load(r)


def main(argv):
    global SOURCE_HOST, PAGE, VIEW
    global TAKEOFF
    if argv[:1] == ["takeoff"]:
        TAKEOFF = True
        argv = ["view"] + argv[1:]
    if argv[:1] == ["view"]:
        VIEW = True
        argv = argv[1:]
    if argv[:1] == ["page"]:
        PAGE = True
        argv = argv[1:] or ["https://example.com/"]
    if argv[:1] == ["source-host"]:
        SOURCE_HOST = True
        argv = argv[1:]
    if argv[:1] == ["slow"]:
        os.environ["QS_WAIT"] = "70"
        argv = argv[1:]
    url = argv[0] if argv else URL
    brave = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                         "BraveSoftware", "Brave-Browser", "Application",
                         "brave.exe")
    if not os.path.isfile(brave):
        print("Brave not found")
        return 1
    tmp = tempfile.mkdtemp(prefix="qs-addon-")
    ext = os.path.join(tmp, "ext")
    shutil.copytree(os.path.join(ROOT, "browser_extension"), ext)
    mp = os.path.join(ext, "manifest.json")
    with open(mp, encoding="utf-8") as f:
        m = json.load(f)
    m["permissions"] += m.pop("optional_permissions", [])
    m["host_permissions"] = m.pop("optional_host_permissions", [])
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(m, f)
    print("add-on", m["version"], "in a throw-away Brave profile")
    undo = source_host(tmp) if SOURCE_HOST else (lambda: None)
    p = subprocess.Popen([
        brave, f"--user-data-dir={os.path.join(tmp, 'profile')}",
        f"--load-extension={ext}", f"--remote-debugging-port={PORT}",
        "--remote-allow-origins=*", "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=DisableLoadExtensionCommandLineSwitch",
        "about:blank"])
    try:
        return run(url)
    finally:
        p.terminate()
        time.sleep(2)
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                       capture_output=True)
        time.sleep(1)
        undo()
        shutil.rmtree(tmp, ignore_errors=True)


def run(url):
    sw = None
    for _ in range(40):
        time.sleep(0.5)
        try:
            ts = targets()
        except OSError:
            continue
        sw = next((t for t in ts if t["type"] == "service_worker"
                   and t["url"].endswith("/sw.js")), None)
        if sw:
            break
    if not sw:
        print("the add-on did not load in Brave (targets:",
              sorted({t["type"] for t in ts}) if 'ts' in dir() else None, ")")
        return 1
    w = WS(sw["webSocketDebuggerUrl"])
    w.js("""globalThis.__log = [];
      chrome.downloads.onChanged.addListener((d) => {
        if (d.state || d.error || d.filename) __log.push(JSON.stringify(d));
      }); 1""")
    # the PDF in a tab, as the user has it
    urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{PORT}/json/new?" + url, method="PUT"),
        timeout=10).read()
    time.sleep(6)
    tab = w.js("chrome.tabs.query({}).then(a => { const t = a.find(x => "
               "(x.url || '').startsWith(%s)); return t ? t.id : -1; })"
               % json.dumps(url[:40]))
    print("PDF tab id:", tab)
    for label, opts in (("the add-on's own download, then the tab's copy",
                         "{ own: true }"),):
        w.js("__log.length = 0; 1")
        if VIEW:
            label = "view here, then Open in QuantiSheet from the viewer"
            r = w.js("viewHere(%s, 'made-up title', %s)"
                     % (json.dumps(url), tab))
            time.sleep(6)
            vt = next((t for t in targets() if "viewer.html" in t["url"]
                       and t["type"] == "page"), None)
            if vt:
                v = WS(vt["webSocketDebuggerUrl"])
                print("   viewer:", v.js(
                    "JSON.stringify({pages: PDFViewerApplication.pagesCount,"
                    " title: document.title, button: !!document."
                    "getElementById('qsOpen'), tools: ['editorHighlightButton',"
                    "'editorFreeTextButton','editorInkButton'].map(i => "
                    "!document.getElementById(i).disabled)})"))
                if TAKEOFF:
                    # the made-up clicks of tests/test_webmarks.py: at
                    # 1/4 inch to the foot, 10 ft, 100 sq ft, 2 counts
                    v.js("sessionStorage.setItem('qs-takeoff:' + "
                         "location.search, JSON.stringify({scales: {}, "
                         "everyPage: {ppu: 18, unit: 'ft', name: '1/4 in'},"
                         " marks: [{page: 0, type: 'length', group: 'Walls',"
                         " pts: [[72, 700], [252, 700]]}, {page: 0, type: "
                         "'area', group: 'Slab', pts: [[72, 400], [252, 400],"
                         " [252, 580], [72, 580]]}, {page: 0, type: 'count',"
                         " group: 'Doors', pts: [[300, 300]]}, {page: 0, "
                         "type: 'count', group: 'Doors', pts: [[330, 300]]}"
                         "]})); location.reload(); 1")
                    time.sleep(6)
                    v = WS(vt["webSocketDebuggerUrl"])
                    print("   takeoff kept in the viewer:",
                          v.js("window.QSTakeoff.count()"))
                v.js("document.getElementById('qsOpen').click(); 1")
                time.sleep(5)
                print("   after its button:", v.js(
                    "document.getElementById('qsNote').textContent"))
                r = dict(r or {}, direct=True)
            else:
                print("   the viewer page did not open")
        elif PAGE:
            label = "web page to PDF"
            r = w.js("pageToPdf(%s, %s, 'Made-up page test')"
                     % (tab, json.dumps(url)))
        else:
            r = w.js("send(%s, 'made-up title', %s, %s)"
                     % (json.dumps(url), tab, opts))
        print(label + ":", r)
        hand = None
        for _ in range(0 if isinstance(r, dict) and r.get("direct") else int(os.environ.get('QS_WAIT', '30'))):
            time.sleep(0.5)
            hand = next((t["url"] for t in targets()
                         if "open.html" in t["url"]), None)
            if hand:
                break
        for ln in w.js("__log") or []:
            d = json.loads(ln)
            print("   download", d.get("id"),
                  {k: v.get("current") for k, v in d.items()
                   if isinstance(v, dict)})
        items = w.js("chrome.downloads.search({}).then(a => a.map(i => "
                     "[i.filename.split('\\\\').slice(-2).join('\\\\'), "
                     "i.mime, i.state, i.error || '', i.bytesReceived, i.danger, "
                     "i.paused, i.byExtensionName || '']))")
        for it in items or []:
            print("   listed:", it)
        print("   watching for the next download:",
              w.js("chrome.storage.session.get('watch').then(g => !!g.watch)"))
        if isinstance(r, dict) and r.get("direct"):
            time.sleep(5)             # let the program start before we go
        print("   newest PDF in Downloads\\QuantiSheet:", newest_saved())
        if hand:
            from urllib.parse import unquote
            path = unquote(hand.split("path=", 1)[1])
            print("   HAND-OFF PAGE OPENED for",
                  os.path.join(*path.split(os.sep)[-2:]),
                  "| file exists:", os.path.isfile(path))
        else:
            print("   no hand-off page")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
