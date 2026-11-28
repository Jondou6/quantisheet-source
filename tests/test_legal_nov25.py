"""Terms 1.1 and the Privacy page match what the program does now (Jon,
Nov 25: "update all the terms and conditions ... deep dive")."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import legal, policy                               # noqa: E402


def test_terms_version_and_new_sections():
    t = legal.terms_html()
    assert legal.TERMS_VERSION == "1.1" and "November 25, 2026" in t
    for word in ("GNU Affero General Public License", "Auto Scale",
                 "Cost data", "Generated drawings", "Back Office and "
                 "ClaimIT", "Services that are not ours", "QuantiLink",
                 "Microsoft Store", "Error reports and feedback",
                 "AS IS", "Limitation of liability"):
        assert word in t, word
    # the old wording that fought the open-source license is gone
    assert "sublicense or redistribute" not in t
    assert "reverse-engineer" not in t


def test_privacy_names_everything_that_can_leave_the_computer():
    p = legal.privacy_html()
    for word in ("Send with QuantiLink", "who sent them", "Signature "
                 "timestamps", "Time Log", "Your name on your work",
                 "License key and sign-in", "Back Office and ClaimIT",
                 "Back Office self-service", "web browser", "package "
                 "status", "automatic error reports"):
        assert word in p, word
    # every internet feature IT can turn off is on the page by name
    for cat, (setting, _hosts) in policy.NETWORK.items():
        if setting in ("DisableUpdateCheck", "DisableErrorReports"):
            continue                      # shown in the team copy's part
        key = {"aerial": "Site and address lookups", "weather": "Weather",
               "rates": "BLS", "docusign": "DocuSign", "dropbox": "Dropbox",
               "quantilink": "QuantiLink", "ai": "AI features",
               "packages": "Package status"}[cat]
        assert key in p, cat


def test_team_copy_privacy_covers_error_reports(monkeypatch):
    from app import updatecheck
    monkeypatch.setattr(updatecheck, "team_build", lambda: True)
    p = legal.privacy_html()
    assert "Error reports (team copy)" in p
    assert "Send Error Reports Automatically" in p


def test_third_party_list_has_what_ships():
    names = " ".join(n for n, _l, _u in legal.THIRD_PARTY)
    for word in ("PyMuPDF", "PySide6", "OpenCV", "NumPy", "pyHanko",
                 "openpyxl", "python-pptx", "Shapely", "lxml", "ezdxf",
                 "Modulor", "manifold3d", "websockets", "certifi"):
        assert word in names, word
    assert "offered under the GNU AGPL v3" in legal.third_party_html()


def test_publisher_and_contact_are_filled_in():
    """Jon, Nov 25: the Terms are with "Jon Dougherty, All State Services
    LLC"; support is support@quantisheet.com; the governing state stays
    generic until his attorney decides; installers keep "QuantiSheet"."""
    t = legal.terms_html()
    assert 'Jon Dougherty, All State Services LLC ("we")' in t
    assert "Questions: support@quantisheet.com." in t
    assert "principal place of business" in t
    assert "support@quantisheet.com" in legal.privacy_html()
    a = legal.about_html()
    assert "mailto:support@quantisheet.com" in a
    assert "© 2026 Jon Dougherty, All State Services LLC." in a
    assert legal._pub()["name"] == "QuantiSheet"


def test_liability_cap_has_a_floor():
    """Jon, Nov 25: keep the 12-month-fees cap, with a US $100 floor so a
    free copy's cap isn't zero, and no limit where the law forbids one."""
    t = " ".join(legal.terms_html().split())
    assert "AMOUNT YOU PAID FOR QUANTISHEET IN THE TWELVE MONTHS" in t
    assert ("IN NO EVENT SHALL TOTAL LIABILITY EXCEED THE GREATER OF FEES "
            "PAID IN THE PRIOR TWELVE MONTHS OR US $100") in t
    assert "LIABILITY THAT CANNOT BE EXCLUDED BY LAW" in t
