"""Form calculations and number formats (Nov 17), on a made-up form like
a change order request: line total = labor + material, subtotal of the
lines, overhead from a percent; number fields turn letters down; amounts
are shown formatted while the value stays a number. Help > Video
Tutorials opens the channel."""
import fitz

from app import annotate, formcalc

SUM = ("var d=this;function n(f){var v=d.getField(f).value;"
       "var x=Number(String(v).replace(/[^0-9.\\-]/g,''));"
       "return isNaN(x)?0:x;}")


def made_up(path):
    d = fitz.open()
    p = d.new_page(width=612, height=792)
    spec = [("labor_1", None), ("material_1", None),
            ("total_1", SUM + "event.value=n('labor_1')+n('material_1');"),
            ("overhead_pct", None),
            ("overhead_amt", SUM + "event.value=n('total_1')*"
                                   "n('overhead_pct')/100;"),
            ("note", None)]
    for i, (name, calc) in enumerate(spec):
        w = fitz.Widget()
        w.field_name = name
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        w.rect = fitz.Rect(72, 72 + 30 * i, 272, 92 + 30 * i)
        w.field_value = ""
        if calc:
            w.script_calc = calc
        if name in ("labor_1", "material_1", "total_1", "overhead_amt"):
            w.script_format = 'AFNumber_Format(2, 0, 0, 0, "$", true);'
            w.script_stroke = 'AFNumber_Keystroke(2, 0, 0, 0, "$", true);'
        p.add_widget(w)
    d.save(path)
    return path


def vals(doc):
    return {w.field_name: w.field_value for w in doc[0].widgets()}


def test_totals_work_themselves_out(tmp_path):
    d = fitz.open(made_up(str(tmp_path / "cor.pdf")))
    for name, v in (("labor_1", "100"), ("material_1", "50"),
                    ("overhead_pct", "10")):
        assert annotate._set_field(d[0], {"name": name, "value": v})
    got = vals(d)
    assert float(got["total_1"]) == 150
    assert float(got["overhead_amt"]) == 15
    # shown formatted as an amount, as other readers do, and still so
    # when the saved file is opened again
    def shown(doc):
        w = next(x for x in doc[0].widgets() if x.field_name == "total_1")
        kind, ref = doc.xref_get_key(w.xref, "AP/N")
        assert kind == "xref"
        return doc.xref_stream(int(ref.split()[0])).decode("latin1")
    assert "150.00" in shown(d)
    d.save(str(tmp_path / "out.pdf"))
    with fitz.open(str(tmp_path / "out.pdf")) as o:
        assert float(vals(o)["total_1"]) == 150
        assert "150.00" in shown(o)


def test_a_number_field_turns_letters_down(tmp_path):
    d = fitz.open(made_up(str(tmp_path / "cor2.pdf")))
    assert formcalc.fill(d[0], "labor_1", "lots") is False
    assert vals(d)["labor_1"] in ("", None)
    assert formcalc.fill(d[0], "note", "anything goes") is True
    assert vals(d)["note"] == "anything goes"
    assert formcalc.fill(d[0], "no_such_field", "1") is None


def test_a_form_without_scripts_fills_as_before(tmp_path):
    d = fitz.open()
    p = d.new_page()
    w = fitz.Widget()
    w.field_name, w.field_type = "plain", fitz.PDF_WIDGET_TYPE_TEXT
    w.rect = fitz.Rect(72, 72, 272, 92)
    p.add_widget(w)
    assert annotate._set_field(d[0], {"name": "plain", "value": "x"})
    assert vals(d)["plain"] == "x"
    assert not getattr(d, "_qs_form_js", False)      # never switched on


def test_video_tutorials_link():
    from app import helpcenter
    assert helpcenter.VIDEO_URL == "https://www.youtube.com/@QuantiSheet"
