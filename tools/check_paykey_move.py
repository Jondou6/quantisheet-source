"""Check the 1.1.1 payroll key move on a COPY of this PC's Back Office
company (Nov 4, QS-025). Never changes the real company or the real key.

    python tools/check_paykey_move.py

Copies the company folder (backoffice.sqlite, datakey.bin) into a
temporary folder, points Back Office's home at another temporary folder,
opens the copy with the 1.1.1 code (which moves the key) and tries every
encrypted value. Prints counts only - never a value, a name or the key.
The temporary copies are removed at the end.
"""
import os
import shutil
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def real_company():
    from quantisheet_backoffice import settings
    folder = settings.data_folder()
    db = os.path.join(folder, "backoffice.sqlite")
    return folder if os.path.isfile(db) else None


def main():
    src = real_company()
    if src is None:
        print("No Back Office company on this PC - nothing to check.")
        return 0
    key = os.path.join(src, "datakey.bin")
    kind = "none"
    if os.path.isfile(key):
        head = open(key, "rb").read(7)
        kind = ("already moved (1.1.1 stub)" if head.startswith(b"qskey1:")
                else "dpapi" if head.startswith(b"dpapi:")
                else "plain" if head.startswith(b"plain:") else "unknown")
    print("company folder found; key file:", kind)
    with tempfile.TemporaryDirectory(prefix="qs-paykey-check-") as tmp:
        home = os.path.join(tmp, "home")
        copy = os.path.join(home, "company-copy")
        os.makedirs(copy)
        # a consistent copy of the database, then the key file
        s = sqlite3.connect(os.path.join(src, "backoffice.sqlite"))
        d = sqlite3.connect(os.path.join(copy, "backoffice.sqlite"))
        s.backup(d)
        s.close()
        d.close()
        if os.path.isfile(key):
            shutil.copy2(key, os.path.join(copy, "datakey.bin"))
        os.environ["QS_BACKOFFICE_HOME"] = home
        from quantisheet_backoffice import crypto, settings, store
        settings.reload()
        from quantisheet_backoffice.r111 import paykeys
        try:
            fc = crypto.FieldCrypto(copy)
        except paykeys.PayKeyError as e:
            print("RESULT: key not opened on this login - refused, no new "
                  "key made:", str(e).splitlines()[0])
            return 1
        moved = open(os.path.join(copy, "datakey.bin"), "rb").read(7)
        print("key moved into the profile:", moved.startswith(b"qskey1:"))
        con = sqlite3.connect(os.path.join(copy, "backoffice.sqlite"))
        ok = bad = 0
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
            for c in cols:
                try:
                    vals = con.execute(
                        f"SELECT {c} FROM {t} WHERE typeof({c}) = 'text' "
                        f"AND ({c} LIKE 'enc1:%' OR {c} LIKE 'enc2:%')"
                    ).fetchall()
                except sqlite3.Error:
                    continue
                for (v,) in vals:
                    try:
                        if v.startswith(crypto.PREFIX):
                            fc.decrypt(v)
                        else:
                            fc.decrypt_value(v)
                        ok += 1
                    except Exception:                     # noqa: BLE001
                        bad += 1
        con.close()
        again = crypto.FieldCrypto(copy).data_key() == fc.data_key()
        print(f"encrypted values: {ok} opened, {bad} did not")
        print("opens again with the same key:", again)
        print("RESULT:", "OK" if bad == 0 and again else "PROBLEM")
        return 0 if bad == 0 and again else 1


if __name__ == "__main__":
    sys.exit(main())
