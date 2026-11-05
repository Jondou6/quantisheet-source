"""Trial on this PC's real Excel: does a Master Schedule update template
survive being opened, filled in and saved by Excel (the very hidden _qs
sheet and its signature)? Made-up job in a temp folder; Excel is driven
through COM, invisible, and closed at the end. Nothing else is touched.

    python tools/trial_excel_roundtrip.py"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

tmp = tempfile.mkdtemp(prefix="ms_excel_")


class _MP:                       # the fixture's monkeypatch, without pytest
    def setattr(self, obj, name, value):
        setattr(obj, name, value)


def main():
    from r39_master_fixtures import ACME, act, make_store
    from app.pm.master import apply
    from app.pm.master.formats import excel
    import pathlib
    s = make_store(pathlib.Path(tmp), _MP())
    path = os.path.join(tmp, "Acme update.xlsx")
    excel.generate(s, ACME, path, cycle="2026-11-05")
    print("template made:", os.path.getsize(path), "bytes")
    try:
        import win32com.client
    except ImportError:
        print("pywin32 isn't installed here - can't drive Excel")
        return 1
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
    except Exception as ex:                               # noqa: BLE001
        print("Excel isn't available on this PC:", ex)
        return 1
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        print("Excel", xl.Version)
        wb = xl.Workbooks.Open(path)
        names = [ws.Name for ws in wb.Worksheets]
        vis = {ws.Name: ws.Visible for ws in wb.Worksheets}
        print("sheets:", names, "visibility:", vis)
        ws = wb.Worksheets("Update")
        hit = None
        for r in range(1, 60):
            for c in range(1, 12):
                if str(ws.Cells(r, c).Value or "").strip() == "A0002":
                    hit = (r, c)
                    break
            if hit:
                break
        if not hit:
            print("A0002 row not found on the Update sheet")
        else:
            heads = {str(ws.Cells(hr, c).Value or "").strip(): c
                     for hr in range(1, hit[0]) for c in range(1, 16)}
            col = next((c for h, c in heads.items()
                        if h.lower().startswith("%")
                        or "percent" in h.lower()), None)
            print("A0002 at", hit, "percent column", col)
            if col:
                ws.Cells(hit[0], col).Value = 60
        wb.Save()
        wb.Close(False)
    finally:
        xl.Quit()
    out = excel.read(s, path)
    print("read back: errors", out.get("errors"), "warnings",
          [w.get("text") for w in out.get("warnings") or []][:3])
    sub = apply.receive(s, path, ACME, channel="manual")
    print("submission:", sub.get("status"), [r.get("text") for r in
                                            sub.get("reasons") or []][:3])
    print("A0002 percent now:", act(s, "A0002").get("percent"))
    return 0


try:
    rc = main()
finally:
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(rc)
