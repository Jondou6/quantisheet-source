"""The outside re-review of 961eece (Nov 7): one test per fix it asked
for. Made-up data only."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402
import pytest                                                  # noqa: E402

from test_gui import qapp, win                                 # noqa: E402,F401
from test_review_fixes_nov7 import _image_pdf                  # noqa: E402


# ---- H1: a container is not "reached" unless it hands focus on ---------------

def test_reached_inside_needs_the_focus_proxy(qapp):
    from PySide6.QtWidgets import QLineEdit, QWidget
    from app import a11y
    box = QWidget()
    inner = QLineEdit(box)
    other = QLineEdit()
    # the box holds `inner` but hands focus to nothing: not reached
    assert not a11y._reached_inside(inner, [box])
    box.setFocusProxy(inner)
    assert a11y._reached_inside(inner, [box])
    assert not a11y._reached_inside(other, [box])


# ---- N1: the model list follows the IT department's AI server ---------------

def test_model_list_uses_the_policy_host(monkeypatch):
    from app import policy
    from app.ai import models, models_ui
    monkeypatch.setattr(policy, "get",
                        lambda k, *a: "http://ai-box.example.test:11434/"
                        if k == "AIHost" else None)
    assert models.it_host() == "http://ai-box.example.test:11434"
    assert models_ui._host() == "http://ai-box.example.test:11434"
    seen = []

    def fake_get(url, timeout):
        seen.append(url)
        return b'{"models": []}'
    monkeypatch.setattr(models, "_get", fake_get)
    try:
        models.list_installed(models_ui._host())
    except models.NotLocalError:                          # pragma: no cover
        pytest.fail("the policy host was refused")
    except Exception:                                     # noqa: BLE001
        pass                                 # answer shape aside: fine here
    assert seen and seen[0].startswith("http://ai-box.example.test:11434")


def test_model_list_without_policy_stays_on_this_pc(monkeypatch):
    from app import policy
    from app.ai import models
    monkeypatch.setattr(policy, "get", lambda k, *a: None)
    assert models.it_host() == ""
    with pytest.raises(models.NotLocalError):
        models.list_installed("http://ai-box.example.test:11434")


def test_bad_policy_host_is_refused(monkeypatch):
    from app import policy
    from app.ai import models
    monkeypatch.setattr(policy, "get",
                        lambda k, *a: "http://user@ai.example.test/x"
                        if k == "AIHost" else None)
    with pytest.raises(models.NotLocalError):
        models.it_host()


# ---- N2, N3: too-large answers say so -----------------------------------------

def test_site_layer_too_large_goes_on_the_legend():
    from app import aerial
    key = next(iter(aerial.SITE_LAYERS))

    def big(url, params, timeout=None):
        raise aerial.TooLarge("example")
    out = aerial.site_layer(key, 33.7, -78.9, 300, 200, 600, 400, get=big)
    assert isinstance(out, aerial.LayerProblem)
    assert "too large" in out and "smaller" in out


def test_imagery_too_large_names_the_service(monkeypatch):
    from app import aerial

    def big(*a, **k):
        raise aerial.TooLarge("example")
    monkeypatch.setattr(aerial, "_get_retry", big)
    monkeypatch.setattr(aerial, "_get", big)
    with pytest.raises(RuntimeError) as e:
        aerial.NAIPSource().fetch(33.7, -78.9, 18, 400, 300)
    assert "USGS imagery service" in str(e.value)
    assert "smaller" in str(e.value)


def test_geocode_odd_answer_is_explained(monkeypatch):
    from app import aerial
    monkeypatch.setattr(aerial, "_get",
                        lambda *a, **k: (b"<html>busy</html>", "text/html"))
    monkeypatch.setattr(aerial, "_get_retry",
                        lambda *a, **k: (b"<html>busy</html>", "text/html"))
    with pytest.raises(RuntimeError) as e:
        aerial.geocode("100 Example St, Sample Town, SC")
    assert "unexpected" in str(e.value)
    assert "Expecting value" not in str(e.value)


# ---- N4: reduce works from a temp file, which is removed ----------------------

def test_reduce_size_temp_file_is_removed(tmp_path, monkeypatch):
    import tempfile
    from app import acrobat
    made = []
    real = tempfile.mkstemp

    def tracking(*a, **k):
        fd, p = real(*a, **k)
        made.append(p)
        return fd, p
    monkeypatch.setattr(tempfile, "mkstemp", tracking)
    d = fitz.open(_image_pdf(str(tmp_path / "photo.pdf")))
    dirty = d.is_dirty
    with pytest.raises(acrobat.NotSmaller):
        acrobat.reduce_size(d, str(tmp_path / "out.pdf"), original=10)
    assert d.is_dirty == dirty
    assert made and not any(os.path.exists(p) for p in made)
    d.close()


# ---- combine lets go of the new file when a source fails ------------------------

def test_combine_closes_its_output_on_a_password(tmp_path, monkeypatch):
    from app import acrobat
    p = str(tmp_path / "locked.pdf")
    d = fitz.open()
    d.new_page()
    d.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner-x",
           user_pw="user-x")
    d.close()
    made = []
    real_open = fitz.open

    def tracking(*a, **k):
        doc = real_open(*a, **k)
        if not a:
            made.append(doc)
        return doc
    monkeypatch.setattr(fitz, "open", tracking)
    with pytest.raises(Exception):
        acrobat.combine([p], bookmarks=False)
    assert made and all(x.is_closed for x in made)


# ---- the title message is true ---------------------------------------------------

def test_title_message_only_claims_a_new_title():
    from app import accessibility
    d = fitz.open()
    d.new_page()
    d.set_metadata({"title": "Sample Plans"})
    done = accessibility.fix(d, rules=["title"])
    text = " ".join(str(x) for x in (done if isinstance(done, list)
                                     else [done]))
    assert "Title set to" not in text
    assert "Sample Plans" in text
    d2 = fitz.open()
    d2.new_page()
    done = accessibility.fix(d2, rules=["title"], title="Example")
    text = " ".join(str(x) for x in (done if isinstance(done, list)
                                     else [done]))
    assert 'Title set to "Example"' in text


# ---- N5: a cheap edit counter keys the ADA cache ---------------------------------

def test_edit_count_moves_on_each_change():
    from app import ada_ui, annotate
    d = fitz.open()
    d.new_page()
    k1 = ada_ui._revision(d)
    assert ada_ui._revision(d) == k1                   # nothing changed
    annotate.bump_edits(d)
    assert ada_ui._revision(d) != k1
    assert annotate.edit_count(d) == 1


# ---- H4: ADA data goes through the op log (undo, live collaboration) -------------

def test_set_jobdata_op_writes_only_listed_files():
    from app import ada_check, annotate
    d = fitz.open()
    d.new_page()
    good = {"id": "op1", "kind": "set_jobdata", "page": 0,
            "payload": {"file": ada_check.FILE,
                        "data": json.dumps({"stories": 4})}}
    assert annotate.apply_op(d, good, fresh=True)
    assert ada_check.read(d)["stories"] == 4
    again = dict(good, id="op2")
    assert not annotate.apply_op(d, again, fresh=True)   # same: no change
    for bad in ({"file": "other.json", "data": "{}"},
                {"file": ada_check.FILE, "data": "not json"},
                {"file": ada_check.FILE,
                 "data": json.dumps({"x": "y" * 1_100_000})}):
        op = {"id": "b", "kind": "set_jobdata", "page": 0, "payload": bad}
        assert not annotate.apply_op(d, op, fresh=True)
    assert "other.json" not in d.embfile_names()
    assert "set_jobdata" in annotate.FULL_UNDO_KINDS


def test_ada_checker_uses_the_apply_hook(qapp):
    from app import ada_ui
    d = fitz.open()
    d.new_page()
    tab = ada_ui.CheckerTab(d)
    sent = []
    tab.apply = lambda proj: sent.append(proj) or True
    tab.blocked = lambda what: pytest.fail("the op log decides, not this")
    tab.ed["stories"].setText("5")
    tab.run()
    assert sent and str(sent[0].get("stories")) == "5"


def test_ada_write_through_the_viewer_is_one_undo_step(win):
    from app import ada_check
    v = win._view
    assert win._ada_apply(v, {"stories": 7})
    assert ada_check.read(win._view.doc)["stories"] == 7
    win.undo()
    assert str(ada_check.read(win._view.doc).get("stories")) != "7"
