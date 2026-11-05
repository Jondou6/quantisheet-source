"""Check an MSI without installing it (no admin needed):

    python tools/check_msi.py PATH.msi [APP_DIR]

1. reads the package back (product code, version, file count);
2. an administrative install (msiexec /a) unpacks it into a temporary
   folder - proof the cabinet and file table are whole - and, with
   APP_DIR, compares every file with the program it was built from;
3. lists the tables IT cares about (launch conditions, policy registry
   values, shortcuts, the ProgramData lock).
"""
import filecmp
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def rows(msi, query):
    import warnings
    warnings.simplefilter("ignore", DeprecationWarning)
    import msilib
    db = msilib.OpenDatabase(msi, msilib.MSIDBOPEN_READONLY)
    v = db.OpenView(query)
    v.Execute(None)
    out = []
    while True:
        r = v.Fetch()
        if r is None:
            break
        n = r.GetFieldCount()
        vals = []
        for i in range(1, n + 1):
            try:
                vals.append(r.GetString(i))
            except Exception:                             # noqa: BLE001
                vals.append(None)                         # a number field
        out.append(tuple(vals))
    v.Close()
    return out


def main(argv):
    import make_msi
    msi = os.path.abspath(argv[0])
    app_dir = argv[1] if len(argv) > 1 else None
    print("package:", make_msi.check(msi))
    print("launch conditions:", rows(msi, "SELECT `Condition` FROM "
                                          "`LaunchCondition`"))
    print("registry:", [(r[0], r[2], r[3]) for r in rows(
        msi, "SELECT `Registry`,`Root`,`Key`,`Name` FROM `Registry`")])
    print("conditional components:", rows(
        msi, "SELECT `Component`,`Condition` FROM `Component` WHERE "
             "`Condition` <> ''"))
    print("shortcuts:", rows(msi, "SELECT `Shortcut`,`Directory_` FROM "
                                  "`Shortcut`"))
    print("lock:", rows(msi, "SELECT `LockObject`,`SDDLText` FROM "
                             "`MsiLockPermissionsEx`"))
    print("remove old first:", rows(
        msi, "SELECT `Action`,`Sequence` FROM `InstallExecuteSequence` "
             "WHERE `Action`='RemoveExistingProducts' OR "
             "`Action`='InstallInitialize' OR `Action`='InstallValidate' "
             "OR `Action`='SetOldInstallDir'"))
    tmp = tempfile.mkdtemp(prefix="quantisheet-msi-")
    try:
        log = os.path.join(tmp, "admin.log")
        target = os.path.join(tmp, "unpacked")
        p = subprocess.run(["msiexec", "/a", msi, "/qn", f"TARGETDIR={target}",
                            "/l*v", log], capture_output=True, text=True,
                           timeout=1200)
        print("admin install exit:", p.returncode)
        if p.returncode != 0 and os.path.exists(log):
            with open(log, encoding="utf-16", errors="replace") as f:
                text = f.read()
            print("log tail:", text[-3000:])
        inst = None
        for dirpath, _dirs, files in os.walk(target):
            if "QuantiSheet.exe" in files:
                inst = dirpath
                break
        print("unpacked program folder:", inst)
        if inst and app_dir:
            missing, differ, n = [], [], 0
            for dirpath, _dirs, files in os.walk(app_dir):
                for f in files:
                    a = os.path.join(dirpath, f)
                    b = os.path.join(inst, os.path.relpath(a, app_dir))
                    n += 1
                    if not os.path.exists(b):
                        missing.append(os.path.relpath(a, app_dir))
                    elif not filecmp.cmp(a, b, shallow=False):
                        differ.append(os.path.relpath(a, app_dir))
            print(f"compared {n} files: {len(missing)} missing, "
                  f"{len(differ)} different", missing[:5], differ[:5])
            for extra in (r"docs\IT_DEPLOYMENT.md",
                          r"docs\Detect-QuantiSheet.ps1",
                          r"policy\QuantiSheet.admx",
                          r"policy\en-US\QuantiSheet.adml"):
                print("  extra", extra, os.path.exists(os.path.join(inst,
                                                                    extra)))
            ok = p.returncode == 0 and not missing and not differ
            print("RESULT:", "OK" if ok else "PROBLEM")
            return 0 if ok else 1
        return 0 if p.returncode == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
