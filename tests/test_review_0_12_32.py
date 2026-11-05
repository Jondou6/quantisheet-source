"""Fixes from the 0.12.32 review (main session's share): the last four
CSV importers read Excel's Windows-1252 files (N2 leftovers), and the
PyMuPDF pin."""
import os
import re


def _cp1252(tmp_path, name, text):
    p = tmp_path / name
    p.write_bytes(text.encode("cp1252"))
    return str(p)


def test_pay_items_read_an_excel_csv(tmp_path):
    from app import heavy
    p = _cp1252(tmp_path, "items.csv", "Item,Description,Unit,Quantity\n"
                "1,Pipe – 8” PVC,LF,120\n")
    rows = heavy.read_pay_items(p)
    assert "–" in str(rows)


def test_actuals_read_an_excel_csv(tmp_path):
    from app import pricehistory
    p = _cp1252(tmp_path, "jc.csv", "Cost Code,Description,Amount\n"
                "03 30 00,Slab – east half,1200.00\n")
    assert pricehistory.read_actuals_csv(p) is not None


def test_bid_form_table_reads_an_excel_csv(tmp_path):
    from app.pm import bidforms
    p = _cp1252(tmp_path, "bid.csv", "Item,Description\n1,Fence – "
                "6’ chain link\n")
    assert "–" in str(bidforms._read_table(p))


def test_assembly_codes_read_an_excel_csv(tmp_path):
    from app import assembly_codes
    p = _cp1252(tmp_path, "codes.csv", "Code,Name\nA1,Wall – CMU\n")
    assert "–" in str(assembly_codes._rows(p))


def test_pymupdf_is_pinned_below_2():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("requirements.txt", "pyproject.toml"):
        with open(os.path.join(root, name), encoding="utf-8") as f:
            txt = f.read().lower()
        m = re.search(r"pymupdf[^\n\"]*", txt)
        assert m and "<2" in m.group(0), name
