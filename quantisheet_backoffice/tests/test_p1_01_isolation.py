"""P1-01: 1.2 isolation (never ~/.quantisheet, never a price database, never
QuantiSheet's app package) and the addendum's 1.4 provenance check.
1.1 and 1.3 need QuantiSheet itself and live in host_tests/ (run with
QuantiSheet's suite); the separate runs with and without this folder
are in the patch notes."""
import importlib
import importlib.metadata
import os
import re
import sqlite3
import sys

import pytest

from quantisheet_backoffice import settings, store

from . import conftest

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.join(os.path.expanduser("~"), ".quantisheet")


def _files(exts=None, skip_host_tests=True):
    for d, dirs, fs in os.walk(PKG):
        dirs[:] = [x for x in dirs if x != "__pycache__" and
                   not (skip_host_tests and x == "host_tests")]
        for f in fs:
            if exts is None or f.endswith(exts):
                yield os.path.join(d, f)


def test_1_2_guard_is_armed_and_catches(tmp_path):
    before = list(conftest.GUARD["violations"])
    with pytest.raises(AssertionError):
        open(os.path.join(REAL, "settings.json"))
    with pytest.raises(AssertionError):
        sqlite3.connect(str(tmp_path / "prices.db"))
    try:
        if "app" not in sys.modules:
            with pytest.raises(AssertionError):
                importlib.import_module("app")
            with pytest.raises(AssertionError):
                exec("import app")
        n = len(conftest.GUARD["violations"]) - len(before)
        assert n == (4 if "app" not in sys.modules else 2)
    finally:
        del conftest.GUARD["violations"][len(before):]   # own probes only


def test_1_2_everything_under_temp_home(office, bo_home, tmp_path):
    for p in (settings.data_folder(), settings.backup_folder(),
              settings.db_path(), office.folder):
        assert os.path.realpath(p).startswith(os.path.realpath(str(bo_home)))
        assert not os.path.realpath(p).startswith(os.path.realpath(REAL))
    from quantisheet_backoffice import backup
    backup.make(office)
    written = [os.path.join(d, f) for d, _, fs in os.walk(tmp_path) for f in fs]
    assert written and all(w.startswith(str(tmp_path)) for w in written)


def test_1_2_refuses_quantisheet_folder_and_price_db(monkeypatch):
    monkeypatch.setenv("QS_BACKOFFICE_HOME", REAL)
    settings.reload()
    with pytest.raises(settings.UnsafePathError):
        settings.data_folder()
    with pytest.raises(settings.UnsafePathError):
        settings.check_safe("/tmp/x/prices.db")
    with pytest.raises(settings.UnsafePathError):
        store.DB("/tmp/somewhere/price_list.sqlite")


def test_1_2_never_imports_app_package():
    pat = re.compile(r"^\s*(import app\b|from app\b|import app\.|from app\.)",
                     re.M)
    dyn = re.compile(r"""import_module\(\s*['"]app\b|__import__\(\s*['"]app\b""")
    hits = [p for p in _files((".py",)) if p != os.path.abspath(__file__) and
            (pat.search(open(p, encoding="utf-8").read()) or
             dyn.search(open(p, encoding="utf-8").read()))]
    assert hits == []


def test_1_2_whole_program_in_a_fresh_process(tmp_path):
    """The package's own entry point (self test) in a clean interpreter:
    'app' never appears in sys.modules."""
    import subprocess
    import sys
    env = dict(os.environ, QS_BACKOFFICE_HOME=str(tmp_path / "h"))
    code = ("import sys, runpy; sys.argv=['qbo','--selftest'];\n"
            "try:\n runpy.run_module('quantisheet_backoffice', "
            "run_name='__main__')\nexcept SystemExit as e:\n rc=e.code\n"
            "print('APP_LOADED' if any(m == 'app' or m.startswith('app.') "
            "for m in sys.modules) else 'APP_CLEAN', rc)")
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         cwd=os.path.dirname(PKG), capture_output=True,
                         text=True, timeout=120)
    assert "APP_CLEAN 0" in out.stdout, out.stdout + out.stderr


def test_1_4_provenance_no_foreign_names():
    banned = ["Slow" + "Books", "Slow" + "books", "Von " + "Holten",
              "VonHolten" + "Codes"]
    hits = []
    for p in _files(skip_host_tests=False):
        data = open(p, "rb").read()
        for b in banned:
            if b.encode() in data or b.encode("utf-16-le") in data:
                hits.append((os.path.relpath(p, PKG), b))
    assert hits == []


def test_1_4_no_intuit_api_google_bni_or_xactimate():
    banned = re.compile(r"intuit\.com|googleapis|google\.|gmail|BNi\b|"
                        r"Xactimate|\.esx\b", re.I)
    hits = [os.path.relpath(p, PKG) for p in _files((".py",))
            if p != os.path.abspath(__file__) and
            banned.search(open(p, encoding="utf-8").read())]
    assert hits == []


def test_1_4_third_party_notices_only_installed_libs():
    text = open(os.path.join(PKG, "THIRD_PARTY_NOTICES.txt"),
                encoding="utf-8").read()
    listed = re.findall(r"^- (\S+) : (.+)$", text, re.M)
    assert len(listed) >= 4
    for dist, licence in listed:
        importlib.metadata.version(dist)          # raises if not installed
        assert re.search(r"LGPL|AGPL|Apache|BSD|MIT|GPL", licence), dist
    names = {d.lower() for d, _ in listed}
    # every third-party library the package imports is listed
    imported = set()
    for p in _files((".py",)):
        if os.sep + "tests" + os.sep in p:
            continue
        src = open(p, encoding="utf-8").read()
        for mod in re.findall(r"^\s*(?:import|from) (\w+)", src, re.M):
            imported.add(mod)
    to_dist = {"PySide6": "pyside6", "fitz": "pymupdf", "pymupdf": "pymupdf",
               "cryptography": "cryptography", "openpyxl": "openpyxl",
               "PIL": "pillow"}
    for mod, dist in to_dist.items():
        if mod in imported:
            assert dist in names, mod
    assert "Intuit" in text and "not affiliated" in text
