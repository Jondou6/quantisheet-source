"""The MSI package for IT (0.12.24): the same program as the server
setup, as a Windows Installer package for Intune (line-of-business app),
SCCM / ConfigMgr, Group Policy software installation and PDQ.

    python tools/make_msi.py APP_DIR OUT.msi [--publisher NAME]

Built with Python's own msilib (Windows Python 3.12) - no WiX or other
download needed. tools/build_installer.py calls build() for the tester and
public copies.

What it installs (per machine, 64-bit, needs admin):
  * the program in C:\\Program Files\\QuantiSheet, Start-menu shortcut;
  * the Group Policy templates in the program folder (and, with GPO=1,
    the default, in C:\\Windows\\PolicyDefinitions);
  * C:\\ProgramData\\QuantiSheet locked to SYSTEM /
    Administrators (users read only) - IT's policy.json lives there
    (Fable review S1);
  * "Open with" for PDF files (OPENWITH=1, the default);
  * the "QuantiSheet" printer (PRINTER=1 adds it; off by default);
  * the policy values given on the command line, in
    HKLM\\Software\\Policies\\QuantiSheet, exactly like the server setup's
    switches: LICENSEKEY, PRICEDB, RELAYURL, AIHOST, LOGDIR,
    ACCEPTAGREEMENT=1, SKIPSIGNIN=1, OFFLINE=1, NOAI=1.

    msiexec /i QuantiSheet-Beta-<version>.msi /qn /l*v C:\\Windows\\Temp\\quantisheet-msi.log
        [LICENSEKEY=...] [PRICEDB=\\\\server\\share\\prices.db] [DESKTOPICON=1] ...
    msiexec /x {ProductCode} /qn           (or by the .msi)

Not in the MSI: the collaboration relay service (scheduled task, firewall
rule) - a relay host uses the server setup. The MSI refuses to install
where the server setup already is (same folder), and a newer MSI replaces
an older one (major upgrade, the old one removed first).
"""
import argparse
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# fixed for every MSI: Windows matches versions by it - never change it
UPGRADE_CODE = "{4C3E6B2A-8D17-4F0B-9A65-2E7C1D9F0B83}"
SERVER_SETUP_KEY = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
                    r"\{6A0E2C4B-9F31-4D2B-8C55-3B1D2E7F9A40}_is1")
# ProgramData\QuantiSheet: SYSTEM and Administrators full, Users read
DATA_SDDL = ("D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
             "(A;OICI;0x1200a9;;;BU)")
POLICY_KEY = r"Software\Policies\QuantiSheet"
# (property, value name, registry value): "#1" is a DWORD 1
POLICY_VALUES = [("LICENSEKEY", "LicenseKey", "[LICENSEKEY]"),
                 ("PRICEDB", "PriceDatabasePath", "[PRICEDB]"),
                 ("RELAYURL", "RelayURL", "[RELAYURL]"),
                 ("AIHOST", "AIHost", "[AIHOST]"),
                 ("LOGDIR", "LogDirectory", "[LOGDIR]"),
                 ("ACCEPTAGREEMENT", "AcceptAgreement", "#1"),
                 ("SKIPSIGNIN", "SkipEmailSignIn", "#1"),
                 ("OFFLINE", "OfflineMode", "#1"),
                 ("NOAI", "DisableAI", "#1")]
NEW_DIR = "QuantiSheet"
# the icon Windows keeps for Programs and Features / the shortcuts
ICON = "quantisheet.ico"
EXE = "QuantiSheet.exe"
PUBLIC = ["OLDPRODUCTS", "NEWERFOUND", "SERVERSETUP",
          "DESKTOPICON",
          "OPENWITH", "GPO", "PRINTER"] + [p for p, _n, _v in POLICY_VALUES]


# "Open with": the server setup's ProgID (the two never share a machine),
# not the standalone setup's QuantiSheet.pdf, so uninstalling either one
# leaves the other's entry. No Applications\QuantiSheet.exe (or App
# Paths) key: it is keyed by the exe name, so the standalone setup's
# would go with it. FriendlyAppName is what Open with shows.
PROGID = "QuantiSheet.Server.pdf"


def openwith_rows(exe_ref):
    """Registry table rows for "Open with" (component OpenWith)."""
    cls = r"Software\Classes"
    prog = cls + "\\" + PROGID
    return [
        ("OwProg", 2, prog, None, "PDF Document (QuantiSheet)", "OpenWith"),
        ("OwIcon", 2, prog + r"\DefaultIcon", None, exe_ref + ",0",
         "OpenWith"),
        ("OwName", 2, prog + r"\shell\open", "FriendlyAppName",
         "QuantiSheet", "OpenWith"),
        ("OwCmd", 2, prog + r"\shell\open\command", None,
         f'"{exe_ref}" "%1"', "OpenWith"),
        ("OwList", 2, cls + r"\.pdf\OpenWithProgids", PROGID, None,
         "OpenWith")]


