"""Macro files: version stamp and pre-flight (review QS-026)."""
import json

import pytest

from app import macros


class _Doc:
    page_count = 2


def test_preflight_lists_what_is_left_out():
    ops = [{"kind": "add_rect", "page": 0, "rect": [0, 0, 1, 1]},
           {"kind": "delete_annot", "page": 0},
           {"kind": "add_rect", "page": 5, "rect": [0, 0, 1, 1]},
           {"kind": "format_disk", "page": 0}, "junk"]
    pre = macros.preflight(ops, _Doc())
    assert pre["ok"] == 1
    whys = [w for _i, w in pre["skipped"]]
    assert "deleting isn't replayed" in whys
    assert "page 6 isn't in this file" in whys
    assert any("unknown step" in w for w in whys)


def test_newer_macro_file_refused(tmp_path):
    p = tmp_path / "m.json"
    macros.save_macro(str(p), [{"kind": "add_rect", "page": 0}])
    d = json.loads(p.read_text())
    assert d["format"] == macros.FORMAT and d["app"]
    d["format"] = 99
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError):
        macros.load_macro(str(p))


# ---- Venice #2 (Nov 4): only new markups, and who made the macro ---------

def test_redaction_and_text_edits_are_never_replayed():
    from app import macros
    for kind in ("add_redact", "replace_span", "delete_image", "set_scale",
                 "add_field", "set_annot", "import_annots", "delete_annot"):
        assert macros._clean({"kind": kind, "page": 0}) is None, kind
    assert macros._clean({"kind": "add_cloud", "page": 0,
                          "rect": [0, 0, 10, 10]})


def test_signed_macro_round_trip_and_tamper(tmp_path, monkeypatch):
    import json

    from app import macros, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    p = str(tmp_path / "m.json")
    ops = [{"kind": "add_cloud", "page": 0, "rect": [0, 0, 10, 10]},
           {"kind": "add_redact", "page": 0, "rect": [0, 0, 10, 10]}]
    macros.save_macro(p, ops)
    kept, info = macros.load_macro_info(p)
    assert info["signature"] == "trusted"            # my own key
    assert len(kept) == 1 and info["dropped"] == 1
    d = json.load(open(p))
    d["ops"][0]["rect"] = [0, 0, 99, 99]             # changed after signing
    json.dump(d, open(p, "w"))
    import pytest
    with pytest.raises(ValueError, match="signature"):
        macros.load_macro_info(p)
    macros.save_macro(p, ops, sign=False)
    assert macros.load_macro_info(p)[1]["signature"] == "unsigned"
