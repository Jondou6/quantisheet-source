"""Command line: sanitize with proof, Generate Set (Venice's headless CLI)."""
import json
import os

import fitz
import pytest

from app import cli


def _dirty(tmp_path):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), "SHEET A-101")
    d.set_metadata({"author": "Someone", "title": "Secret job"})
    d.embfile_add("notes.txt", b"private")
    p.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(10, 10, 50, 50),
                   "uri": "https://example.com"})
    d.set_xml_metadata('<?xpacket begin=""?><x:xmpmeta xmlns:x="adobe:ns:'
                       'meta/"></x:xmpmeta><?xpacket end="w"?>')
    src = str(tmp_path / "dirty.pdf")
    d.save(src)
    d.close()
    return src


def test_proof_sees_xml_metadata(tmp_path):
    from app import acrobat2
    d = fitz.open(_dirty(tmp_path))
    rows = {i: st for st, i, _d in acrobat2.verify_clean(d)}
    assert rows["XML metadata (document and pages)"] == "FAIL"
    acrobat2.sanitize(d)
    rows = {i: st for st, i, _d in acrobat2.verify_clean(d)}
    assert rows["XML metadata (document and pages)"] == "PASS"


def test_cli_sanitize_proves_the_saved_file(tmp_path, capsys):
    src = _dirty(tmp_path)
    out = str(tmp_path / "clean.pdf")
    man = str(tmp_path / "clean.json")
    rc = cli.main(["sanitize", src, "--out", out, "--manifest", man])
    assert rc == 0, capsys.readouterr().out
    assert "CLEAN" in capsys.readouterr().out
    rep = json.load(open(man))
    assert rep["clean"] and len(rep["sha256"]) == 64
    assert all(c["status"] == "PASS" for c in rep["checks"])
    d = fitz.open(out)
    assert "A-101" in d[0].get_text() and not d.metadata.get("author")
    d.close()


def test_cli_sanitize_exit_2_when_not_clean(tmp_path, monkeypatch, capsys):
    from app import acrobat2
    monkeypatch.setattr(acrobat2, "sanitize",
                        lambda doc, **k: ["scripts"])        # nothing removed
    rc = cli.main(["--json", "sanitize", _dirty(tmp_path),
                   "--out", str(tmp_path / "c.pdf")])
    assert rc == 2
    rep = json.loads(capsys.readouterr().out)
    assert not rep["clean"] and rep["steps_failed"] == ["scripts"]


def test_cli_genset_passes_its_options_through(tmp_path, monkeypatch):
    seen = {}

    def fake(argv):
        seen["argv"] = argv
        return 0
    import app.genset.__main__ as gm
    monkeypatch.setattr(gm, "main", fake)
    rc = cli.main(["genset", "--brief", "1600 sf 3 bed house", "--no-ai",
                   str(tmp_path / "g.pdf")])
    assert rc == 0
    assert seen["argv"][:2] == ["--brief", "1600 sf 3 bed house"]


def test_cli_genset_no_set_exit_2(tmp_path, capsys):
    rc = cli.main(["genset", "--brief", "300 sf cabin", "--no-ai",
                   str(tmp_path / "g.pdf")])
    assert rc == 2
    assert "No set made" in capsys.readouterr().err
    assert not os.path.exists(tmp_path / "g.pdf")
