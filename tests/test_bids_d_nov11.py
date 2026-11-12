"""Nov 11, bidding phase D: scope items (Included / Excluded) on the bid
form, inclusions / exclusions / clarifications as lists, project-wide
lines, and the answers going into the Scope Sheet with nothing retyped.
Made-up companies and numbers only."""
import datetime as dt
import os
import re

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                         # noqa: E402
from app.collab import hub as hubmod                             # noqa: E402
from app.pm import actions, bidforms, scope_sheet as ss         # noqa: E402
from app.pm.store import ProjectStore                            # noqa: E402
from test_pm import env, qapp_pm, _team                         # noqa: E402,F401

L = bidforms.L
FORM = [L(1, "Base bid - plumbing complete"),
        L(2, "Underground sanitary", "Unit price", 100, "LF"),
        L(3, "Permits and fees", bidforms.SCOPE),
        L(4, "Sales tax", bidforms.SCOPE),
        L(5, "Hoisting", bidforms.SCOPE),
        L(6, "Bid bond included?", "Yes / No"),
        L(7, "Lead time for water heaters", "Text")]


# ---- the form ----------------------------------------------------------------

def test_scope_item_is_a_line_type_and_old_forms_open_unchanged():
    old = [{"item": "1", "description": "Base bid", "type": "Lump sum",
            "qty": None, "unit": "", "note": ""},
           {"item": "2", "description": "Bid bond included?",
            "type": "Yes / No", "qty": None, "unit": "", "note": ""}]
    assert bidforms.clean(old) == old            # nothing added, nothing lost
    got = bidforms.clean([{"description": "Permits", "type": "scope item"},
                          {"description": "Tax", "type": "Included?"},
                          {"description": "x", "type": "nonsense"}])
    assert [g["type"] for g in got] == ["Scope item", "Scope item",
                                        "Lump sum"]
    assert "Scope checklist (included / excluded)" in bidforms.library()
    # a scope item is not money
    t = bidforms.totals(bidforms.clean(FORM), {"0": "1000", "1": "10",
                                               "2": "Included"})
    assert float(t["base"]) == 2000.0 and t["missing"] == []


def test_scope_answers_and_lists():
    assert [bidforms.scope_answer(v) for v in (
        "Included", "yes", "EXCLUDED", "No", "NIC", "", "maybe", "125.00"
    )] == ["Y", "Y", "N", "N", "N", "", "", ""]
    assert bidforms.split_notes(
        "- Permits by others\n2) Winter protection; temporary heat\n\n"
        "none\n* Permits by others") == [
        "Permits by others", "Winter protection", "temporary heat"]
    rec = {"form": FORM}
    b = {"form_values": {"0": "1,000", "1": "12.50", "2": "Included",
                         "3": "Excluded", "5": "Yes"},
         "exclusions": "Roof curbs\nTemporary heat",
         "clarifications": "Price good 30 days"}
    a = bidforms.answers(rec, b)
    assert a["scope"] == [("Permits and fees", "Y"), ("Sales tax", "N"),
                          ("Hoisting", "")]
    assert [(d, float(v)) for d, v in a["prices"]] == [
        ("Base bid - plumbing complete", 1000.0),
        ("Underground sanitary", 1250.0)]
    assert a["exclusions"] == ["Roof curbs", "Temporary heat"] and \
        a["clarifications"] == ["Price good 30 days"] and \
        a["inclusions"] == []


def test_project_wide_lines_join_at_the_end(tmp_path):
    s = ProjectStore(str(tmp_path / "p"))
    assert bidforms.common(s) == []
    com = bidforms.set_common(s, bidforms.questions(FORM))
    assert [c["description"] for c in com] == [
        "Permits and fees", "Sales tax", "Hoisting", "Bid bond included?",
        "Lead time for water heaters"]
    assert all(c["common"] for c in com)
    pkg = [L(1, "Base bid - electrical complete"),
           L(2, "Bid bond included?", "Yes / No")]
    lines, added = bidforms.with_common(pkg, com)
    assert added == 4 and len(lines) == 6
    # the package's own lines keep their place (answers stay on them)
    assert [x["description"] for x in lines[:2]] == [
        "Base bid - electrical complete", "Bid bond included?"]
    assert lines[1]["common"] is True and "common" not in lines[0]
    assert [x["item"] for x in lines] == ["1", "2", "3", "4", "5", "6"]
    again, added = bidforms.with_common(lines, com)
    assert added == 0 and again == lines
    assert bidforms.clean(lines) == lines        # the mark survives a save


