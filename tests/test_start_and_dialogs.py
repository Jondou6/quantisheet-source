"""Stage 1 (speed and polish): Recent never lists throwaway temp files,
Open/Save boxes start in your last folder, and the installer's build check
keeps out of your settings."""
import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QFileDialog                    # noqa: E402

from app import filedialogs, settings                        # noqa: E402
from test_gui import qapp                                    # noqa: E402,F401


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})


def _real_dir():
    d = os.path.join(os.path.expanduser("~"), ".quantisheet-test-real")
    os.makedirs(d, exist_ok=True)
    return d


@pytest.fixture(autouse=True, scope="module")
def _tidy_real_dir():
    """Venice M14: the "real folder" these tests need (outside Temp) is
    removed afterwards, not left in the home folder."""
    yield
    import shutil
    shutil.rmtree(os.path.join(os.path.expanduser("~"),
                               ".quantisheet-test-real"), ignore_errors=True)


def test_temp_files_never_reach_recent():
    real = os.path.join(_real_dir(), "plans.pdf")
    open(real, "wb").close()
    tmp = os.path.join(tempfile.mkdtemp(prefix="quantisheet-smoke-"),
                       "smoke.pdf")
    open(tmp, "wb").close()
    settings.remember_recent(tmp)
    settings.remember_recent(real)
    assert settings.recent() == [real]
    # an old list that already has temp files in it is cleaned on read
    settings.set("recent", [tmp, real])
    assert settings.recent() == [real]
    assert settings.last_dir() == os.path.dirname(real)


def test_a_real_drawing_in_temp_still_counts():
    """Only the program's own temp files are left out: a drawing opened
    straight from an email (in Temp) is a real recent file."""
    mail = os.path.join(tempfile.mkdtemp(prefix="outlook-"), "C-101.pdf")
    open(mail, "wb").close()
    settings.remember_recent(mail)
    assert settings.recent()[0] == mail
    # an old build's check left "tmp…\\smoke.pdf" in Recent: not shown
    old = os.path.join(tempfile.mkdtemp(), "smoke.pdf")
    open(old, "wb").close()
    settings.set("recent", [old, mail])
    assert settings.recent() == [mail]


def test_open_box_starts_in_the_last_folder(monkeypatch):
    seen = []

    def fake(parent=None, caption="", dir="", filter=""):
        seen.append(dir)
        return (os.path.join(_real_dir(), "picked.pdf"), "PDF (*.pdf)")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(fake))
    monkeypatch.setattr(filedialogs, "_DONE", False)
    filedialogs.install()
    settings.set("last_dir", tempfile.gettempdir())   # temp is never used
    QFileDialog.getOpenFileName(None, "Open PDF", "", "PDF (*.pdf)")
    assert seen[-1] != tempfile.gettempdir() and os.path.isdir(seen[-1])
    # the folder you picked is remembered for next time
    assert settings.get("last_dir") == _real_dir()
    QFileDialog.getOpenFileName(None, "Open PDF")
    assert seen[-1] == _real_dir()
    # a suggested file name starts in that folder too
    QFileDialog.getOpenFileName(None, "Save", "report.pdf")
    assert seen[-1] == os.path.join(_real_dir(), "report.pdf")
    # an explicit folder is respected
    QFileDialog.getOpenFileName(None, "Open", tempfile.gettempdir())
    assert seen[-1] == tempfile.gettempdir()


def test_build_check_uses_private_settings(monkeypatch):
    from app import main
    before = settings.DIR
    main._private_settings()
    assert settings.DIR != before and "quantisheet-smoke-" in settings.DIR


def test_start_up_marks():
    from app import main
    main._mark("test step")
    assert main._MARKS[-1][0] == "test step" and main._MARKS[-1][1] >= 0


