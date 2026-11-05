"""Master Schedule practice run on Jon's REAL Dropbox (Jon approved, Oct
28). A made-up job (Acme Electric / Best Plumbing, example.invalid) in a
temp folder; the inbox is one new Dropbox folder:

    /QuantiSheet Practice - Schedule Inbox/
        Acme Electric/   a filled-in update sheet  -> Processed/
        Best Plumbing/   a file that isn't a schedule -> Rejected/ + reason
        <each>/Outbox/   the update sheets QuantiSheet made

Uses the Dropbox sign-in QuantiSheet already has (File > Dropbox); signs
nothing in, deletes nothing: Jon deletes the practice folder himself in
Dropbox when he's done looking.

    python tools/practice_dropbox_inbox.py"""
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
FOLDER = "/QuantiSheet Practice - Schedule Inbox"


def main():
    from app import dropbox_sync as dbx
    key = dbx.app_key()
    real = dbx.Client(key)               # read Jon's sign-in BEFORE the
    if not key or not real.tokens.get("refresh_token"):   # temp settings
        print("NOT SIGNED IN: open QuantiSheet > File > Dropbox > Sign in, "
              "then run this again.")
        return 1
    print("Dropbox account:", real.current_account().get("name") or "?")
    tmp = tempfile.mkdtemp(prefix="qs_dbx_practice_")
    try:
        from r39_master_fixtures import ACME, BEST, act, fill, make_store

        class _MP:
            def setattr(self, o, n, v):
                setattr(o, n, v)
        s = make_store(pathlib.Path(tmp), _MP())   # temp settings from here
        from app.pm.master import dropbox_inbox, intake, model
        from app.pm.master.formats import excel
        dropbox_inbox._client = lambda: real
        model.set_config(s, inbox=dropbox_inbox.as_setting(FOLDER),
                         cycle={"nth": 1})
        for c in (ACME, BEST):
            try:
                real.create_folder(dbx.join(FOLDER, c))
            except Exception as ex:                         # noqa: BLE001
                print("folder", c, "-", type(ex).__name__)
        sheets = intake.prepare_packets(s, cycle_date="2026-11-05")
        print("update sheets made:", len(sheets))
        r = dropbox_inbox.sync(s)
        print("uploaded to Outbox:", len(r["uploaded"]), r["errors"])
        p = os.path.join(tmp, "Acme update.xlsx")
        excel.generate(s, ACME, p, cycle="2026-11-05")
        fill(p, {"A0002": {"% complete": 60}})
        real.upload(p, dbx.join(dbx.join(FOLDER, ACME), "Acme update.xlsx"),
                    mode="overwrite")
        junk = os.path.join(tmp, "not a schedule.xlsx")
        import openpyxl
        wb = openpyxl.Workbook()
        wb.active["A1"] = "This is not a schedule update"
        wb.save(junk)
        real.upload(junk, dbx.join(dbx.join(FOLDER, BEST), "not a schedule.xlsx"),
                    mode="overwrite")
        print("two practice files put in the subs' folders")
        st = intake.state_for(s)
        r1 = intake.scan(s, st)
        for x in r1["picked"]:
            print("  received:", x.get("company"), x.get("file_name"), "->",
                  x.get("status"), [y.get("text") for y in
                                    x.get("reasons") or []][:2])
        print("  errors:", r1["errors"])
        r2 = dropbox_inbox.sync(s)       # results go back to Dropbox
        print("  moved in Dropbox:", *r2["moved"], sep="\n    ")
        print("  errors:", r2["errors"])
        print("A0002 percent now:", act(s, "A0002").get("percent"))
        print("\nIn Dropbox:")
        for c in (ACME, BEST):
            for sub in ("", "/Processed", "/Rejected", "/Outbox"):
                try:
                    names = [e["name"] for e in real.list_folder(
                        dbx.join(FOLDER, c) + sub)]
                except Exception:                           # noqa: BLE001
                    names = []
                print(f"  {c}{sub or ''}: {names}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


sys.exit(main())
