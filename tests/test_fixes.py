"""Regression tests for the bugs fixed after the initial (Venice) version."""
import json
import os

import fitz
import pytest

from app import annotate, autocount, history, macros, page_ops, rules, versions
from app.collab import merge
from app.collab.oplog import OpLog, Op


def _doc(text="The wall shall be rated. fire rating 2 hr.", pages=1):
    d = fitz.open()
    for _ in range(pages):
        d.new_page(width=612, height=792).insert_text((40, 60), text)
    return d


class View:
    def __init__(self, doc):
        self.doc = doc

    def _render(self):
        pass


# ---- collaboration ---------------------------------------------------------

def test_reapplying_log_does_not_duplicate():
    d = _doc()
    a = OpLog("a")
    a.add_local("add_highlight", 0, rect=[10, 10, 40, 20])
    a.add_local("add_rect", 0, rect=[100, 100, 140, 130])
    for _ in range(3):                    # every sync used to redraw all ops
        merge.apply_merged(View(d), a.to_list())
    assert len(list(d[0].annots())) == 2


def test_remote_redaction_really_removes_text():
    d = fitz.open()
    d.new_page().insert_text((50, 50), "SECRET NUMBER 1234")
    op = OpLog("x").add_local("add_redact", 0, rect=[0, 0, 600, 100])
    merge.apply_merged(View(d), [op.to_dict()])
    assert "SECRET" not in d[0].get_text()


def test_delete_annot_and_tombstone():
    d = _doc()
    log = OpLog("a")
    hl = log.add_local("add_highlight", 0, rect=[10, 10, 40, 20])
    log.add_local("delete_annot", 0, target=hl.id)
    merge.apply_merged(View(d), log.to_list())
    assert d[0].first_annot is None


def test_marks_are_real_annotations():
    d = _doc()
    for kind in ("add_rect", "add_ellipse", "add_cloud"):
        annotate.apply_op(d, annotate.new_op(kind, 0, rect=[50, 50, 90, 90]))
    annotate.apply_op(d, annotate.new_op("add_text", 0, pt=[50, 200], text="hi"))
    annotate.apply_op(d, annotate.new_op("add_count", 0, pt=[50, 300], n=3))
    # removable, not burned in (a count's dot is a label part of its marker)
    assert len([a for a in d[0].annots()
                if not annotate.is_label(d, a)]) == 5


def test_order_is_lamport_not_wallclock():
    a, b = OpLog("a"), OpLog("b")
    a.add_local("add_highlight", 0, rect=[1, 1, 2, 2])
    b.merge(a.to_list())
    later = b.add_local("add_rect", 0, rect=[3, 3, 4, 4])
    a.merge(b.to_list())
    assert [o["id"] for o in a.to_list()] == [o["id"] for o in b.to_list()]
    assert a.to_list()[-1]["id"] == later.id


def test_tampered_op_rejected():
    d = OpLog("a").add_local("add_highlight", 0, rect=[1, 1, 2, 2]).to_dict()
    d["payload"]["rect"] = [0, 0, 600, 800]
    with pytest.raises(ValueError):
        Op.from_dict(d)
    assert OpLog("b").add_remote(d) is None


def test_client_ids_are_unique():
    assert OpLog().client_id != OpLog().client_id


# ---- rules ------------------------------------------------------------------

def test_rules_find_regex_matches():
    d = _doc()
    marks = rules.find_marks(d)
    kinds = sorted(k for _, k, _ in marks)
    assert kinds == ["add_highlight", "add_underline"]   # shall, fire rating


def test_rules_do_not_stack_duplicates():
    d = _doc()
    assert rules.apply_rules(d) == 2
    assert rules.apply_rules(d) == 0


def test_nl_rule_whole_words():
    r = rules.parse_nl_rule("underline every fire rating in red")
    assert r["mark"] == "underline" and r["color"] == [1, 0, 0]
    d = _doc()
    assert rules.apply_rules(d, [r]) == 1
    r2 = rules.parse_nl_rule("highlight all required items")
    assert r2["color"] == [1, 1, 0]          # "required" is not "red"


# ---- page ops ---------------------------------------------------------------

def test_watermark_is_visible():
    d = fitz.open()
    d.new_page()
    before = d[0].get_pixmap().samples
    page_ops.add_watermark(d, "DRAFT")
    assert d[0].get_pixmap().samples != before


def test_bates_on_rotated_page():
    d = _doc(pages=2)
    d[1].set_rotation(90)
    assert page_ops.bates_number(d, "EX", 1) == 2
    assert "EX000002" in d[1].get_text()


# ---- history / versions -------------------------------------------------------

