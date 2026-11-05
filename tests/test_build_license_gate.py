"""Reviews 1 + 2 (Nov 4): the release build stops on an AGPL / GPL /
unknown license unless docs/LICENSE_DECISIONS.json records a decision."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _gate(monkeypatch, tmp_path, decisions):
    import build_installer as bi
    p = tmp_path / "LICENSE_DECISIONS.json"
    p.write_text(json.dumps({"accepted": decisions}))
    monkeypatch.setattr(bi, "LICENSE_DECISIONS", str(p))
    monkeypatch.setattr(bi, "log", lambda *a: None)
    return bi


def test_an_unrecorded_agpl_package_stops_the_build(monkeypatch, tmp_path):
    bi = _gate(monkeypatch, tmp_path, {})
    res = {"loud": [("AGPL", "PyMuPDF", "1.0", "AGPL-3.0")]}
    with pytest.raises(RuntimeError, match="PyMuPDF"):
        bi.license_gate(res)


def test_a_recorded_decision_lets_it_through(monkeypatch, tmp_path):
    bi = _gate(monkeypatch, tmp_path, {"pymupdf": {
        "flag": "AGPL", "for": "in-house testers only"}})
    assert bi.license_gate({"loud": [("AGPL", "PyMuPDF", "1.0", "x")]})
    # a different flag for the same package is not covered
    with pytest.raises(RuntimeError):
        bi.license_gate({"loud": [("GPL", "PyMuPDF", "1.0", "x")]})


def test_the_shipped_decisions_file_is_valid():
    with open(os.path.join(ROOT, "docs", "LICENSE_DECISIONS.json"),
              encoding="utf-8") as fh:
        d = json.load(fh)
    assert d["accepted"]["pymupdf"]["for"] == "in-house testers only"
