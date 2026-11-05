"""Venice #1 (Nov 4): PDF JavaScript / XFA - confirm nothing runs, and
that people are told what a file carries."""
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


def test_a_form_script_is_not_run(tmp_path):
    """Change A; if MuPDF ran B's calculation script, B would become 10."""
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
    assert "never runs them" in activecontent.message(found)
    plain = fitz.open(_form(str(tmp_path / "p.pdf"), with_js=False))
    assert activecontent.message(activecontent.scan(plain)) == ""
    assert activecontent.message({"xfa": True}).count("XFA") == 1
    assert activecontent.POLICY == "off"
