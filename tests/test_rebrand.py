"""Everything is QuantiSheet (Jon, Oct 30): the program's earlier name
appears nowhere in what ships, builds or installs it - only in
app/oldnames.py, which converts files saved under it, and in the few
clearly marked lines that clean up after it (the setup removing the old
"Open with" entry, Back Office still recognising time cards brought in
before)."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD = re.compile(r"pdf[\s_-]*studio", re.I)

# where the program, its installers and its shipped docs live
SCAN = ["app", "server", "installer", "quantisheet_claims",
        "quantisheet_backoffice", "quantisheet.py", "quantisheet.spec",
        "quantisheet_claims.spec", "README.md", "make-tester-key.bat",
        "install.bat", "build.bat", "docs/IT_DEPLOYMENT.md",
        "docs/RELEASE_CHECKLIST.md", "tools/make_msi.py",
        "tools/build_installer.py", "tools/release_files.py",
        "tools/zip_release.py", "tools/install_release.py",
        "tools/check_installer.py", "tools/make_admx.py",
        "tools/make_winget.py", "tools/beta_keys.py"]
SKIP_DIRS = {"__pycache__", "tests", "host_tests"}
SKIP_EXT = (".pyc", ".orig", ".png", ".ico", ".bmp", ".jpg", ".pdf",
            ".sqlite", ".db", ".zip")
# the one module that knows the old name, and the marked clean-up lines
ALLOWED_FILES = {"app/oldnames.py"}
ALLOWED_LINES = {
    "installer/quantisheet.iss": 2,                 # remove the old ProgID
    "quantisheet_backoffice/timeentry.py": 1,       # OLD_CARD_PREFIX
}


def _files():
    for item in SCAN:
        p = os.path.join(ROOT, *item.split("/"))
        if os.path.isfile(p):
            yield item
            continue
        for base, dirs, names in os.walk(p):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for n in names:
                if n.endswith(SKIP_EXT):
                    continue
                yield os.path.relpath(os.path.join(base, n),
                                      ROOT).replace(os.sep, "/")


def offenders():
    out = []
    for rel in _files():
        if rel in ALLOWED_FILES:
            continue
        with open(os.path.join(ROOT, *rel.split("/")), encoding="utf-8",
                  errors="replace") as f:
            hits = [(i, ln.strip()) for i, ln in enumerate(f, 1)
                    if OLD.search(ln)]
        if len(hits) > ALLOWED_LINES.get(rel, 0):
            out += [f"{rel}:{i}: {ln[:90]}" for i, ln in hits]
    return out


def test_no_old_name_anywhere_that_ships():
    assert offenders() == []


def test_no_old_name_in_file_or_folder_names():
    bad = []
    for item in ("app", "installer", "server", "quantisheet_claims",
                 "quantisheet_backoffice", "docs"):
        for base, dirs, names in os.walk(os.path.join(ROOT, item)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for n in dirs + names:
                if OLD.search(n) and not n.startswith("GITHUB_RELEASE_"):
                    bad.append(os.path.join(base, n))
    assert bad == []


def test_the_allowed_lines_are_the_clean_up():
    iss = open(os.path.join(ROOT, "installer", "quantisheet.iss"),
               encoding="utf-8").read()
    old = [ln for ln in iss.splitlines() if OLD.search(ln)]
    assert len(old) == 2 and all(
        "deletekey" in ln or "deletevalue" in ln for ln in old)
    te = open(os.path.join(ROOT, "quantisheet_backoffice", "timeentry.py"),
              encoding="utf-8").read()
    assert [ln for ln in te.splitlines() if OLD.search(ln)] == \
        ['OLD_CARD_PREFIX = "pdfstudio:timecard:"']


def test_the_check_finds_one(tmp_path, monkeypatch):
    import sys
    mod = sys.modules[__name__]
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "a.py").write_text('A = "PDF Studio"\n')
    (tmp_path / "x" / "b.py").write_text('B = "pdfstudio_x.json"\n')
    (tmp_path / "x" / "c.py").write_text('C = "QuantiSheet"\n')
    monkeypatch.setattr(mod, "ROOT", str(tmp_path))
    monkeypatch.setattr(mod, "SCAN", ["x"])
    assert len(offenders()) == 2


def _read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8-sig") as f:
        return f.read()


def test_installers_keep_their_ids_and_use_quantisheet_names():
    solo = _read("installer", "quantisheet.iss")
    server = _read("installer", "quantisheet_server.iss")
    for iss, app_id in ((solo, "375F90B3-3B41-4FE9-B790-B29C6D30C75E"),
                        (server, "6A0E2C4B-9F31-4D2B-8C55-3B1D2E7F9A40")):
        assert f"AppId={{{{{app_id}}}" in iss          # upgrades in place
        assert re.search(r"(?m)^AppName=QuantiSheet", iss)
        assert re.search(r"(?m)^DefaultDirName=\{code:DefaultAppDir\}$", iss)
        assert 'AppUserModelID: "QuantiSheet.App"' in iss
        assert "NewExe = 'QuantiSheet.exe';" in iss
        assert "function PrepareToInstall" in iss
    assert 'Subkey: "Software\\Classes\\QuantiSheet.pdf"' in solo
    assert 'Subkey: "Software\\Classes\\QuantiSheet.Server.pdf"' in server
    assert 'Subkey: "Software\\Policies\\QuantiSheet"' in server
    assert '/TN ""QuantiSheet Relay""' in server
    assert "printer --migrate" not in solo + server


def test_msi_names():
    import sys
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import make_msi
    assert make_msi.UPGRADE_CODE == "{4C3E6B2A-8D17-4F0B-9A65-2E7C1D9F0B83}"
    assert make_msi.EXE == "QuantiSheet.exe"
    assert make_msi.NEW_DIR == "QuantiSheet"
    assert make_msi.PROGID == "QuantiSheet.Server.pdf"
    assert make_msi.POLICY_KEY == r"Software\Policies\QuantiSheet"


def test_group_policy_template_and_policy_key():
    from app import policy
    assert policy.KEY == r"SOFTWARE\Policies\QuantiSheet"
    admx = _read("installer", "policy", "QuantiSheet.admx")
    assert 'namespace="QuantiSheet.Policies.QuantiSheet"' in admx
    assert 'key="Software\\Policies\\QuantiSheet"' in admx


def test_spec_and_version_info():
    spec = _read("quantisheet.spec")
    assert spec.count('name="QuantiSheet",') == 2          # EXE and COLLECT
    vi = _read("installer", "version_info.txt")
    assert "'OriginalFilename', 'QuantiSheet.exe'" in vi


def test_installed_exe_and_is_program(tmp_path):
    from app import branding
    base = str(tmp_path)
    assert branding.installed_exe(base) == os.path.join(
        base, "QuantiSheet", "QuantiSheet.exe")
    for p in ("QuantiSheet.exe", "C:/x/QUANTISHEET.EXE"):
        assert branding.is_program(p), p
    for p in ("ClaimIT.exe", "QuantiSheet.exe.lnk", "", None, "python.exe"):
        assert not branding.is_program(p), p