def test_bid_form_action_adds_the_project_wide_lines(tmp_path):
    s = ProjectStore(str(tmp_path / "p"))
    said, picks = [], []
    ctx = actions.Ctx(s, ask=lambda title, opts: picks.pop(0)(opts),
                      notify=said.append)
    a = s.save_record("bidpkg", {"title": "Plumbing", "form": FORM})
    picks.append(lambda o: next(x for x in o if x.startswith(
        "Project-wide lines: use")))
    a = actions.run(ctx, "bidpkg", a, "Bid Form…")
    assert len(bidforms.common(s)) == 5 and "every package" in said[-1]
    b = s.save_record("bidpkg", {"title": "Electrical"})
    picks.append(lambda o: "Template: Electrical")
    b = actions.run(ctx, "bidpkg", b, "Bid Form…")
    assert len(b["form"]) == 7 + 5
    assert [x["description"] for x in b["form"][-5:]] == [
        c["description"] for c in bidforms.common(s)]
    assert "5 of them the project-wide lines" in said[-1]
    picks.append(lambda o: next(x for x in o if x.startswith(
        "Project-wide lines (5)")))
    b = actions.run(ctx, "bidpkg", b, "Bid Form…")
    assert len(b["form"]) == 12 and "already has every" in said[-1]


def test_printed_bid_form_has_the_new_sections(tmp_path):
    s = ProjectStore(str(tmp_path / "Job"))
    said, opened = [], []
    ctx = actions.Ctx(s, notify=said.append, open_file=opened.append)
    r = s.save_record("bidpkg", {"title": "Plumbing", "form": FORM,
                                 "due": "2026-12-01"})
    actions.run(ctx, "bidpkg", r, "Print Bid Form…")
    assert opened and opened[0].endswith(".pdf") and "Nothing was sent" \
        in said[-1]
    text = "".join(p.get_text() for p in fitz.open(opened[0]))
    for w in ("Bid Form", "Prices", "Underground sanitary",
              "Scope - mark each Included or Excluded", "Permits and fees",
              "Questions", "Bid bond included?", "Inclusions (one per line)",
              "Exclusions (one per line)", "Clarifications (one per line)",
              "2026-12-01"):
        assert w in text, w
    assert os.path.dirname(opened[0]).endswith("Bid Forms")


# ---- the online bid page and the hub -----------------------------------------

def test_bid_page_has_scope_choice_and_three_lists():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "app", "collab", "web", "bid.html"),
                encoding="utf-8").read()
    assert 'ln.type === "Scope item"' in html
    assert '["Included","Excluded"]' in html
    for el in ('id="incl"', 'id="excl"', 'id="clar"'):
        assert html.count(el) == 1
    assert 'clarifications: $("#clar").value' in html
    # the socket still comes only from the page's own host
    assert "location.host" in html and "searchParams.get(\"ws\")" not in html


def _invite(env, sealed=False):
    tmp, H = env
    s = ProjectStore(str(tmp / "p"))
    _team(s)
    s.connect("ws://hub", "Tower Job", "pw123456")
    said = []
    pkg = s.save_record("bidpkg", {
        "title": "Plumbing", "trades": "22 Plumbing", "due": "2026-12-20",
        "due_time": "2:00 PM", "form": FORM,
        **({"sealed": "Yes"} if sealed else {}),
        "bidders": [{"company": "Example Mechanical",
                     "email": "est@example-mech.example"},
                    {"company": "Sample Piping",
                     "email": "bid@sample-piping.example"}]})
    ctx = actions.Ctx(s, notify=said.append)
    pkg = actions.run(ctx, "bidpkg", pkg, "Send Invitations")
    s.sync()
    return s, H, pkg, [b["token"] for b in pkg["bidders"]], said


def test_hub_keeps_scope_answers_and_clarifications(env):
    s, H, pkg, toks, said = _invite(env)
    assert not any("older than this bid form" in x for x in said)
    info = H.call("bid.open", {"token": toks[0]}, {}, False)
    assert info["clarifications"] == "" and \
        info["form"][2]["type"] == "Scope item"
    H.call("bid.respond", {
        "token": toks[0], "intent": "Bid Received",
        "form": {"0": "50000", "1": "40", "2": "Included", "3": "Excluded",
                 "5": "Yes"},
        "inclusions": "Start-up", "exclusions": "Roof curbs\nTemporary heat",
        "clarifications": "Price good 30 days"}, {}, False)
    info = H.call("bid.open", {"token": toks[0]}, {}, False)
    assert info["clarifications"] == "Price good 30 days" and \
        info["values"]["2"] == "Included"
    s.sync()
    row = s.get("bidpkg", pkg["_id"])["bidders"][0]
    assert row["clarifications"] == "Price good 30 days"
    assert float(row["amount"]) == 54000.0       # scope items add no money
    assert hubmod.BID_FEATURES == ("scope_items", "clarifications")


