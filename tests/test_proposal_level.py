"""v21: level subs' emailed PDF proposals; plug numbers from past bids."""
import fitz
import pytest

from app import leveling, proposal_level as pl


def _pdf(path, lines):
    d = fitz.open()
    pg = d.new_page(width=612, height=792)
    y = 60
    for ln in lines:
        pg.insert_text((50, y), ln, fontsize=10)
        y += 16
    d.save(str(path))
    return str(path)


def _three(tmp_path):
    a = _pdf(tmp_path / "Acme quote.pdf", [
        "ACME PIPE INC", "PROPOSAL", "Project: Riverside WWTP - Yard Piping",
        "1   8\" PVC SDR-35 sewer   1,200 LF   $45.00   $54,000.00",
        "2   48\" precast manhole   6 EA   $4,200.00   $25,200.00",
        "3   Bypass pumping   Lump Sum   $12,000.00",
        "Total Base Bid: $91,200.00",
        "Alternate 1: Add rock excavation $8,500.00",
        "Exclusions:", "- Permits and fees", "- Testing",
        "Inclusions:", "- Traffic control"])
    b = _pdf(tmp_path / "Beta.pdf", [
        "Beta Utilities LLC", "Quotation",
        "8 inch PVC SDR-35 sewer 1200 LF $41.50 $49,800.00",
        "48 inch precast manhole 6 EA $3,900.00 $23,400.00",
        "TOTAL $73,200.00", "Excludes: bypass pumping, permits"])
    c = _pdf(tmp_path / "Cobra.pdf", [
        "COBRA CONSTRUCTION", "Bid Proposal",
        "8\" PVC SDR-35 sewer  1,200 LF  $47.00  $56,400.00",
        "48\" precast manhole  6 EA  $4,000.00  $24,000.00",
        "Bypass pumping  LS  $10,000.00",
        "Total: $90,400.00"])
    return [a, b, c]


def test_parse_lines_total_alternates_and_exclusions(tmp_path):
    p = pl.parse(_three(tmp_path)[0])
    assert p["bidder"] == "ACME PIPE INC"
    assert p["total"] == pytest.approx(91200)
    assert [(r["qty"], r["unit"], r["price"]) for r in p["lines"]] == [
        (1200, "LF", 45.0), (6, "EA", 4200.0), (1, "LS", 12000.0)]
    assert p["alternates"] == [{"desc": "Add rock excavation",
                                "amount": 8500.0, "no": "1"}]
    assert p["exclusions"] == ["Permits and fees", "Testing"]
    assert p["inclusions"] == ["Traffic control"]
    assert p["check"] == ""                         # lines add up to total


def test_inline_excludes_and_total_mismatch_flag(tmp_path):
    p = pl.parse(_three(tmp_path)[1])
    assert p["bidder"] == "Beta Utilities LLC"
    assert p["exclusions"] == ["bypass pumping", "permits"]
    assert p["total"] == pytest.approx(73200)
    p["total"] = 80000
    assert "differ" in pl.check(p)


def test_to_bids_levels_with_existing_engine(tmp_path):
    props = [pl.parse(f) for f in _three(tmp_path)]
    bids = pl.to_bids(props)
    assert set(bids) == {"ACME PIPE INC", "Beta Utilities LLC",
                         "COBRA CONSTRUCTION"}
    res = leveling.run(bids, min_bidders=2)
    omit = res["analysis"]["omissions"]["Beta Utilities LLC"]
    assert any("bypass" in i.desc.lower() for i in omit)


def test_plug_suggestion_prefers_past_bids(tmp_path):
    props = [pl.parse(f) for f in _three(tmp_path)]
    res = leveling.run(pl.to_bids(props), min_bidders=2)
    lib = [{"desc": "Bypass pumping", "unit": "LS", "esc_median": 15000.0,
            "bids": 7, "projects": 4},
           {"desc": "Asphalt patch", "unit": "SY", "esc_median": 60.0,
            "bids": 3, "projects": 2}]
    sug = pl.suggest_plugs(res, lib)
    s = next(x for x in sug if x["bidder"] == "Beta Utilities LLC")
    assert s["amount"] == pytest.approx(15000)
    assert s["source"].startswith("past bids: 7 bids on 4 projects")
    nolib = pl.suggest_plugs(res, [])
    s2 = next(x for x in nolib if x["bidder"] == "Beta Utilities LLC")
    assert s2["amount"] == pytest.approx(11000)      # median of this job
    assert s2["source"] == "this job's median (2 bids)"
    plugs = pl.as_plugs(sug)
    lev = leveling.run(pl.to_bids(props), min_bidders=2, plugs=plugs)
    beta = next(r for r in lev["results"]
                if r["bidder"] == "Beta Utilities LLC")
    assert beta["plugged"] == pytest.approx(15000)


def test_exclusion_report(tmp_path):
    props = [pl.parse(f) for f in _three(tmp_path)]
    rep = pl.exclusions_matrix(props)
    assert rep["permits"] == {"ACME PIPE INC": True,
                              "Beta Utilities LLC": True,
                              "COBRA CONSTRUCTION": False}