def msi_version(v):
    """'0.12.24' -> '0.12.24' (MSI wants up to three numbers, each part
    under 256 for the first two)."""
    parts = [int(x) for x in v.split(".")[:3]]
    if len(parts) < 3:
        parts += [0] * (3 - len(parts))
    if parts[0] > 255 or parts[1] > 255 or parts[2] > 65535:
        raise ValueError(f"version {v} can't be an MSI version")
    return ".".join(str(p) for p in parts)


def _sql(db, query):
    v = db.OpenView(query)
    v.Execute(None)
    v.Close()


def build(app_dir, out_path, version, publisher="QuantiSheet",
          product_name="QuantiSheet (all users)"):
    """Write the MSI; returns (out_path, product code, files added)."""
    import warnings
    warnings.simplefilter("ignore", DeprecationWarning)
    import msilib
    from msilib import schema, sequence
    # directory ids start fresh per MSI (msilib keeps them module-wide)
    getattr(msilib, "_directories", set()).clear()

    exe = os.path.join(app_dir, EXE)
    if not os.path.isfile(exe):
        raise RuntimeError(f"no {EXE} in {app_dir}")
    ver = msi_version(version)
    product_code = "{" + str(uuid.uuid4()).upper() + "}"
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    db = msilib.init_database(out_path, schema, product_name, product_code,
                              ver, publisher)
    msilib.add_tables(db, sequence)
    # the old version comes out first (before anything is installed): the
    # components are new each build, so a late removal would delete the
    # files just installed
    _sql(db, "UPDATE `InstallExecuteSequence` SET `Sequence`=1401 "
             "WHERE `Action`='RemoveExistingProducts'")
    icon = os.path.join(ROOT, "icon.ico")
    add = msilib.add_data
    add(db, "Property", [
        ("ALLUSERS", "1"), ("ARPNOMODIFY", "1"),
        ("ARPPRODUCTICON", ICON),
        ("ARPCOMMENTS", "QuantiSheet - PDF program for construction"),
        ("UpgradeCode", UPGRADE_CODE),
        ("OPENWITH", "1"), ("GPO", "1"), ("PRINTER", "0"),
        ("SecureCustomProperties", ";".join(PUBLIC))])
    add(db, "Icon", [(ICON, msilib.Binary(icon))])
    add(db, "Upgrade", [
        # anything older: removed (min inclusive = 256)
        (UPGRADE_CODE, "0.0.1", ver, None, 256, None, "OLDPRODUCTS"),
        # anything newer: detected only (2), install refused
        (UPGRADE_CODE, ver, None, None, 2, None, "NEWERFOUND")])
    # the server setup (Inno) in the same folder: refuse
    add(db, "RegLocator", [("ServerSetupSig", 2, SERVER_SETUP_KEY,
                            "DisplayVersion", 2 | 16)])     # raw, 64-bit
    add(db, "AppSearch", [("SERVERSETUP", "ServerSetupSig")])
    add(db, "LaunchCondition", [
        ("Installed OR NOT SERVERSETUP",
         "QuantiSheet is already installed for all users by the server "
         "setup. Uninstall that first, then install the MSI."),
        ("Installed OR NOT NEWERFOUND",
         "A newer QuantiSheet MSI is already installed."),
        ("VersionNT64", "QuantiSheet needs 64-bit Windows."),
        ("VersionNT >= 603",
         "QuantiSheet needs Windows 10 / Server 2016 or later.")])

    cab = msilib.CAB("quantisheet")
    feature = msilib.Feature(db, "Main", "QuantiSheet", "The program",
                             1, directory="INSTALLDIR")
    feature.set_current()
    tdir = msilib.Directory(db, cab, None, app_dir, "TARGETDIR",
                            "SourceDir")
    pf = msilib.Directory(db, cab, tdir, app_dir, "ProgramFiles64Folder",
                          ".")
    inst = msilib.Directory(db, cab, pf, app_dir, "INSTALLDIR",
                            f"QUANTI~1|{NEW_DIR}")
    inst.start_component("MainExe", feature, 0, keyfile=EXE)
    count = 0

    def walk(d, path):
        nonlocal count
        names = sorted(os.listdir(path))
        for n in names:
            p = os.path.join(path, n)
            if os.path.isfile(p):
                d.add_file(n)
                count += 1
        for n in names:
            p = os.path.join(path, n)
            if os.path.isdir(p):
                sub = msilib.Directory(db, cab, d, p, n,
                                       f"{d.make_short(n)}|{n}")
                sub.start_component(sub.logical, feature, 0)
                walk(sub, p)
    walk(inst, app_dir)

    # beside the program: IT guide, detection script, templates
    extra = {"docs": [os.path.join(ROOT, "docs", "IT_DEPLOYMENT.md"),
                      os.path.join(ROOT, "installer", "it",
                                   "Detect-QuantiSheet.ps1")],
             "policy": [os.path.join(ROOT, "installer", "policy",
                                     "QuantiSheet.admx")],
             "policy/en-US": [os.path.join(ROOT, "installer", "policy",
                                           "en-US", "QuantiSheet.adml")]}
    made = {"": inst}
    for rel in ("docs", "policy", "policy/en-US"):
        parent = made[os.path.dirname(rel)]
        name = os.path.basename(rel)
        if os.path.isdir(os.path.join(app_dir, *rel.split("/"))):
            raise RuntimeError(f"the program already has a {rel} folder")
        d = msilib.Directory(db, cab, parent,
                             os.path.dirname(extra[rel][0]),
                             "Extra_" + name.replace("-", "_"),
                             f"{parent.make_short(name)}|{name}")
        d.start_component(d.logical, feature, 0)
        made[rel] = d
    for rel, files in extra.items():
        d = made[rel]
        for f in files:
            if not os.path.isfile(f):
                raise RuntimeError(f"missing {f}")
            d.add_file(os.path.basename(f), src=f)    # from outside app_dir
            count += 1

    # Group Policy templates in C:\Windows\PolicyDefinitions (GPO=1)
    win = msilib.Directory(db, cab, tdir, ROOT, "WindowsFolder", ".")
    pdef = msilib.Directory(db, cab, win,
                            os.path.join(ROOT, "installer", "policy"),
                            "PolicyDefinitions",
                            "POLICY~1|PolicyDefinitions")
    pdef.start_component("GpoAdmx", feature, 0)
    pdef.add_file("QuantiSheet.admx")
    pdef_en = msilib.Directory(db, cab, pdef,
                               os.path.join(ROOT, "installer", "policy",
                                            "en-US"),
                               "PolicyDefinitionsEnUS", "en-US")
    pdef_en.start_component("GpoAdml", feature, 0)
    pdef_en.add_file("QuantiSheet.adml")
    for comp in ("GpoAdmx", "GpoAdml"):
        _sql(db, "UPDATE `Component` SET `Condition`='GPO=\"1\"' "
                 f"WHERE `Component`='{comp}'")

    # ProgramData\QuantiSheet (IT's policy.json), locked down
    add(db, "Directory", [
        ("CommonAppDataFolder", "TARGETDIR", "."),
        ("QSDATA", "CommonAppDataFolder", "QUANTI~1|QuantiSheet"),
        ("ProgramMenuFolder", "TARGETDIR", "."),
        ("DesktopFolder", "TARGETDIR", ".")])
    add(db, "Component", [("DataFolder", _guid(), "QSDATA", 256,
                           None, None)])
    add(db, "CreateFolder", [("QSDATA", "DataFolder")])
    # msilib's schema makes an (empty) LockPermissions table: Windows
    # Installer refuses a package with both it and MsiLockPermissionsEx
    # ("Both LockPermissions and MsiLockPermissionsEx tables were found",
    # Jon's PC, 0.12.27 - an admin install /a doesn't check this)
    _sql(db, "DROP TABLE `LockPermissions`")
    _sql(db, "CREATE TABLE `MsiLockPermissionsEx` ("
             "`MsiLockPermissionsEx` CHAR(72) NOT NULL, "
             "`LockObject` CHAR(72) NOT NULL, `Table` CHAR(32) NOT NULL, "
             "`SDDLText` LONGCHAR NOT NULL, `Condition` CHAR(255) "
             "PRIMARY KEY `MsiLockPermissionsEx`)")
    add(db, "MsiLockPermissionsEx", [("LockData", "QSDATA",
                                      "CreateFolder", DATA_SDDL, None)])

    # registry: policy values (each only when its property is given),
    # "Open with", and a key for the desktop shortcut's component
    reg, comps = [], []
    for prop, name, value in POLICY_VALUES:
        rid = "Pol" + name
        reg.append((rid, 2, POLICY_KEY, name, value, "C" + rid))
        comps.append(("C" + rid, _guid(), "TARGETDIR", 256 | 4, prop, rid))
    exe_ref = f"[INSTALLDIR]{EXE}"
    reg += openwith_rows(exe_ref)
    reg += [
        ("DeskKey", 2, r"Software\QuantiSheet\Installer", "DesktopShortcut",
         "#1", "Desktop")]
    comps += [("OpenWith", _guid(), "TARGETDIR", 256 | 4, 'OPENWITH="1"',
               "OwProg"),
              ("Desktop", _guid(), "DesktopFolder", 256 | 4,
               'DESKTOPICON="1"', "DeskKey")]
    add(db, "Registry", reg)
    add(db, "Component", comps)
    add(db, "FeatureComponents", [("Main", c[0]) for c in comps] +
        [("Main", "DataFolder")])
    add(db, "Shortcut", [
        ("StartMenu", "ProgramMenuFolder", "QUANTI~1|QuantiSheet", "MainExe",
         exe_ref, None, "QuantiSheet", None, ICON, 0, None,
         "INSTALLDIR"),
        ("DesktopIcon", "DesktopFolder", "QUANTI~1|QuantiSheet", "Desktop",
         exe_ref, None, "QuantiSheet", None, ICON, 0, None,
         "INSTALLDIR")])
    # the "QuantiSheet" printer (PRINTER=1 to add it; off by default since
    # 0.12.26): the program sets it up and takes it down itself -
    # deferred, failures don't stop the install. Each user's helper then
    # runs as them from sign-in (HKLM Run, --all-users). printer --remove
    # takes the printer away.
    exe_key = inst.keyfiles[EXE]
    add(db, "CustomAction", [
        ("PrinterInstall", 18 | 1024 | 2048 | 64, exe_key,
         "printer --install --all-users"),
        ("PrinterRemove", 18 | 1024 | 2048 | 64, exe_key,
         "printer --remove")])
    add(db, "InstallExecuteSequence", [
        ("PrinterRemove", 'REMOVE="ALL"', 3450),        # before RemoveFiles
        ("PrinterInstall", 'PRINTER="1" AND NOT REMOVE', 6550)])
    db.Commit()
    cab.commit(db)
    si = db.GetSummaryInformation(20)
    si.SetProperty(msilib.PID_TITLE, product_name)
    si.SetProperty(msilib.PID_APPNAME, "QuantiSheet build (msilib)")
    si.SetProperty(msilib.PID_PAGECOUNT, 500)      # Windows Installer 5.0
    si.Persist()
    db.Commit()
    del db
    return out_path, product_code, count


