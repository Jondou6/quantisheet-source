"""r36 v2 step 5 (safety): the customer quote PDF has its own small
renderer (quote_pdf.py) instead of proposal.py's private helpers
(_Writer, _header, _lines, _acceptance), so a later change to
proposal.py's internals can't break the quote. The output is the same as
the step-4 quote: every text span (text, where it starts and ends, font, size, colour) and
every line drawn is compared with a golden copy made from the step-4 code
(tests/data/r36_quote_pdf_golden.json). Made-up data only."""
import json
import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, proposal as P, settings  # noqa: E402,E501
from app.estimating import quotes                             # noqa: E402
from estimate_helpers import blank_doc                        # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "data", "r36_quote_pdf_golden.json")
COMP = {"name": "Test Builders LLC", "address": "1 Test St\nTest City, SC",
        "phone": "555-0100", "email": "test@example.invalid",
        "website": "example.invalid", "license": "T-123",
        "signer": "Test Signer", "title": "Estimator", "logo": ""}
DATA = {"project": "Test Project", "client": "Test Client",
        "attention": "Test Person", "client_address": "2 Test Rd\nTestville",
        "project_address": "3 Job Ln", "number": "T-0001",
        "date": "2026-10-01", "valid_days": "45",
        "terms": "Test terms - half down, half on completion.",
        "exclusions": "Test permits\n- Test dumpster"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def cases():
    """(name, doc, spec) - one with options, tiers and every section, one
    long enough for several pages, one plain."""
    out = []
    d = blank_doc()
    ids = EL.add(d, [
        EL.new_line("Test demo", 1, "ls", sub=1000),
        EL.new_line("Test basic shingles", 20, "sq", mat=100),
        EL.new_line("Test arch shingles", 20, "sq", mat=150),
        EL.new_line("Test metal roof", "20.456", "sq", mat=400),
        EL.new_line("Test gutter guards", 1, "ls", mat=500),
        EL.new_line("TEST WALL MOUNTED DATA OUTLET - STUBBED ABOVE LIFT-OUT "
                    "CEILING WITH PULL STRING AND BUSHING", 12, "ea", sub=165),
    ])
    spec = quotes.blank()
    spec.update(pct="15", title="Test Roof Quote", notes="Test note \u2014 "
                "\u201cquoted\u201d \u2022 dash", inclusions=["Test tear-off"],
                assign={ids[1]: "Good", ids[2]: "Better", ids[3]: "Best",
                        ids[4]: quotes.OPTION},
                tier_notes={"Better": "Test better note"},
                selected_tier="Better", accepted_options=[ids[4]])
    out.append(("tiers", d, spec))
    d2 = blank_doc()
    EL.add(d2, [EL.new_line(f"Test line {i:03d}", i + 1, "ea", mat=i + 3)
                for i in range(90)])
    out.append(("long", d2, quotes.blank()))
    d3 = blank_doc()
    o = EL.add(d3, [EL.new_line("Test patch", 3, "ea", lab=50),
                    EL.new_line("Test extra", 1, "ls", sub=75)])
    s3 = quotes.blank()
    s3.update(tiers=[], assign={o[1]: quotes.OPTION})
    out.append(("options_only", d3, s3))
    return out


def summary(out):
    """Every span and drawn line of a PDF, rounded (what a reader sees).
    Span boxes depend on PyMuPDF's global small-glyph-heights switch,
    which the main window turns on: measured with it off (as the golden
    copy was), then put back."""
    import fitz
    prev = fitz.TOOLS.set_small_glyph_heights()
    fitz.TOOLS.set_small_glyph_heights(False)
    try:
        return _summary(out)
    finally:
        fitz.TOOLS.set_small_glyph_heights(prev)


def _summary(out):
    pages = []
    for page in out:
        spans = []
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for sp in ln["spans"]:
                    # where the text was put (origin) and where it ends -
                    # not the box height, which differs by PyMuPDF setting
                    spans.append([sp["text"],
                                  [round(v, 1) for v in sp["origin"]],
                                  round(sp["bbox"][2], 1),
                                  sp["font"], round(sp["size"], 2),
                                  sp["color"]])
        draws = [[[round(v, 1) for v in dr["rect"]],
                  [round(c, 3) for c in (dr.get("color") or ())],
                  round(dr.get("width") or 0, 2)]
                 for dr in page.get_drawings()]
        pages.append({"size": [round(page.rect.width, 1),
                               round(page.rect.height, 1)],
                      "spans": spans, "draws": draws})
    return {"pages": pages, "meta": {k: out.metadata.get(k) for k in
                                     ("title", "author", "creator")}}


def render_all():
    res = {}
    for name, d, spec in cases():
        out = quotes.make_pdf(d, spec, comp=dict(COMP), data=dict(DATA))
        res[name] = summary(out)
        out.close()
    return res


def test_quote_pdf_same_as_step_4():
    with open(GOLDEN, encoding="utf-8") as f:
        want = json.load(f)
    got = render_all()
    assert set(got) == set(want)
    for name in want:
        assert len(got[name]["pages"]) == len(want[name]["pages"]), name
        for i, (g, w) in enumerate(zip(got[name]["pages"],
                                       want[name]["pages"])):
            assert g["size"] == w["size"], (name, i)
            assert g["spans"] == w["spans"], (name, i)
            assert g["draws"] == w["draws"], (name, i)
        assert got[name]["meta"] == want[name]["meta"], name
    assert len(want["long"]["pages"]) >= 3          # page breaks covered


def test_quote_pdf_does_not_use_proposal_private_helpers(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("proposal.py private helper used")
    for name in [n for n in dir(P) if n.startswith("_") and
                 not n.startswith("__")]:
        if callable(getattr(P, name)):
            monkeypatch.setattr(P, name, boom)
    for n in ("LEFT", "RIGHT", "TOP", "BOTTOM", "GREY", "NAVY", "INK",
              "RULE", "PAPER"):
        monkeypatch.delattr(P, n)
    name, d, spec = cases()[0]
    out = quotes.make_pdf(d, spec, comp=dict(COMP), data=dict(DATA))
    assert "Test Roof Quote" in out[0].get_text()
    out.close()


def test_quote_sources_name_no_private_proposal_helper():
    from app.estimating import quote_pdf
    for mod in (quotes, quote_pdf):
        src = open(mod.__file__, encoding="utf-8").read()
        assert not re.search(r"\bP\._|proposal\._|\bP\.[A-Z]{2,}", src), \
            mod.__name__


def test_quote_pdf_public_helper_used_by_quotes():
    from app.estimating import quote_pdf
    for name in ("Writer", "header", "acceptance", "bullet_lines"):
        assert callable(getattr(quote_pdf, name))
    assert quote_pdf.bullet_lines("a\n- b\n\u2022 c\n\n") == ["a", "b", "c"]


if __name__ == "__main__":                        # make the golden copy
    import sys
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(render_all(), f, indent=0)
