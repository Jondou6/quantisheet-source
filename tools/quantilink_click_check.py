"""Click through Send with QuantiLink the way a user would, against the
QuantiLink on this PC. It starts its own test copy of the server on
127.0.0.1:8091 with the made-up test data (Desktop\\QuantiLink\\
data-test-run, made by tools/quantilink_local.py setup) and stops it
afterwards, so the office's own QuantiLink data is never touched.
Nov 25 optimization list: "Click-through test of Send with QuantiLink".

    python tools/quantilink_click_check.py

Everything is made up and kept in a temporary folder: a made-up job with
two RFIs (one with an attachment) and a daily log, a drawing in that job,
and QuantiSheet settings of its own (never this PC's real settings). It
opens the main window, sets the connection in the Connection window
(Load Folders, pick the folder, OK), presses Home > QuantiLink, ticks an
RFI or two, presses Send, waits for the share link, opens the link, presses Copy
Links, then sends the daily log too. The access key and the share links'
tokens are never printed."""
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _hide(link):
    return link.rsplit("/", 1)[0] + "/<token>" if "/s/" in link else link


def _wait(app, cond, secs=90):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


def _pdf(path, words):
    import fitz
    d = fitz.open()
    d.new_page().insert_text((72, 72), words)
    d.save(path)
    d.close()
    return path


PORT = 8091


def _test_server():
    """Start the test copy of QuantiLink; returns (process, login)."""
    import subprocess
    import quantilink_local as qll
    folder = qll._default_folder()
    data = os.path.join(os.path.dirname(folder), "data-test-run")
    with open(os.path.join(data, "test-login.json")) as f:
        login = json.load(f)
    url = f"http://127.0.0.1:{PORT}"
    login["url"] = url
    env = dict(os.environ, HOST="127.0.0.1", PORT=str(PORT),
               QUANTILINK_DATA=data)
    env.pop("QUANTILINK_BACKUP_DIR", None)
    log = open(os.path.join(data, "click-check-server.log"), "ab")
    p = subprocess.Popen(["node", "server.js"], cwd=folder, env=env,
                         stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL,
                         creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
    for _ in range(60):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=3) as r:
                if r.status == 200:
                    return p, login
        except Exception:                                 # noqa: BLE001
            pass
    p.kill()
    sys.exit("the test QuantiLink server didn't start (see "
             "data-test-run\\click-check-server.log)")


def main():
    srv, login = _test_server()
    print("0. test QuantiLink server on", login["url"], "(made-up data)")
    tmp = tempfile.mkdtemp(prefix="qs-ql-click-")
    try:
        run(tmp, login)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        srv.kill()
        print("   test server stopped")


