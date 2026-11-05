"""T12 and findings 14, 15: the module never touches ~/.quantisheet, its
price DB, or QuantiSheet's code."""
import builtins
import os
import re
import sqlite3

import pytest

from quantisheet_claims import settings, store
from .helpers import c8_claim

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def no_quantisheet_dir(monkeypatch):
    bads = settings.quantisheet_dirs()
    real_open, real_connect = builtins.open, sqlite3.connect

    def guard(p):
        if isinstance(p, (str, bytes, os.PathLike)):
            rp = os.path.realpath(os.fsdecode(p))
            for bad in bads:
                if rp == bad or rp.startswith(bad + os.sep):
                    raise AssertionError(f"touched QuantiSheet's folder: {rp}")

    def g_open(p, *a, **k):
        guard(p)
        return real_open(p, *a, **k)

    def g_connect(p, *a, **k):
        guard(p)
        return real_connect(p, *a, **k)

    monkeypatch.setattr(builtins, "open", g_open)
    monkeypatch.setattr(sqlite3, "connect", g_connect)
    return bads


def test_t12_everything_under_tmp_home(claims_home, no_quantisheet_dir, tmp_path):
    assert settings.home() == str(claims_home)
    settings.set("author", "Jon")
    p = store.save(c8_claim())
    assert p.startswith(str(claims_home))
    assert settings.prices_path().startswith(str(claims_home))
    claim, revs = store.load(p)
    assert claim == c8_claim()
    written = [os.path.join(d, f) for d, _, fs in os.walk(tmp_path) for f in fs]
    assert written and all(w.startswith(str(tmp_path)) for w in written)


def test_t12_price_db_path_is_never_the_real_one(claims_home):
    for name in (".quantisheet",):
        real = os.path.join(os.path.expanduser("~"), name)
        for p in (settings.home(), settings.prices_path(),
                  settings.settings_path(), settings.claims_folder()):
            assert not os.path.realpath(p).startswith(os.path.realpath(real))
    assert os.path.basename(settings.prices_path()) == "prices.json"


@pytest.mark.parametrize("name", [".quantisheet"])
def test_t12_refuses_quantisheet_folder(monkeypatch, name):
    monkeypatch.setenv("QUANTISHEET_CLAIMS_HOME",
                       os.path.join(os.path.expanduser("~"), name))
    with pytest.raises(settings.UnsafePathError):
        settings.home()
    with pytest.raises(settings.UnsafePathError):
        settings.check_safe(os.path.join(os.path.expanduser("~"), name,
                                         "prices.db"))


def test_t12_default_home_is_appdata_on_windows(monkeypatch, tmp_path):
    """%APPDATA%\\ClaimIT."""
    monkeypatch.delenv("QUANTISHEET_CLAIMS_HOME")
    monkeypatch.setattr(os, "name", "nt")
    roaming = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(roaming))
    assert settings.home() == str(roaming / "ClaimIT")


def _sources():
    for d, _, fs in os.walk(PKG):
        for f in fs:
            if f.endswith(".py"):
                yield os.path.join(d, f)


def test_t12_never_imports_quantisheet_app():
    pat = re.compile(r"^\s*(import app\b|from app\b|import app\.|from app\.)", re.M)
    hits = [p for p in _sources() if pat.search(open(p, encoding="utf-8").read())]
    assert hits == []


def test_finding14_no_name_clash():
    # the package name and its modules sit outside app/, so nothing shadows
    # app/coverage.py, app/money.py, app/revisions.py or app/estimate.py
    assert os.path.basename(PKG) == "quantisheet_claims"
    import quantisheet_claims
    assert quantisheet_claims.__name__ == "quantisheet_claims"


def test_finding27_no_float_in_engine():
    engine = ("cents.py", "settle.py", "wbs.py", "diff.py", "revision.py",
              "recipes.py", "model.py", "interface.py")
    for name in engine:
        src = open(os.path.join(PKG, name), encoding="utf-8").read()
        code = re.sub(r'"""[\s\S]*?"""|#.*', "", src)
        assert "float(" not in code and " round(" not in code, name
