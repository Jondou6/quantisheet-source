"""Store listing review (Chief, Oct 30): the Privacy page names every
outside service, and the uninstaller offers to delete QuantiSheet's own
data - asked, No by default, never in a silent uninstall."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_privacy_page_names_every_outside_service():
    from app import legal
    html = legal.privacy_html()
    for word in ("Dropbox", "DocuSign", "Outlook", "Open-Meteo", "USGS",
                 "Census", "FEMA", "Fish and Wildlife", "AIHost",
                 "OfflineMode", "DisableAI", "Deleting your data"):
        assert word in html, word


def test_uninstall_asks_before_deleting_data():
    iss = open(os.path.join(ROOT, "installer", "quantisheet.iss"),
               encoding="utf-8-sig").read()
    i = iss.index("usPostUninstall")
    block = iss[i:i + 900]
    assert "not UninstallSilent" in block
    assert "MB_DEFBUTTON2" in block and "IDYES" in block      # No default
    assert "{%USERPROFILE}\\.quantisheet" in block
    assert "Software\\QuantiSheet\\Cache" in block
    assert "Your drawings and job folders are not touched" in block


def test_no_code_line_starts_with_a_hash():
    """Inno's preprocessor reads a line starting with # as a directive and
    the build stops (Oct 30)."""
    for name in ("quantisheet.iss", "quantisheet_server.iss",
                 "quantisheet_claims.iss"):
        text = open(os.path.join(ROOT, "installer", name),
                    encoding="utf-8-sig").read()
        code = text[text.index("\n[Code]"):] if "\n[Code]" in text else ""
        bad = [ln for ln in code.splitlines() if ln.lstrip().startswith("#")]
        assert bad == [], (name, bad)


def test_pages_never_point_at_a_contact_about_does_not_show(monkeypatch):
    """Chief's r46 retest X1."""
    from app import betalicense, legal
    monkeypatch.setattr(legal, "_pub", lambda: {
        "name": "QuantiSheet", "state": "", "contact": ""})
    for store, want in ((True, "Microsoft Store page"),
                        (False, "who gave you QuantiSheet")):
        monkeypatch.setattr(betalicense, "is_store", lambda s=store: s)
        for page in (legal.terms_html(), legal.privacy_html()):
            assert "shown in Help > About" not in page
            assert want in page
