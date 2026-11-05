"""Second-symbol training for auto count (v27).

When 3+ rejected hits in the count review look alike (count_triage.
Triage.second_symbol_suggestion), they are probably a different symbol.
This turns them into a new count group: the first rejected hit's rect is
the template, run through the viewer's own count_symbol(rect) (with the
review list), so it is found and reviewed like any other symbol.

Flow: wire(dlg, group) adds a "Train as second symbol" button to the
CountReviewDialog (after count_triage.attach). Clicking it keeps the
current review (OK - the accepted hits are counted as usual) and leaves
dlg.second_symbol_request; the viewer then calls after_review(view, dlg),
which starts the second count. Hit rects are in the same page coordinates
as symbol_template / count_symbol use, so no conversion is needed.
"""
import fitz

SUFFIX = "2nd symbol"


def _name(base, existing):
    n, name = 1, f"{base} ({SUFFIX})"
    while name in existing:
        n += 1
        name = f"{base} ({SUFFIX} {n})"
    return name


def plan(suggestion, base_group, existing=()):
    """{group, page, rect, rects} for the suggestion, or None."""
    if not suggestion or not suggestion.get("hits"):
        return None
    hs = suggestion["hits"]
    first = hs[0]
    return {"group": _name(base_group or "Count", set(existing)),
            "page": first["page"], "rect": fitz.Rect(first["rect"]),
            "rects": [(h["page"], fitz.Rect(h["rect"])) for h in hs]}


def train(view, p, all_pages=None):
    """Count the new symbol with the viewer's count_symbol (review on).
    Returns what count_symbol returns (marks added)."""
    if not p:
        return 0
    view.go_to(p["page"])
    return view.count_symbol(fitz.Rect(p["rect"]), group=p["group"],
                             all_pages=all_pages, review=True)


def _groups(dlg):
    try:
        from . import annotate
        return {i.get("group") for i in annotate.takeoff_items(dlg.doc)}
    except Exception:
        return set()


def wire(dlg, base_group):
    """Add the button to a CountReviewDialog that has count_triage.attach
    on it. Shown only while there is a suggestion."""
    from PySide6.QtWidgets import QPushButton
    btn = QPushButton("Train as second symbol")
    btn.setToolTip("Count the rejected look-alikes as their own symbol")
    btn.hide()
    lay = dlg.layout()
    lay.insertWidget(min(4, lay.count()), btn)
    dlg.second_symbol_request = None
    dlg.second_symbol_button = btn

    def refresh():
        t = getattr(dlg, "triage", None)
        s = t.second_symbol_suggestion() if t is not None else None
        btn.setVisible(bool(s))
        if s:
            btn.setText(f"Train {len(s['hits'])} rejected look-alikes as a "
                        "second symbol")

    old = dlg._count

    def count_and_refresh(*a, **k):
        r = old(*a, **k)
        refresh()
        return r
    dlg._count = count_and_refresh

    def go():
        s = dlg.triage.second_symbol_suggestion()
        dlg.second_symbol_request = plan(s, base_group, _groups(dlg))
        if dlg.second_symbol_request:
            dlg.accept()
    btn.clicked.connect(go)
    refresh()
    return btn


def after_review(view, dlg):
    """Call after the first review's marks are applied."""
    p = getattr(dlg, "second_symbol_request", None)
    dlg.second_symbol_request = None
    return train(view, p) if p else 0