def test_splash_comes_before_the_main_window_code():
    """main.py must not import main_window at the top, or the splash waits
    for all of the program's code to load."""
    import ast
    import os
    src = open(os.path.join(os.path.dirname(__file__), "..", "app",
                            "main.py"), encoding="utf-8").read()
    top = [n for n in ast.parse(src).body
           if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any(getattr(n, "module", "") == "main_window" for n in top)


def test_start_page_cards_even_and_five_recent(qapp):
    from PySide6.QtGui import QAction
    from app import startpage
    files = []
    for i in range(7):
        p = os.path.join(_real_dir(), f"job{i}.pdf")
        open(p, "wb").close()
        files.append(p)
    settings.set("recent", files)
    acts = [(f"Card {i}", "a much longer subtitle than the others" if i == 2
             else "short", "open", QAction(f"a{i}")) for i in range(7)]
    page = startpage.StartPage(acts)
    page.resize(1400, 900)
    page.show()
    qapp.processEvents()
    assert page.recent.count() == startpage.RECENT_SHOWN == 5
    sizes = {(c.width(), c.height()) for c in page.cards}
    assert len(sizes) == 1, sizes                 # every card the same size
    assert page.recent.verticalScrollBar().isHidden() or \
        page.recent.verticalScrollBarPolicy() == \
        __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ScrollBarAlwaysOff
    page.close()


def test_python_temp_folders_only(tmp_path):
    """tmpXXXXXXXX (Python's own temp names) is throwaway; tmp_plans and
    templates are someone's real folders."""
    base = tempfile.gettempdir()
    assert settings._is_temp(os.path.join(base, "tmpa7oas68l", "smoke.pdf"))
    assert settings._is_temp(os.path.join(base, "quantisheet-x", "a.pdf"))
    assert settings._is_temp(base)
    assert not settings._is_temp(os.path.join(base, "tmp_plans", "C-101.pdf"))
    assert not settings._is_temp(os.path.join(base, "templates", "A.pdf"))
    assert not settings._is_temp(os.path.join(base, "tmpa7oas68lx", "A.pdf"))


def test_recent_lists_a_file_once():
    p = os.path.join(_real_dir(), "Twice.pdf")
    open(p, "wb").close()
    settings.set("recent", [p, p.upper() if os.name == "nt" else p, p])
    assert settings.recent() == [p]


def test_relative_start_folder_is_under_the_last_folder(monkeypatch):
    real = _real_dir()
    settings.set("last_dir", real)
    assert filedialogs._start_dir("sub/report.pdf") == \
        os.path.join(real, "sub/report.pdf")
    assert filedialogs._start_dir("report.pdf") == \
        os.path.join(real, "report.pdf")


def test_double_click_on_recent_opens_once(qapp):
    from PySide6.QtGui import QAction
    from app import startpage
    p = os.path.join(_real_dir(), "Once.pdf")
    open(p, "wb").close()
    settings.set("recent", [p])
    page = startpage.StartPage([("Open", "a PDF", "open", QAction("o"))])
    got = []
    page.open_path.connect(got.append)
    it = page.recent.item(0)
    page.recent.itemClicked.emit(it)        # what a double-click sends
    page.recent.itemClicked.emit(it)
    page.recent.itemActivated.emit(it)
    assert got == [p]
    page.close()


def test_dialog_caption_keyword_with_no_folder():
    """Grok F14: getOpenFileName(None, caption='x') used to pass caption
    twice (TypeError)."""
    seen = []

    def fake(*a, **k):
        seen.append((a, k))
        return ("", "")
    w = filedialogs._wrap(fake, 2)
    w(None, caption="Open")
    a, k = seen[-1]
    assert a[1] == "Open" and "caption" not in k and a[2]
    w(None, "Save", "out/r.pdf", "PDF (*.pdf)")
    a, k = seen[-1]
    assert a[2] == os.path.join(settings.last_dir(), "out/r.pdf")
    assert a[3] == "PDF (*.pdf)"
    w(parent=None, caption="Pick", dir="")
    a, k = seen[-1]
    assert a[1] == "Pick" and a[2] == settings.last_dir() and not k


def test_old_temp_names_only_for_the_old_smoke_file():
    """Round 2 (both reviews): Python-style tmpXXXXXXXX folders count only
    for the old build check's smoke.pdf; quantisheet_jobs is someone's."""
    base = tempfile.gettempdir()
    assert not settings._is_temp(os.path.join(base, "tmp_outlook", "x.pdf"))
    assert not settings._is_temp(os.path.join(base, "tmp3dmodels", "x.pdf"))
    assert not settings._is_temp(os.path.join(base, "tmpabcdefgh", "x.pdf"))
    assert settings._is_temp(os.path.join(base, "tmpabcdefgh", "smoke.pdf"))
    assert settings._is_temp(os.path.join(base, "tmpab12cd34", "smoke.pdf"))
    assert settings._is_temp(os.path.join(base, "pdfs_ocr_1", "a.pdf"))
    assert not settings._is_temp(os.path.join(base, "quantisheet_jobs", "a.pdf"))
    assert settings._is_temp(base + os.sep)


def test_unchanged_plain_values_are_not_rewritten(monkeypatch):
    settings.set("zoom_step", 1.25)
    writes = []
    real = settings.os.replace
    monkeypatch.setattr(settings.os, "replace",
                        lambda a, b: (writes.append(b), real(a, b)))
    settings.set("zoom_step", 1.25)
    assert writes == []
    lst = settings.get("recent") or []
    lst.append("x")                     # edited in place, then set again
    settings.set("recent", lst)
    assert writes                       # lists are always written


def test_restyled_cards_click_and_read_well(qapp):
    """Stage 3: icon tile, bold title, grey subtitle - and the whole card is
    still one button."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction
    from PySide6.QtTest import QTest
    from app import startpage
    hits = []
    a = QAction("o")
    a.triggered.connect(lambda *_: hits.append(1))
    page = startpage.StartPage([("Open a PDF", "Drawings, specs or any PDF "
                                 "and a lot more words than fit", "open", a)])
    page.resize(1200, 800)
    page.show()
    qapp.processEvents()
    card = page.cards[0]
    assert card.title.text() == "Open a PDF"
    assert card.sub.text().endswith("…")             # long subtitle elided
    assert card.text().startswith("Open a PDF\n")
    QTest.mouseClick(card, Qt.LeftButton, pos=card.sub.geometry().center())
    qapp.processEvents()
    assert hits == [1]                       # a click on the subtitle counts
    page.close()


def test_start_page_never_makes_the_window_taller(qapp):
    """Stage 3 cards are taller: the page scrolls rather than stretching the
    window past the bottom of a 1080p (or 150 %-scaled) screen."""
    from PySide6.QtGui import QAction
    from app import startpage
    acts = [(f"Card {i}", "short", "open", QAction(f"a{i}")) for i in range(9)]
    page = startpage.StartPage(acts)
    assert page.minimumSizeHint().height() < 400


def test_splash_shows_the_version(qapp):
    """Jon, Oct 19: the splash says which version is starting."""
    from PySide6.QtGui import QColor, QPixmap
    from app import __version__, main
    assert main.splash_version_text() == f"Version {__version__}"
    pm = QPixmap(1200, 700)
    pm.fill(QColor("white"))
    main._stamp_version(pm)
    img = pm.toImage()
    # something was written in the band under the tagline, on the left
    dark = sum(1 for x in range(60, 400, 2) for y in range(450, 485, 2)
               if img.pixelColor(x, y).lightness() < 200)
    assert dark > 20


def test_start_cards_never_cut_off_their_text(qapp):
    """Jon, Oct 30: with larger Windows text the bottoms of g, p and y
    were cut off on the start page. Cards and the title grow to fit."""
    from PySide6.QtGui import QAction
    from app import startpage
    page = startpage.StartPage([("Open a project folder",
                                 "Every sheet of a job in one list",
                                 "folder", QAction("o"))])
    page.setStyleSheet("#StartCardTitle { font-size: 22pt; } "
                       "#StartCardSub { font-size: 18pt; } "
                       "#StartTitle { font-size: 44pt; }")
    page.resize(1200, 900)
    page.show()
    qapp.processEvents()
    card = page.cards[0]
    assert card.height() > startpage.CARD_HEIGHT
    for lab in (card.title, card.sub, page._heads[0]):
        assert lab.height() >= lab.fontMetrics().height(), lab.text()
    page.close()


def test_splash_shows_only_this_computers_company(qapp, tmp_path,
                                                  monkeypatch):
    """Nov 3 (Jon): the shipped splash has no company on it; the company
    saved on this computer (proposal company details) is drawn on it."""
    from PySide6.QtGui import QColor, QImage, QPixmap
    from app import main, settings
    pm = QPixmap(1200, 700)
    pm.fill(QColor("white"))
    monkeypatch.setattr(settings, "get", lambda k, d=None: {} if k ==
                        "company" else d)
    assert main.splash_company() == ("", "")
    before = pm.toImage().copy()
    main._stamp_company(pm)
    assert pm.toImage() == before                    # nothing drawn
    logo = str(tmp_path / "logo.png")
    img = QImage(200, 80, QImage.Format_RGB32)
    img.fill(QColor(20, 90, 40))
    img.save(logo)
    monkeypatch.setattr(settings, "get", lambda k, d=None: {
        "name": "Test Builders", "logo": logo} if k == "company" else d)
    assert main.splash_company() == ("Test Builders", logo)
    main._stamp_company(pm)
    out = pm.toImage()
    assert out.pixelColor(100, 90).green() < 150     # the logo
    assert out.pixelColor(80, 320) != QColor("white")  # the "by" label
