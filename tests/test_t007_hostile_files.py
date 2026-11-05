"""Threat model T-007 (0.13.14): every XML reader refuses DOCTYPE /
ENTITY declarations in any encoding and over-size files; xlsx members
are size-checked before they are unpacked (made-up files only)."""
import zipfile

import pytest

from app import bidtab, safexml, xfdf

BOMB = (b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><r>&b;</r>')


@pytest.mark.parametrize("data", [BOMB, BOMB.decode().encode("utf-16"),
                                  BOMB.decode().encode("utf-16-le")])
def test_declarations_refused_in_any_encoding(data):
    with pytest.raises((safexml.HostileFile, Exception)):
        safexml.fromstring(data)


def test_plain_xml_reads_and_size_cap():
    assert safexml.fromstring(b"<r><x>1</x></r>").find("x").text == "1"
    with pytest.raises(safexml.HostileFile):
        safexml.fromstring(b"<r>" + b"x" * 100 + b"</r>", max_bytes=50)


def test_xfdf_and_msproject_refuse_a_bomb(tmp_path):
    p = tmp_path / "evil.xfdf"
    p.write_bytes(BOMB)
    with pytest.raises(safexml.HostileFile):
        xfdf.parse(str(p))
    from app.pm import schedule
    with pytest.raises(safexml.HostileFile):
        schedule.import_msproject(None, str(p))


def test_xlsx_member_bomb_refused(tmp_path, monkeypatch):
    p = tmp_path / "bid.xlsx"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b"<a>" + b" " * 3_000_000 +
                   b"</a>")
    monkeypatch.setattr(safexml, "MAX_BYTES", 1_000_000)
    with pytest.raises(safexml.HostileFile):
        bidtab._xlsx_rows(str(p))


def test_master_schedule_reader_refuses_utf16_doctype(tmp_path):
    from app.pm.master.formats import common
    p = tmp_path / "s.xml"
    p.write_bytes(BOMB.decode().encode("utf-16"))
    out = {"errors": []}
    assert common.load(str(p), out) is None
    assert "DOCTYPE" in out["errors"][0]["text"]
