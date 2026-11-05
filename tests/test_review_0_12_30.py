"""Fixes from the 0.12.30 review: Excel (Windows-1252) CSVs import, 5xx
answers are worded as the service's trouble, an AI part failing keeps the
other parts, and crashes are dated."""
import io
import time
import urllib.error

import pytest

from app import aerial, assembly_csv, costbook, heavy, textio


def _cp1252(tmp_path, name, text):
    p = tmp_path / name
    p.write_bytes(text.encode("cp1252"))
    return str(p)


def test_text_reader_falls_back_to_windows_1252(tmp_path):
    p = _cp1252(tmp_path, "x.csv", "a,b\nPipe – 8”,1\n")
    assert "–" in textio.read_text(p)
    u = tmp_path / "u.csv"
    u.write_bytes(b"\xef\xbb\xbfa,b\n")                   # Excel UTF-8 BOM
    assert textio.read_text(str(u)) == "a,b\n"


def test_wages_cost_book_and_assemblies_read_excel_csvs(tmp_path):
    lib = heavy.library()
    p = _cp1252(tmp_path, "wd.csv", "Classification,Rate,Fringe\n"
                "Laborer – general,$21.50,4.10\n")
    wages, left = heavy.read_wages_csv(p, lib)
    assert wages["LAB"]["base"] == "21.50"
    p = _cp1252(tmp_path, "prices.csv",
                "Code,Description,Unit,Material,Labor,Crew\n"
                "092116,Gyp board – 5/8”,sf,1.00,0.02,D-2\n")
    c = costbook.from_csv(p)
    assert "\u2013" in c.get("092116")["desc"]
    head = ",".join(assembly_csv.COLUMNS)
    p = _cp1252(tmp_path, "asm.csv", head + "\n" +
                "A1,Wall – test,09,Finishes,,SF,Area,,1,Stud “3-5/8”,"
                "Material,LF,Qty,1,0,\n")
    items, _problems = assembly_csv.parse(p)
    assert items


class _Busy(urllib.error.HTTPError):
    def __init__(self, code=502):
        super().__init__("http://x", code, "Bad Gateway", {}, io.BytesIO())


def test_502_is_the_service_having_trouble(monkeypatch):
    calls = []

    def get(url, params, timeout=60):
        calls.append(url)
        raise _Busy()
    monkeypatch.setattr(aerial, "_get", get)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError) as e:
        aerial.geocode("716 4th Ave N, Surfside Beach, SC")
    assert "having trouble right now (502)" in str(e.value)
    assert "internet" not in str(e.value)
    assert len(calls) == 2                                 # one retry


def test_one_failed_ai_part_keeps_the_others():
    from app.ai import rfi_finder
    pages = [(i, f"A-{i}", "PLAN", "x " * 4000) for i in range(6)]
    n = {"i": 0}

    def ask(prompt):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("500 token repeat limit reached")
        return '{"items": [{"question": "Q%d?", "page": 1}]}' % n["i"]
    out = rfi_finder.ai_review_specs(pages, ask, limit=9000, max_chunks=4)
    assert len(out) >= 2
    assert out.skipped and "part 2" in out.skipped[0]

    def bad(prompt):
        raise RuntimeError("model gone")
    with pytest.raises(RuntimeError):
        rfi_finder.ai_review_specs(pages, bad, limit=9000, max_chunks=2)
