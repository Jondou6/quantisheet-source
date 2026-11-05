"""Every module test runs with a temp home: nothing is read or written
under ~/.quantisheet or the real claims folder (brief 3.1, T12)."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def claims_home(tmp_path, monkeypatch):
    home = tmp_path / "claims_home"
    monkeypatch.setenv("QUANTISHEET_CLAIMS_HOME", str(home))
    from quantisheet_claims import settings
    settings.reload()
    yield home
    settings.reload()
