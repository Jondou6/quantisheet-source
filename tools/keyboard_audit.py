"""Keyboard-only audit (Nov 5): open the main windows and dialogs off
screen and list every control Tab can't reach (app/a11y.keyboard_audit).
Uses a throwaway settings folder; touches no real job.

python tools/keyboard_audit.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _throwaway_home():
    """Run as a program: point the home folders at a throwaway folder.
    Only main() does this - imported by a test, the test's own home stays
    (Chief, Nov 6: setting them at import leaked into later tests)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    home = tempfile.mkdtemp(prefix="qs_kbd_")
    for k in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        os.environ[k] = home
    return home


def windows():
    """(title, builder) for each window to check. Builders take the main
    window."""
    import importlib
    from app.service import menu as svc_menu
    out = []
    for e in svc_menu.ENTRIES:
        mod, fn = e["call"].rsplit(".", 1)
        out.append((e["label"], lambda _w, mod=mod, fn=fn:
                    getattr(importlib.import_module(mod), fn)()))
    out += [
        ("Contract & Billing", lambda w: w.billing()),
        ("Check Scan Quality", lambda w: w.scan_quality(languages=["eng"])),
        ("Local AI Models", lambda w: w.ai_models(
            fetch=lambda: (_ for _ in ()).throw(OSError("test")))),
        ("Practice Job", lambda w: __import__(
            "app.practice_job_ui", fromlist=["x"]).open_window(w)),
    ]
    return out


def run(win, report=print):
    from PySide6.QtWidgets import QApplication, QTabWidget
    from app import a11y
    found = {}
    for title, build in windows():
        try:
            dlg = build(win)
        except Exception as e:                            # noqa: BLE001
            found[title] = [("-", "-", f"couldn't open: {e}")]
            continue
        if dlg is None:
            found[title] = [("-", "-", "didn't open")]
            continue
        dlg.show()
        QApplication.processEvents()
        probs = []
        tabs = dlg.findChildren(QTabWidget)
        if tabs:
            for t in tabs:
                for i in range(t.count()):
                    t.setCurrentIndex(i)
                    QApplication.processEvents()
                    probs += [(c, n, f"{p} ({t.tabText(i)} tab)")
                              for c, n, p in a11y.keyboard_audit(dlg)]
        else:
            probs = a11y.keyboard_audit(dlg)
        found[title] = sorted(set(probs))
        dlg.close()
    for title, probs in found.items():
        report(f"{title}: {'OK' if not probs else len(probs)}")
        for p in probs:
            report(f"    {p[0]} {p[1]!r}: {p[2]}")
    return found


def main():
    home = _throwaway_home()
    import fitz
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from app.main_window import MainWindow
    w = MainWindow()
    path = os.path.join(home, "kbd.pdf")
    d = fitz.open()
    d.new_page().insert_text((72, 72), "Keyboard audit")
    d.save(path)
    w.open_path(path)
    found = run(w)
    w.close()
    app.quit()
    return 1 if any(found.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