def test_an_older_hub_is_called_out(env, monkeypatch):
    real = hubmod.Hub.op_bid_invite

    def old(self, a, ctx):
        out = real(self, a, ctx)
        out.pop("features")
        return out
    monkeypatch.setattr(hubmod.Hub, "op_bid_invite", old)
    s, H, pkg, toks, said = _invite(env)
    assert any("Your hub server is older than this bid form" in x
               for x in said)


def test_sealed_bids_seal_the_clarifications_too(env):
    assert "clarifications" in hubmod.Hub.SEALED_KEYS


# ---- into the Scope Sheet ----------------------------------------------------

def _answered(env):
    s, H, pkg, toks, said = _invite(env)
    H.call("bid.respond", {
        "token": toks[0], "intent": "Bid Received",
        "form": {"0": "50000", "1": "40", "2": "Included", "3": "Excluded",
                 "5": "Yes"},
        "exclusions": "Roof curbs\nTemporary heat",
        "clarifications": "Price good 30 days"}, {}, False)
    H.call("bid.respond", {
        "token": toks[1], "intent": "Bid Received",
        "form": {"0": "47,500", "1": "38", "2": "Excluded", "3": "Included",
                 "4": "Included"},
        "exclusions": "roof curbs"}, {}, False)
    s.sync()
    return s


def test_answers_fill_the_scope_sheet_with_nothing_retyped(env):
    s = _answered(env)
    sh = ss.new_sheet("22 00 00", "Plumbing", bidders=0)
    sh["lines"] = []
    ss.add_line(sh, "Underground sanitary")
    ss.add_line(sh, "Permits & fees")            # close, not the same words
    assert ss.bidders_from_package(s, sh) == 2
    got = ss.fill_from_package(s, sh)
    a, b = sh["bidders"]
    assert (a["company"], b["company"]) == ("Example Mechanical",
                                            "Sample Piping")
    line = {ln["desc"]: ln for ln in sh["lines"]}
    # scope items with no line yet became lines; the close one was matched
    assert set(line) == {"Underground sanitary", "Permits & fees",
                         "Sales tax", "Hoisting"}
    assert got["lines"] == 2
    cell = lambda d, x: ss.bid_cell(line[d], x["id"])           # noqa: E731
    assert cell("Permits & fees", a)["flag"] == "Y" and \
        cell("Permits & fees", b)["flag"] == "N"
    assert cell("Sales tax", a)["flag"] == "N" and \
        cell("Sales tax", b)["flag"] == "Y"
    assert cell("Hoisting", a)["flag"] == "" and \
        cell("Hoisting", b)["flag"] == "Y"       # no answer: left blank
    assert cell("Underground sanitary", a)["amount"] == 400000 and \
        cell("Underground sanitary", b)["amount"] == 380000
    ca = [(c["kind"], c["text"], c["status"])
          for c in ss.clarifications(sh, a)]
    assert ca == [("Exclusion", "Roof curbs", "pending"),
                  ("Exclusion", "Temporary heat", "pending"),
                  ("Clarification", "Price good 30 days", "pending")]
    assert [c["text"] for c in ss.clarifications(sh, b)] == ["roof curbs"]
    assert got["flags"] == 5 and got["amounts"] == 2 and got["rows"] == 4 \
        and got["bidders"] == 2
    # the exclusions table sees them at once
    from app import exclusions as ex
    rows = ex.matrix(ss.exclusion_bids(sh))
    assert next(r for r in rows if "heat" in r["label"].lower())["only"] \
        == "Example Mechanical"


def test_filling_again_changes_nothing_and_typed_cells_are_kept(env):
    s = _answered(env)
    sh = ss.new_sheet("22 00 00", "Plumbing", bidders=0)
    sh["lines"] = []
    ln = ss.add_line(sh, "Sales tax")
    ss.bidders_from_package(s, sh)
    a = sh["bidders"][0]
    ss.set_bid(sh, ln["id"], a["id"], flag="Y")    # typed by the estimator
    ss.fill_from_package(s, sh)
    assert ss.bid_cell(ln, a["id"])["flag"] == "Y"  # their N didn't win
    before = ss.to_dict(sh)
    again = ss.fill_from_package(s, sh)
    assert again["flags"] == again["amounts"] == again["rows"] == \
        again["lines"] == 0
    assert ss.to_dict(sh) == before


def test_scope_sheet_window_says_what_came_in(env, qapp_pm):
    from app.pm import scope_sheet_ui as ui
    s = _answered(env)
    ed = ui.ScopeSheetEditor(s)
    sh = ss.new_sheet("22 00 00", "Plumbing", bidders=0)
    ed.set_sheet(sh)
    n = ed.from_package()
    assert n > 2
    msg = ed.msg.text()
    assert "Added 2 bidder(s)" in msg and "included / excluded answer(s)" \
        in msg and "Pending until you accept" in msg
    assert ed.from_package() == 0
