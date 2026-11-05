"""Job Cost Report import against the real report's layout (Nov 4): blank
cells are left out of a line, amounts sit right-aligned under their
headings, totals end in '*', every page repeats the job header, and the
report ends with job / report totals. Made-up job and numbers only."""
from quantisheet_backoffice.r111 import sagejc

# right edges of the seven column headings, as on the real report
EDGES = [211, 291, 371, 450, 530, 609, 689]
HEAD1 = ["Original", "Approved", "Total", "Total", "Remaining", "JTD",
         "Budget"]
HEAD2 = ["Estimate", "Changes", "Estimate", "Committed", "Commit", "Cost",
         "Variance"]


def _row(page, y, label, cells, star=False):
    """label words at the left, then {column index: text} right-aligned."""
    out, x = [], 40
    for t in label.split():
        out.append({"page": page, "x0": x, "y0": y, "x1": x + 6 * len(t),
                    "y1": y + 8, "t": t})
        x += 6 * len(t) + 4
    for col, t in cells.items():
        t = t + ("*" if star else "")
        x1 = EDGES[col] + (4 if star else 0)
        out.append({"page": page, "x0": x1 - 6 * len(t), "y0": y, "x1": x1,
                    "y1": y + 8, "t": t})
    return out


def _header(page, y0):
    w = _row(page, y0, "99-X-123 Example Pump Station", {})
    w += _row(page, y0 + 12, "100 Sample Rd", {})
    w += _row(page, y0 + 24, "Testville, SC 29000", {})
    for k, t in enumerate(HEAD1):
        w.append({"page": page, "x0": EDGES[k] - 6 * len(t), "y0": y0 + 40,
                  "x1": EDGES[k], "y1": y0 + 48, "t": t})
    for k, t in enumerate(HEAD2):
        w.append({"page": page, "x0": EDGES[k] - 6 * len(t), "y0": y0 + 52,
                  "x1": EDGES[k], "y1": y0 + 60, "t": t})
    return w


def _report():
    w = _header(0, 20)
    w += _row(0, 100, "01-025 Business Meals", {})
    w += _row(0, 112, "Other", {0: "1,500", 2: "1,500", 4: "1,500",
                                5: "1,450", 6: "50"})
    w += _row(0, 124, "Cost Code Totals", {0: "1,500", 1: "0", 2: "1,500",
                                           3: "0", 4: "1,500", 5: "1,450",
                                           6: "50"}, star=True)
    w += _row(0, 140, "01-051 Bond on Subcontractor", {})
    w += _row(0, 152, "Other", {0: "8,000", 2: "8,000", 3: "8,000",
                                5: "8,000"})
    w += _row(0, 164, "Subcontractor", {3: "12,000", 4: "12,000-",
                                        5: "12,000", 6: "12,000-"})
    w += _row(0, 176, "Cost Code Totals", {0: "8,000", 1: "0", 2: "8,000",
                                           3: "20,000", 4: "12,000-",
                                           5: "20,000", 6: "12,000-"},
              star=True)
    # page 2 repeats the header; its address lines must not become lines
    w += _header(1, 20)
    w += _row(1, 100, "02-100 Site Work", {})
    w += _row(1, 112, "Labor", {0: "5,000", 1: "1,000", 2: "6,000",
                                4: "6,000", 5: "4,000", 6: "2,000"})
    w += _row(1, 124, "Cost Code Totals", {0: "5,000", 1: "1,000",
                                           2: "6,000", 3: "0", 4: "6,000",
                                           5: "4,000", 6: "2,000"},
              star=True)
    w += _row(1, 150, "Job Totals", {0: "14,500", 2: "15,500",
                                     5: "25,450"}, star=True)
    w += _row(1, 170, "Report Totals", {0: "14,500"}, star=True)
    return w


def test_blank_cells_go_in_the_right_column():
    r = sagejc.parse_words(_report())
    assert r["job_number"] == "99-X-123"
    assert r["job_name"] == "Example Pump Station"
    assert r["address"] == "100 Sample Rd"
    assert [c["code"] for c in r["codes"]] == ["01-025", "01-051", "02-100"]
    other = r["codes"][0]["lines"][0]
    assert other["category"] == "Other"
    assert (other["original"], other["changes_amt"], other["committed"],
            other["jtd"], other["variance"]) == (150000, 0, 0, 145000, 5000)
    sub = r["codes"][1]["lines"][1]
    assert sub["committed"] == 1200000 and sub["remaining"] == -1200000
    assert sub["variance"] == -1200000 and sub["overrun"] == 1


def test_totals_match_their_lines_and_page_headers_are_skipped():
    r = sagejc.parse_words(_report())
    cols = ("original", "changes_amt", "total_estimate", "committed",
            "remaining", "jtd", "variance")
    for c in r["codes"]:
        cats = [ln for ln in c["lines"] if not ln["is_total"]]
        tot = [ln for ln in c["lines"] if ln["is_total"]]
        assert len(tot) == 1, c["code"]
        for k in cols:
            assert sum(ln[k] for ln in cats) == tot[0][k], (c["code"], k)
    cats = {ln["category"] for c in r["codes"] for ln in c["lines"]
            if not ln["is_total"]}
    assert cats == {"Other", "Subcontractor", "Labor"}   # no address lines
    # job / report totals don't become lines of the last code
    assert len(r["codes"][2]["lines"]) == 2
