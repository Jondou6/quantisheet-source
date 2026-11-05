"""The quarterly restore drill quotes the menus that are actually in the
program (docs/RESTORE_DRILL.md)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs", "RESTORE_DRILL.md")


def _doc():
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


def _checks(text):
    found = []
    for line in text.splitlines():
        if not line.startswith("CHECK "):
            continue
        path, sep, quoted = line[len("CHECK "):].partition(" | ")
        assert sep, line
        found.append((path.strip(), quoted))
    return found


def test_checked_strings_match_the_source():
    checks = _checks(_doc())
    assert len(checks) >= 15
    for rel, quoted in checks:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            src = fh.read()
        assert quoted in src, (rel, quoted)


def test_drill_covers_the_three_parts_and_the_mismatches():
    text = _doc()
    assert "once a quarter" in text
    assert "qs-drill" in text
    assert ".qskey" in text
    assert "quantisheet_estimate.json" in text
    assert "no top-level menu named Back Office" in text
    assert 'no command named "Open a Job"' in text
    assert "r111/menu.py" in text
    assert "Payroll Key & Approvals" in text
    assert "UNVERIFIED" in text
    # the menu labels use the ellipsis character, not three dots
    assert "Back Up My QuantiSheet Data…" in text
    assert "Restore QuantiSheet Data From a Backup…" in text
    assert "Back Up My QuantiSheet Data..." not in text
