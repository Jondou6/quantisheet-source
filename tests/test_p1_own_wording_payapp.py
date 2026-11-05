"""P1 'own-wording pay application forms (no AIA text)': the printed
application uses QuantiSheet's own titles and wording - no AIA name,
document numbers or certificate text (made-up job)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                  # noqa: E402

from app import money                                        # noqa: E402


def test_application_pdf_has_no_aia_wording(tmp_path):
    d = fitz.open()
    d.new_page()
    money.set_info(d, project="Example Job", owner="Example Owner",
                   contractor="Example GC")
    money.set_sov(d, [{"item": "1", "desc": "Example work",
                       "scheduled": 100000}])
    no = money.new_pay_app(d, "2026-11-30")
    no = no if isinstance(no, int) else 1
    money.set_progress(d, no, "1", work=25000)
    out = str(tmp_path / "app.pdf")
    money.pay_app_pdf(d, no, out)
    text = " ".join(p.get_text() for p in fitz.open(out)).upper()
    for bad in ("AIA", "G702", "G703", "CERTIFICATE FOR PAYMENT",
                "ARCHITECT'S CERTIFICATE"):
        assert bad not in text, bad
    assert "APPLICATION FOR PAYMENT" in text


def test_menus_say_pay_applications_without_form_numbers():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in ("main_window.py", "simple_menu.py", "billing_ui.py"):
        src = open(os.path.join(root, "app", f), encoding="utf-8").read()
        assert "(G702/G703)" not in src and "G702/G703 PDF" not in src
