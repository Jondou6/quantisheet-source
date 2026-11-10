"""Chief's round-5 re-test of 0040464 (Nov 9): one test per problem he
found. Made-up data only."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402
import pytest                                                  # noqa: E402

from test_review_fixes_nov7 import _image_pdf, _image_size     # noqa: E402


# ---- 1: money rounds half up -----------------------------------------------------

def test_c2_rounds_half_up():
    from app.dmoney import c2
    assert c2(1.125) == 1.13
    assert c2(0.125) == 0.13
    assert c2(1.25 * 0.1) == 0.13
    assert c2(1.15 * 0.1) == 0.12            # 0.11499999999999999 in float
    assert c2(2.675) == 2.68
    assert c2(-0.125) == -0.13
    assert c2(0.1 + 0.2) == 0.3
    assert c2(1234567.885) == 1234567.89


def test_decimal_default_is_half_up_on_every_thread():
    import threading
    from decimal import Decimal
    import app                                                 # noqa: F401
    assert Decimal("1.125").quantize(Decimal("0.01")) == Decimal("1.13")
    got = []
    t = threading.Thread(target=lambda: got.append(
        Decimal("0.125").quantize(Decimal("0.01"))))
    t.start()
    t.join()
    assert got == [Decimal("0.13")]


def test_retainage_on_1_25_is_13_cents():
    from app import money
    d = fitz.open()
    d.new_page()
    money.set_info(d, 10, 10, project="Example Job", owner="Example Owner",
                   contractor="Example Builders")
    money.set_sov(d, [{"desc": "Example line", "scheduled": 100}])
    no = money.new_pay_app(d, "2026-01-31")
    money.set_progress(d, no, money.sov(d)[0]["item"], work=1.25)
    v = money.compute(d, no)
    assert v["totals"]["retainage"] == 0.13
    assert v["g702"]["5a"] == pytest.approx(0.13)
    assert v["rows"][0]["retainage"] == 0.13


def test_bid_with_12_5_percent_overhead_is_1_13():
    from app import bidbuild
    b = bidbuild.build([{"key": "a", "trade": "Example", "direct": 1.00,
                         "material": 0.0}], {"overhead": 12.5})
    assert b["total"] == 1.13
    assert b["lines"][0]["price"] == 1.13


def test_proposal_money_text_rounds_half_up():
    from app import money, proposal
    assert proposal._money(0.125) == "$0.13"
    assert money._m(1.125) == "$1.13"
    assert money._m(-1.125) == "($1.13)"


# ---- 2: the summary's sheet numbers and scales -------------------------------------

def test_made_up_sheet_and_scale_are_marked():
    from app.ai import review
    src = ("A-101 FIRST FLOOR PLAN SCALE: 1/4\" = 1'-0\" "
           "A-102 ROOF PLAN SCALE: 1/4\" = 1'-0\" SEE A-302. "
           "GRAB BAR B-233. 3/4\" PLYWOOD")
    reply = ("- A-100 is the cover sheet.\n"
             "- The floor plan is at 1/8\" = 1'-0\".\n"
             "- A-101 and A-102 are drawn at 1/4\" = 1'-0\".\n"
             "- Plans at a scale of 1/8 inch.\n"
             "- See A-302; B-233 grab bars; 3/4\" plywood.")
    out, flagged = review.check_facts(reply, src, ["A-101", "A-102"])
    assert "A-100 (no such sheet in the drawings)" in out
    assert out.count("(this scale isn't in the drawings)") == 2
    assert "A-101 and A-102 are drawn at 1/4\" = 1'-0\".\n" in out
    assert "A-302 (no such" not in out and "B-233 (no such" not in out
    assert "3/4\" plywood" in out
    assert flagged == ["A-100", 'scale 1/8"']


def test_summary_footer_names_what_was_made_up(monkeypatch):
    from app.ai import review
    monkeypatch.setattr(review, "_ollama", lambda prompt: (
        "- A-100 is the cover sheet.\n- Plans at 1/8\" = 1'-0\"."))
    out = review.summarize_text("A-101 FLOOR PLAN SCALE: 1/4\" = 1'-0\"",
                                in_set=["A-101"])
    assert "Not in the document - stated by the AI: A-100; scale 1/8\"" \
        in out


# ---- 3: Watermark + Reduce keeps a protected file protected ------------------------

def _locked(tmp_path):
    d = fitz.open(_image_pdf(str(tmp_path / "plain.pdf")))
    p = str(tmp_path / "locked.pdf")
    perms = fitz.PDF_PERM_PRINT | fitz.PDF_PERM_ACCESSIBILITY
    d.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner-x",
           user_pw="", permissions=perms)
    d.close()
    return p, perms


def _check_protected(path, perms):
    with fitz.open(path) as r:
        assert r.metadata.get("encryption"), "the password was lost"
        assert r.permissions & fitz.PDF_PERM_MODIFY == 0
        assert r.permissions & fitz.PDF_PERM_PRINT
        assert r.authenticate("owner-x")


@pytest.mark.parametrize("forced", [True, False])
def test_watermark_and_reduce_keep_the_password(tmp_path, monkeypatch,
                                                forced):
    from app import acrobat, acrobat2
    p, perms = _locked(tmp_path)
    if forced:                       # the "not smaller" path
        real = acrobat.reduce_size
        monkeypatch.setattr(acrobat, "reduce_size",
                            lambda doc, path, **k: real(doc, path,
                                                        original=10))
    res = acrobat2.run_batch([p], ["watermark", "reduce"],
                             str(tmp_path / "o"), {"watermark": "DRAFT"})
    out = res[0][1]
    assert not str(out).startswith(("ERROR", "SKIPPED")), res
    _check_protected(out, perms)


def test_watermark_alone_keeps_the_password(tmp_path):
    from app import acrobat2
    p, perms = _locked(tmp_path)
    res = acrobat2.run_batch([p], ["watermark"], str(tmp_path / "o"),
                             {"watermark": "DRAFT"})
    assert not str(res[0][1]).startswith("ERROR"), res
    _check_protected(res[0][1], perms)
