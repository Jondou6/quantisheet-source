"""Venice #1 (Nov 4): PDF JavaScript / XFA - confirm nothing runs on its
own, and that people are told what a file carries. Since Nov 17 a form's
own calculations run when a person fills a field (formcalc.py), and
nothing else does."""
import fitz

from app import activecontent


def _form(path, with_js=True):
    d = fitz.open()
    p = d.new_page()
    for name, y in (("A", 72), ("B", 120)):
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(72, y, 272, y + 30)
        w.field_value = "1"
        if name == "B" and with_js:
            w.script_calc = ('event.value = this.getField("A").value * 2;')
        p.add_widget(w)
    if with_js:
        cat = d.pdf_catalog()
        x = d.get_new_xref()
        d.update_object(x, "<< /S /JavaScript /JS (app.alert('hi');) >>")
        d.xref_set_key(cat, "OpenAction", f"{x} 0 R")
    d.save(path)
    return path


def test_a_form_script_is_not_run_on_its_own(tmp_path):
    """Opening, changing A outside the fill path and saving run nothing:
    B would become 10 if its calculation ran."""
    d = fitz.open(_form(str(tmp_path / "f.pdf")))
    pg = d[0]                       # keep the page: a widget needs it
    a = next(w for w in pg.widgets() if w.field_name == "A")
    a.field_value = "5"
    a.update()
    d.save(str(tmp_path / "g.pdf"))
    g = fitz.open(str(tmp_path / "g.pdf"))
    gp = g[0]
    b = next(w for w in gp.widgets() if w.field_name == "B")
    assert b.field_value == "1"                 # the script did not run


def test_scripts_and_xfa_are_reported(tmp_path):
    d = fitz.open(_form(str(tmp_path / "f.pdf")))
    found = activecontent.scan(d)
    assert found["javascript"] >= 1 and found["auto_actions"] >= 1
    assert "only form calculations run" in activecontent.message(found)
    plain = fitz.open(_form(str(tmp_path / "p.pdf"), with_js=False))
    assert activecontent.message(activecontent.scan(plain)) == ""
    assert activecontent.message({"xfa": True}).count("XFA") == 1
    assert activecontent.POLICY == "forms"


def test_filling_a_field_runs_the_forms_calculation(tmp_path):
    """Nov 17: filling A the way the window does runs B's calculation
    (B = A x 2); the open action (an alert) is never run."""
    from app import annotate
    d = fitz.open(_form(str(tmp_path / "f.pdf")))
    pg = d[0]
    assert annotate._set_field(pg, {"name": "A", "value": "5"})
    b = next(w for w in d[0].widgets() if w.field_name == "B")
    assert b.field_value == "10"
    d.save(str(tmp_path / "h.pdf"))
    with fitz.open(str(tmp_path / "h.pdf")) as h:
        b = next(w for w in h[0].widgets() if w.field_name == "B")
        assert b.field_value == "10"