def run(tmp, login):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    app = QApplication.instance() or QApplication([])
    from app import settings, toolchest
    settings.DIR = os.path.join(tmp, "cfg")
    settings.PATH = os.path.join(settings.DIR, "settings.json")
    settings._cache = None
    toolchest.PATH = os.path.join(settings.DIR, "tc.json")
    for name in ("information", "warning", "about"):
        setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    from app.pm.store import ProjectStore
    from app import quantilink as ql, quantilink_ui
    job = os.path.join(tmp, "Made-up Test Clinic")
    os.makedirs(job)
    s = ProjectStore(job)
    att = _pdf(os.path.join(tmp, "sketch.pdf"), "Made-up sketch")
    s.save_record("rfi", {"subject": "Roof drain location", "status": "Open",
                          "question": "Confirm the roof drain at grid C-4.",
                          "attachments": [s.attach(att)]})
    s.save_record("rfi", {"subject": "Door swing at 104", "status": "Closed",
                          "question": "Which way does door 104 swing?"})
    s.save_record("daily", {"date": "2026-11-25", "weather": "Clear",
                            "notes": "Made-up daily log for a test."})
    s.flush() if hasattr(s, "flush") else None
    drawing = _pdf(os.path.join(job, "A-101 Made-up Plan.pdf"),
                   "Made-up floor plan")

    from app.main_window import MainWindow
    win = MainWindow()
    win.resize(1200, 900)
    assert win.open_path(drawing), "couldn't open the made-up drawing"
    app.processEvents()
    print("1. main window open with a drawing from a made-up job")

    # the Connection window, as a user fills it in
    d = quantilink_ui.ConnectionDialog(win)
    d.url.setText(login["url"])
    d.key.setText(login["token"])
    d.load_btn.click()
    ok = _wait(app, lambda: d.space.count() > 0, 30)
    print("2. Connection > Load Folders:", d.space.count(), "folder(s)",
          "" if ok else "- none loaded: " + d.status.text())
    if not ok:
        sys.exit(1)
    d.space.setCurrentIndex(0)
    d.save()
    c = ql.connection()
    print("   saved:", c["url"], "->", c["space"].get("name"),
          "(key kept encrypted)" if c["key"] else "(no key!)")

    # Home > QuantiLink
    act = win.command("Send with QuantiLink")
    from app import quickaccess
    where = quickaccess.where_is(win, act)
    print("3. Home > QuantiLink button:", "found on the " + where[1] +
          " tab" if where else "NOT FOUND")
    act.trigger()
    app.processEvents()
    dlg = win.findChildren(quantilink_ui.SendDialog)
    if not dlg:
        print("   the button opened no window; opening it directly:")
        dlg = [win.send_quantilink()]
    dlg = dlg[-1]
    print("   window open; project:", dlg.store.name if dlg.store else None,
          "; RFIs listed:", dlg.list.count())

    for i in range(dlg.list.count()):           # both RFIs, one with a
        dlg.list.item(i).setCheckState(Qt.Checked)  # sketch attached
    dlg.attach.setChecked(True)
    dlg.send_btn.click()
    done = _wait(app, lambda: dlg.status.text().startswith("Sent"), 90)
    print("4. Send:", dlg.status.text() if done else "timed out")
    links = [r["link"] for r in dlg.results if r.get("link")]
    for r in dlg.results:
        print("   ", r.get("name"), "->",
              _hide(r["link"]) if r.get("link") else r.get("error"))
    if not links:
        sys.exit(1)
    st = urllib.request.urlopen(links[0], timeout=15).status
    print("5. first share link opens: HTTP", st)
    dlg.copy_btn.click()
    clip = QGuiApplication.clipboard().text()
    print("6. Copy Links:", "all links on the clipboard"
          if all(link in clip for link in links) else "MISSING from clipboard")

    i = dlg.kind.findData("daily")
    dlg.kind.setCurrentIndex(i)
    app.processEvents()
    dlg.tick_all(True)
    dlg.send_btn.click()
    done = _wait(app, lambda: dlg.status.text().startswith("Sent"), 90)
    print("7. Daily log:", dlg.status.text() if done else "timed out")
    for r in dlg.results:
        print("   ", r.get("name"), "->",
              _hide(r["link"]) if r.get("link") else r.get("error"))
    left = [n for n in os.listdir(tempfile.gettempdir())
            if n.startswith("quantisheet-") and
            os.path.getmtime(os.path.join(tempfile.gettempdir(), n)) >
            time.time() - 300]
    print("8. temporary send files left behind:", len(left))
    # who sent it (Nov 25): QuantiLink's record of an upload names the
    # sender when one shared key is used
    c = ql.connection()
    got = ql.Client(c["url"], c["key"]).upload(
        c["space"]["id"], "Made-up Test Clinic/Who sent it.txt",
        b"made-up", "text/plain")
    said = json.dumps(got)
    who = ql.sender_name()
    print("9. QuantiLink's record names the sender:",
          ("Sent from QuantiSheet by " + who) in said if who else
          "no sender name set", "| record fields:", sorted(got)[:12])
    dlg.close()
    win._view.dirty = False if win._view is not None else None
    win.close()
    good = done and links and st == 200
    print("CLICK-THROUGH", "PASSED" if good else "FAILED")
    if not good:
        sys.exit(1)


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    main()