def _guid():
    return "{" + str(uuid.uuid4()).upper() + "}"


def check(msi_path):
    """Read the package back: (product code, version, file count,
    properties) - the build check that it is a real MSI."""
    import warnings
    warnings.simplefilter("ignore", DeprecationWarning)
    import msilib
    db = msilib.OpenDatabase(msi_path, msilib.MSIDBOPEN_READONLY)

    def one(q):
        v = db.OpenView(q)
        v.Execute(None)
        r = v.Fetch()
        v.Close()
        return r

    def prop(name):
        r = one(f"SELECT `Value` FROM `Property` WHERE `Property`='{name}'")
        return r.GetString(1) if r else None
    tables = set()
    v = db.OpenView("SELECT `Name` FROM `_Tables`")
    v.Execute(None)
    while True:
        r = v.Fetch()
        if r is None:
            break
        tables.add(r.GetString(1))
    v.Close()
    if "LockPermissions" in tables and "MsiLockPermissionsEx" in tables:
        raise RuntimeError("the MSI has both LockPermissions and "
                           "MsiLockPermissionsEx - Windows won't install it")
    v = db.OpenView("SELECT `File` FROM `File`")
    v.Execute(None)
    n = 0
    while v.Fetch():
        n += 1
    v.Close()
    return {"product_code": prop("ProductCode"),
            "version": prop("ProductVersion"),
            "upgrade_code": prop("UpgradeCode"),
            "allusers": prop("ALLUSERS"), "files": n}


def main(argv=None):
    from app import __version__
    ap = argparse.ArgumentParser(description="Build the QuantiSheet MSI")
    ap.add_argument("app_dir")
    ap.add_argument("out")
    ap.add_argument("--version", default=__version__)
    ap.add_argument("--publisher", default="QuantiSheet")
    a = ap.parse_args(argv)
    path, code, n = build(a.app_dir, a.out, a.version, a.publisher)
    info = check(path)
    print(f"MSI {path}: {n} files, {os.path.getsize(path) / 1e6:.0f} MB, "
          f"product code {code}")
    print(info)
    return 0


if __name__ == "__main__":
    sys.exit(main())
