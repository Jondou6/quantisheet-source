"""A damaged quantisheet_scale.json (its file entry isn't a stream) must not
block Set Scale: the scales read as empty, the next Set Scale replaces the
attachment, and the user is told once."""
import json
import re

import fitz

from app import annotate, embfiles, pdfmeasure


def _break_scale_file(doc):
    """Point the scale file's /EF /F at a non-stream object (an array), the
    way a damaged PDF does: reading it gives 'object is not a stream' and
    update_stream gives 'object is no PDF dict'."""
    loc = embfiles._names_array(doc)
    assert loc is not None
    _, text = doc.xref_get_key(*loc)
    entries = embfiles._entries(text)
    value = dict(entries)[annotate.SCALE_FILE]
    x = embfiles._stream_xref(doc, value)
    assert x
    bad = doc.get_new_xref()
    doc.update_object(bad, "[1 2 3]")
    m = re.match(r"(\d+)\s+\d+\s+R", value)
    if m:                                    # filespec is its own object
        doc.xref_set_key(int(m.group(1)), "EF/F", f"{bad} 0 R")
    else:                                    # filespec inline in /Names
        doc.xref_set_key(loc[0], loc[1],
                         text.replace(f"/F {x} 0 R", f"/F {bad} 0 R"))


def _doc_with_damaged_scales():
    d = fitz.open()
    d.new_page(width=612, height=792)
    embfiles.put(d, "quantisheet_other.json", b'{"keep": 1}')
    embfiles.put(d, annotate.SCALE_FILE,
                 json.dumps({"0": {"ppu": 5.0, "unit": "ft"}}).encode())
    _break_scale_file(d)
    return d


def test_damaged_scale_file_is_reset_on_set_scale():
    d = _doc_with_damaged_scales()
    try:
        d.embfile_get(annotate.SCALE_FILE)
        readable = True
    except Exception:
        readable = False
    assert not readable                      # really damaged
    assert annotate.read_scales(d) == {}     # treated as no saved scales
    assert annotate.take_scale_notice(d) is None

    assert annotate._set_scale(d, 0, {"ppu": 10.0, "unit": "ft"})
    assert annotate.read_scales(d) == {0: {"ppu": 10.0, "unit": "ft"}}
    sc = annotate.scale_at(d, 0)
    assert 200 / sc["ppu"] == 20             # 200 pt at 10 pt/ft = 20 ft
    assert annotate.take_scale_notice(d) == annotate.SCALE_RESET_NOTICE
    assert annotate.take_scale_notice(d) is None     # once

    # the other job file is untouched; the next Set Scale is quiet
    assert d.embfile_get("quantisheet_other.json") == b'{"keep": 1}'
    assert annotate._set_scale(d, 0, {"ppu": 12.0, "unit": "ft"})
    assert annotate.take_scale_notice(d) is None
    d2 = fitz.open("pdf", d.tobytes(garbage=3))
    assert annotate.read_scales(d2) == {0: {"ppu": 12.0, "unit": "ft"}}


class _FakeDoc:
    """Just enough of a Document for _set_scale when reading the scale
    file fails the way PyMuPDF does on a damaged PDF."""
    page_count = 1

    def __init__(self):
        self.files = {annotate.SCALE_FILE: None}      # None = damaged

    def embfile_names(self):
        return list(self.files)

    def embfile_get(self, name):
        if self.files[name] is None:
            raise RuntimeError("object is not a stream")
        return self.files[name]

    def embfile_add(self, name, data, filename=None, desc=None):
        assert name not in self.files
        self.files[name] = data


def test_damaged_scale_read_simulated():
    """Same, with the failure simulated (no real damaged PDF needed)."""
    d = _FakeDoc()
    saved = (embfiles.delete, embfiles.put, pdfmeasure.sync_page)
    calls = []

    def fake_delete(doc, name):
        calls.append(("delete", name))
        doc.files.pop(name, None)
        return True

    def fake_put(doc, name, data, desc=""):
        calls.append(("put", name))
        doc.files[name] = data
    embfiles.delete, embfiles.put = fake_delete, fake_put
    pdfmeasure.sync_page = lambda *a, **k: None
    try:
        assert annotate.read_scales(d) == {}
        assert annotate._set_scale(d, 0, {"ppu": 10.0, "unit": "ft"})
        assert calls[0] == ("delete", annotate.SCALE_FILE)
        assert json.loads(d.files[annotate.SCALE_FILE]) == \
            {"0": {"ppu": 10.0, "unit": "ft"}}
        assert annotate.take_scale_notice(d) == annotate.SCALE_RESET_NOTICE
        assert annotate.take_scale_notice(d) is None
        assert annotate._set_scale(d, 0, {"ppu": 8.0, "unit": "ft"})
        assert annotate.take_scale_notice(d) is None
        assert annotate.read_scales(d)[0]["ppu"] == 8.0
    finally:
        embfiles.delete, embfiles.put, pdfmeasure.sync_page = saved
