"""PDF Management tab (Jon, Nov 6): every PDF tool on one tab, right after
Home - create, combine, export, compare, organize pages, page marks, edit,
OCR, redact, forms, sign, e-sign, protect, standards."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import quickaccess as QA                              # noqa: E402
from test_gui import win, qapp                                 # noqa: E402,F401

TAB = "PDF Management"


def _actions(win, tab=TAB):
    out = {}
    for title, group in win.ribbon.pages[tab].groups.items():
        for b in group.buttons:
            a = b.defaultAction()
            names = {b.text().replace("&&", "&")}
            if a is not None:
                names.add(a.text().replace("&&", "&").replace("…", "")
                          .strip())
                m = a.menu() or (b.menu() if hasattr(b, "menu") else None)
            else:
                m = b.menu() if hasattr(b, "menu") else None
            if m is not None:
                names |= {x.text().replace("…", "").strip()
                          for x in m.actions() if x.text()}
            for n in names:
                out.setdefault(n, set()).add(title)
    return out


def test_tab_sits_after_home_and_shows_without_a_file(win):
    tabs = list(win.ribbon.pages)
    assert tabs[0] == "Home" and tabs[1] == TAB
    assert TAB not in QA.hidden_tabs(None)
    assert "Pages" not in tabs and "Document" not in tabs


def test_groups_in_working_order(win):
    groups = list(win.ribbon.pages[TAB].groups)
    assert groups == list(QA.PDF_GROUPS), groups
    assert "Convert" not in win.ribbon.pages["Tools"].groups


def test_every_pdf_tool_has_a_button(win):
    have = _actions(win)
    want = {
        "Create PDF From File": "Create & Convert",
        "Combine Files": "Create & Convert",
        "Compare": "Create & Convert",
        "Organize Pages": "Pages", "Insert Pages From PDF": "Pages",
        "Replace Pages": "Pages", "Extract Pages": "Pages",
        "Delete Pages": "Pages", "Split Document": "Pages",
        "Crop Pages": "Pages", "Rotate Right": "Pages",
        "Header & Footer": "Page Marks", "Page Numbers": "Page Marks",
        "Bates Numbering": "Page Marks", "Watermark": "Page Marks",
        "Edit Text": "Content", "Make Searchable (OCR)": "Content",
        "Add Image": "Content", "Search & Redact": "Content",
        "Prepare Form (detect fields)": "Forms",
        "Flatten Markups & Fields": "Forms",
        "Signature": "Sign", "Request Signatures": "E-Sign",
        "Password Protect": "Protect", "Reduce File Size": "Protect",
        "Remove Hidden Information": "Protect",
        "Accessibility Check": "Standards", "PDF/A (archival)": "Standards",
    }
    missing = {k: v for k, v in want.items() if v not in have.get(k, ())}
    assert not missing, missing
    labels = [b.text() for g in win.ribbon.pages[TAB].groups.values()
              for b in g.buttons]
    assert "Export PDF" in labels


def test_no_other_product_named_on_the_tab(win):
    text = " ".join(_actions(win)).lower() + " " + " ".join(
        win.ribbon.pages[TAB].groups).lower() + " " + TAB.lower()
    for word in ("adobe", "acrobat", "bluebeam"):
        assert word not in text


def test_edit_pdf_is_one_of_the_first_three_buttons(win):
    """Jon, Nov 6: an Edit PDF button, one of the first three."""
    first = [b for g in win.ribbon.pages[TAB].groups.values()
             for b in g.buttons][:3]
    labels = [b.text().replace("&&", "&") for b in first]
    assert "Edit PDF" in labels, labels
    b = first[labels.index("Edit PDF")]
    assert b.defaultAction() is win.command("Edit PDF")
    from app.ribbon import clean
    menu = [clean(a.text()) for a in b.menu().actions()]
    for name in ("Edit Text", "Add Image", "Search & Redact",
                 "Organize Pages", "Crop Pages"):
        assert any(m.startswith(name) for m in menu), (name, menu)


def test_edit_pdf_turns_on_page_editing(win):
    seen = []
    base = win.command("Edit Text")
    base.triggered.connect(lambda *_a: seen.append(1))
    win.command("Edit PDF").trigger()
    assert seen == [1]
    assert "Ctrl+E" in win.command("Edit PDF").toolTip()