def test_history_tracks_in_memory_edits():
    d = _doc()
    h = history.History(lambda: d.tobytes())
    annotate.apply_op(d, annotate.new_op("add_rect", 0, rect=[1, 1, 50, 50]))
    h.snapshot()
    before = fitz.open(stream=h.undo(), filetype="pdf")    # no doc: bytes
    assert before[0].first_annot is None
    after = fitz.open(stream=h.redo(), filetype="pdf")
    assert after[0].first_annot is not None


def test_versions_branch_name_is_sanitised(tmp_path):
    src = tmp_path / "a.pdf"
    _doc().save(src)
    rid = versions.save_revision(str(src), src.read_bytes(),
                                 branch="../../evil name")
    files = os.listdir(str(src) + ".versions")
    assert all("/" not in f and ".." not in f for f in files)
    assert versions.load_revision(str(src), rid) == src.read_bytes()


def test_compare_reports_changes(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    _doc("alpha line").save(a)
    _doc("beta line").save(b)
    out = tmp_path / "diff.pdf"
    versions.compare(str(a), str(b), str(out))
    text = fitz.open(out)[0].get_text()
    assert "- alpha line" in text and "+ beta line" in text


# ---- autocount / macros -------------------------------------------------------

def test_autocount_numbers_each_hit():
    d = _doc("EXIT here and EXIT there", pages=2)
    hits = autocount.find_by_label(d, "EXIT", use_ocr=False)
    assert len(hits) == 4
    assert autocount.apply_counts(d, hits) == 4
    assert len([a for a in d[0].annots()
                if not annotate.is_label(d, a)]) == 2


def test_macro_replay_keeps_kind_and_colour():
    d = _doc()
    ops = [{"kind": "add_highlight", "page": 0, "rect": [10, 10, 50, 20],
            "color": [0, 1, 0]},
           {"kind": "bogus", "page": 0}]
    assert macros.replay(View(d), ops) == 1
    page = d[0]                      # keep the page alive while using annot
    a = page.first_annot
    assert a.type[0] == fitz.PDF_ANNOT_HIGHLIGHT
    assert tuple(round(c, 2) for c in a.colors["stroke"]) == (0, 1, 0)


# ---- AI markup (no model needed) -----------------------------------------------

def test_redline_and_spec_marks():
    from app.ai import review
    d = _doc(pages=2)
    m = review.redline_marks(d, [{"old": "shall", "new": "must", "reason": "x"}])
    assert len(m) == 2 and m[0][1] == "add_strike"
    assert "Replace with: must" in m[0][2]["note"]
    s = review.spec_marks(d, [{"finding": "no rating", "page": 2}])
    assert s[0][0] == 1 and s[0][1] == "add_note"
    assert review._items('{"edits": [{"old": "a"}]}', "edits") == [{"old": "a"}]
    assert review._items("junk [ {\"old\": \"b\"} ] junk", "edits") == [{"old": "b"}]


# ---- signing ----------------------------------------------------------------

def test_sign_twice_same_key_and_audit_keeps_signature(tmp_path, monkeypatch):
    from app.sign import signer, verify, embed
    from app.sign.audit import AuditLog
    monkeypatch.setattr(signer, "DEFAULT_DIR", str(tmp_path / "keys"))
    src = tmp_path / "doc.pdf"
    _doc().save(src)
    one, two = tmp_path / "one.pdf", tmp_path / "two.pdf"
    signer.sign_pdf(str(src), str(one))
    key = (tmp_path / "keys" / "signing_key.pem").read_bytes()
    signer.sign_pdf(str(one), str(two))              # second signature
    assert (tmp_path / "keys" / "signing_key.pem").read_bytes() == key
    res = [r for r in verify.verify_document(str(two)) if "field" in r]
    assert len(res) == 2 and all(r["valid"] for r in res), res

    log = AuditLog()
    log.add("approved", "me", "ok")
    audited = tmp_path / "audited.pdf"
    embed.embed_audit(str(two), str(audited), log)
    res = verify.verify_document(str(audited))
    sigs = [r for r in res if "field" in r]
    assert all(r["valid"] for r in sigs), res        # still intact
    assert any(r.get("audit_chain_valid") for r in res)
    log.add("second", "me", "again")
    embed.embed_audit(str(audited), str(audited), log)
    assert len(embed.read_audit(str(audited)).entries) == 2


def test_audit_detects_tampering():
    from app.sign.audit import AuditLog
    log = AuditLog()
    log.add("a", "me", "one")
    log.add("b", "me", "two")
    data = json.loads(log.to_json())
    data[0]["detail"] = "changed"
    assert not AuditLog.from_json(json.dumps(data)).verify()
    assert AuditLog.from_json(log.to_json()).verify()
