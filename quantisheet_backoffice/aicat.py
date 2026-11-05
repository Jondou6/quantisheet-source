"""AI categorization and reconciliation suggestions (addendum P3-05).

Three layers, cheapest first, for a bank or card line that has no match:
1. rule / match  - banking.suggest() (bank rules, matching postings, the
                   user's own category). No model.
2. similar       - the most alike payee among lines this company already
                   accepted or the user categorized / corrected (difflib on
                   a cleaned payee). No model. Corrections feed this layer.
3. model         - the local model (localai) is given the date, amount,
                   cleaned payee / description, this company's chart and
                   open jobs, and proposes account, job and cost code with
                   a confidence and a reason. Anything not in the lists is
                   thrown away.

Every layer only SUGGESTS: the line gets status 'Suggested' and nothing is
posted until a person clicks Accept (banking.accept). AI suggestions are
left out of 'Accept all suggested'; accept_bulk() accepts the AI
suggestions at or above the Settings > AI threshold, on the user's click
only. Every accept can be undone (undo_accept). Each suggestion and each acceptance,
correction, rejection or undo is in ai_log and the audit trail. With no
model installed, layers 1 and 2 still work and the line simply stays New.
"""
from __future__ import annotations

import difflib
import json
import re
from collections import Counter
from decimal import Decimal

from . import aiguard, aitrail, banking, cents, clock, ledger, localai

SIMILAR_MIN = Decimal("0.85")
NOISE = re.compile(r"\b(POS|DEBIT|CREDIT|CARD|PURCHASE|ACH|CHECKCARD|"
                   r"PAYMENT|ONLINE|WWW|COM|INC|LLC|CO|CORP)\b")
CHOOSABLE = ("cogs", "expense", "other expense", "income", "other income",
             "asset", "liability", "equity")
NOT_CHOOSABLE = ("system", "tax payable")
SYSTEM = ("You help a construction company's bookkeeper. Pick the ONE "
          "account from the list that best fits a bank or card line, and "
          "the job and cost code if the line is clearly for one job. "
          "Answer only JSON: {\"account\": \"<number from the list>\", "
          "\"job\": \"<job number or empty>\", \"cost_code\": \"<code or "
          "empty>\", \"confidence\": <0 to 1>, \"reason\": \"<few "
          "words>\"}. If none fits, answer {\"account\": \"\", "
          "\"confidence\": 0}.")


class AICatError(RuntimeError):
    pass


def clean_payee(text: str) -> str:
    t = re.sub(r"[^A-Z ]", " ", (text or "").upper())
    t = NOISE.sub(" ", t)
    return " ".join(w for w in t.split() if len(w) > 1)


def _history(office, bank_account_id=None) -> list[dict]:
    """Lines with a category a person stands behind: accepted lines (not
    matches) and lines the user categorized or corrected, even before
    they are accepted."""
    out = []
    for r in office.db.rows(
            "SELECT * FROM statement_lines WHERE deleted = 0 AND "
            "(status = 'Accepted' OR (user_categorized = 1 AND "
            "status != 'Excluded')) ORDER BY date DESC, id DESC"):
        s = json.loads(r["suggestion"]) if r["suggestion"] else {}
        acct = r["account_id"] if r["user_categorized"] else \
            s.get("account_id")
        if not acct or s.get("kind") in ("match", "choose"):
            continue
        out.append({"id": r["id"], "payee": r["payee"], "date": r["date"],
                    "clean": clean_payee(r["payee"]), "account_id": acct,
                    "job_id": r["job_id"] if r["user_categorized"] else
                    s.get("job_id"),
                    "cost_code": (r["cost_code"] if r["user_categorized"]
                                  else s.get("cost_code")) or "",
                    "positive": r["amount"] > 0})
    return out


def similar(office, ln) -> dict | None:
    target = clean_payee(ln["payee"])
    if not target:
        return None
    best, score = [], Decimal(0)
    for h in _history(office):
        if h["id"] == ln["id"] or h["positive"] != (ln["amount"] > 0):
            continue
        r = Decimal(str(round(difflib.SequenceMatcher(
            None, target, h["clean"]).ratio(), 2)))
        if r > score:
            best, score = [h], r
        elif r == score and r > 0:
            best.append(h)
    if not best or score < SIMILAR_MIN:
        return None
    votes = Counter(h["account_id"] for h in best)
    acct, n = votes.most_common(1)[0]
    conf = (score * Decimal(n) / Decimal(len(best))).quantize(Decimal("0.01"))
    h = next(x for x in best if x["account_id"] == acct)
    a = ledger.account(office, acct)
    return {"account_id": acct, "job_id": h["job_id"],
            "cost_code": h["cost_code"], "confidence": str(conf),
            "reason": f"like '{h['payee']}' on {h['date']} "
                      f"({a['number']} {a['name']})", "basis_line": h["id"]}


def choices(office) -> list[dict]:
    return [a for a in ledger.accounts(office)
            if a["type"] in CHOOSABLE and
            (a.get("subtype") or "") not in ledger.CONTROL_SUBTYPES and
            (a.get("subtype") or "") not in NOT_CHOOSABLE and
            not a.get("system")]


def _safe_clean(text, vals) -> str:
    """Scrub personal data from the RAW text first (so an e-mail or a
    number is caught whole), then clean it, keeping the [person] / [id]
    placeholders."""
    scrubbed = aiguard.scrub(text or "", vals)
    parts = re.split(r"(\[[a-z]+\])", scrubbed)
    return " ".join(x for x in (p if p.startswith("[") else clean_payee(p)
                                for p in parts) if x)


def _open_jobs(office) -> list[dict]:
    return office.db.rows("SELECT * FROM jobs WHERE deleted = 0 "
                          "ORDER BY number")


def ask_model(office, ln, client=None) -> dict | None:
    """Layer 3. Returns a suggestion dict, or None (no model, no answer,
    or an answer that is not one of this company's accounts)."""
    c = client if client is not None else localai.client()
    if c is None:
        return None
    accts = choices(office)
    listing = "\n".join(f"{a['number']} {a['name']} ({a['type']})"
                        for a in accts)
    jl = _open_jobs(office)
    jobs_txt = "\n".join(f"{j['number']} {j['name']}" for j in jl) or "none"
    direction = "money in" if ln["amount"] > 0 else "money out"
    vals = aiguard.protected_values(office)
    user = (f"Accounts:\n{listing}\n\nOpen jobs:\n{jobs_txt}\n\nLine: "
            f"{ln['date']}, {direction}, {cents.text(abs(ln['amount']))}, "
            f"payee '{_safe_clean(ln['payee'], vals)}', "
            f"description '{_safe_clean(ln['memo'], vals)}'")
    try:
        r = c.chat(office, SYSTEM, user)
    except localai.AIUnavailable:
        return None
    except aiguard.PIIBlocked as e:
        aitrail.log(office, "categorize", "model", "statement_line",
                    ln["id"], {}, "", f"not sent: {e}", status="discarded")
        return None
    ans = localai.parse_json(r["text"])
    num = str(ans.get("account") or "").strip()
    a = next((x for x in accts if x["number"] == num), None)
    meta = {"model": r["model"], "model_version": r.get("model_version", ""),
            "input_hash": r["input_hash"]}
    if a is None:
        aitrail.log(office, "categorize", "model", "statement_line",
                    ln["id"], {"account": num}, ans.get("confidence", ""),
                    "not an account in this company's list; ignored",
                    status="discarded", **meta)
        return None
    try:
        conf = Decimal(str(ans.get("confidence", 0))).quantize(
            Decimal("0.01"))
    except Exception:                                     # noqa: BLE001
        conf = Decimal(0)
    conf = min(max(conf, Decimal(0)), Decimal(1))
    job = next((j for j in jl if j["number"] == str(ans.get("job") or
                                                     "").strip()), None)
    code = ""
    if job is not None:
        from . import jobs as _jobs
        cc = str(ans.get("cost_code") or "").strip()
        code = cc if cc in _jobs.cost_codes(office, job["id"]) else ""
    return dict({"account_id": a["id"],
                 "job_id": job["id"] if job else None, "cost_code": code,
                 "confidence": str(conf),
                 "reason": str(ans.get("reason") or "")[:200] or
                 f"local model: {a['number']} {a['name']}"}, **meta)


def suggest_line(office, lid, client=None) -> dict | None:
    """Work out one line's suggestion through the three layers."""
    office.require("bank.edit", "statement_line", lid)
    s = banking.suggest(office, lid)
    if s is not None:
        return s
    ln = banking.line(office, lid)
    if ln["status"] in ("Accepted", "Excluded") or ln["user_categorized"]:
        return None
    layer, prop = "similar", similar(office, ln)
    if prop is None:
        layer, prop = "model", ask_model(office, ln, client)
    if prop is None:
        return None
    thr = Decimal(localai.config()["threshold"])
    model = prop.pop("model", "")
    mver = prop.pop("model_version", "")
    ihash = prop.pop("input_hash", "")
    log_id = aitrail.log(office, "categorize", layer, "statement_line", lid,
                         {k: prop[k] for k in ("account_id", "job_id",
                                               "cost_code")},
                         prop["confidence"], prop["reason"], model, ihash,
                         model_version=mver)
    s = dict(prop, kind="ai", layer=layer, ai_log_id=log_id,
             low=Decimal(prop["confidence"]) < thr)
    with office.db.tx():
        office.db.update("statement_lines", lid, suggestion=json.dumps(s),
                         status="Suggested")
    return s


def suggest_queue(office, bank_account_id=None, client=None,
                  cancelled=None) -> dict:
    """Suggest for every open line. `cancelled` is a callable checked
    between lines (the Cancel button); lines done so far keep their
    suggestions."""
    c = client if client is not None else localai.client()
    n = {"rule": 0, "similar": 0, "model": 0, "none": 0,
         "model_available": False, "cancelled": False}
    try:
        if c is not None and not c.available():
            c = None
    except localai.Cancelled:
        n["cancelled"] = True
        return n
    n["model_available"] = c is not None
    for ln in banking.review_queue(office, bank_account_id):
        if cancelled is not None and cancelled():
            n["cancelled"] = True
            break
        if ln["status"] not in ("New", "Suggested"):
            continue
        try:
            s = suggest_line(office, ln["id"], c)
        except localai.Cancelled:
            n["cancelled"] = True
            break
        key = "none" if s is None else (s.get("layer") if s["kind"] == "ai"
                                        else "rule")
        n[key] += 1
    return n


def accept_bulk(office, bank_account_id=None, threshold=None) -> dict:
    """'Accept AI suggestions at or above the threshold' - the user's
    click. Each accepted line can still be undone one by one."""
    office.require("bank.edit", "statement_line", "accept AI")
    thr = Decimal(str(threshold if threshold is not None
                      else localai.config()["threshold"]))
    done, skipped = [], 0
    for ln in banking.review_queue(office, bank_account_id):
        s = ln["suggestion"] or {}
        if ln["status"] != "Suggested" or s.get("kind") != "ai":
            continue
        if Decimal(s["confidence"]) < thr:
            skipped += 1
            continue
        banking.accept(office, ln["id"])
        done.append(ln["id"])
    office.audit("ai bulk accept", "statement_line", None, None,
                 {"threshold": str(thr), "accepted": done,
                  "below_threshold": skipped})
    return {"accepted": done, "below_threshold": skipped,
            "threshold": str(thr)}


def dismiss(office, lid, reason="") -> None:
    """The user turns an AI suggestion down; the line goes back to New."""
    office.require("bank.edit", "statement_line", lid)
    ln = banking.line(office, lid)
    s = ln["suggestion"] or {}
    if s.get("kind") != "ai":
        raise AICatError("This line has no AI suggestion.")
    with office.db.tx():
        office.db.update("statement_lines", lid, suggestion=None,
                         status="New")
        aitrail.decide(office, s["ai_log_id"], "rejected",
                       detail={"reason": reason})


def on_accept(office, lid, s, entry_id) -> None:
    """Called by banking.accept for an AI suggestion."""
    aitrail.decide(office, s["ai_log_id"], "accepted", entry_id=entry_id,
                   undo={"entry": entry_id, "line": lid})


def on_categorize(office, lid, old, account_id) -> None:
    """The user picked a category over an AI suggestion: 'corrected'."""
    if old and old.get("kind") == "ai" and old.get("ai_log_id"):
        aitrail.decide(office, old["ai_log_id"], "corrected",
                       detail={"user_account": account_id})


def undo_accept(office, lid, reason="") -> int:
    """Undo an accepted AI suggestion: an exact reversing entry; the line
    is back in the review queue. Refused once the line is reconciled."""
    office.require("bank.edit", "statement_line", lid)
    ln = banking.line(office, lid)
    s = ln["suggestion"] or {}
    if ln["status"] != "Accepted" or s.get("kind") != "ai":
        raise AICatError("Only an accepted AI suggestion can be undone here.")
    if ln["reconciliation_id"] or (ln["journal_line_id"] and
                                   banking._line_reconciled(
                                       office, ln["journal_line_id"])):
        raise AICatError("This line is reconciled; undo the reconciliation "
                         "first.")
    with office.db.tx():
        rid = ledger.reverse(office, ln["entry_id"],
                             ledger.first_open_date(office, clock.today()),
                             f"Undo AI suggestion (line {lid})")
        if ln["journal_line_id"]:
            office.db.update("journal_lines", ln["journal_line_id"],
                             statement_line_id=None)
        office.db.update("statement_lines", lid, status="New",
                         suggestion=None, journal_line_id=None,
                         entry_id=None)
        aitrail.decide(office, s["ai_log_id"], "undone",
                       undo={"entry": ln["entry_id"], "reversal": rid},
                       detail={"reason": reason})
    return rid


# ---- reconciliation suggestions --------------------------------------------

def recon_suggestions(office, rid) -> dict:
    """Which uncleared items to tick: items already tied to a statement
    line dated in the period, or one same-amount statement line within
    banking.MATCH_DAYS. Pure: nothing is ticked or logged here (the UI may
    call it to refresh); run_recon_suggestions() is the logged run."""
    from . import reconcile
    r = reconcile.reconciliation(office, rid)
    st = reconcile.status(office, rid)
    lines = office.db.rows(
        "SELECT * FROM statement_lines WHERE bank_account_id = ? AND "
        "deleted = 0 AND status != 'Excluded' AND date <= ?",
        (r["bank_account_id"], r["period_end"]))
    by_jl = {ln["journal_line_id"]: ln for ln in lines
             if ln["journal_line_id"]}
    free = [ln for ln in lines if not ln["journal_line_id"]]
    used, out = set(), []
    for it in reconcile.items(office, rid):
        if it["cleared"]:
            continue
        if it["line_id"] in by_jl:
            sl = by_jl[it["line_id"]]
            out.append({"line_id": it["line_id"], "amount": it["amount"],
                        "statement_line": sl["id"], "confidence": "1.00",
                        "reason": f"on the statement {sl['date']}: "
                                  f"{sl['payee']}"})
            continue
        hits = [ln for ln in free if ln["amount"] == it["amount"] and
                ln["id"] not in used and banking._near(ln["date"], it["date"])]
        if len(hits) == 1:
            used.add(hits[0]["id"])
            out.append({"line_id": it["line_id"], "amount": it["amount"],
                        "statement_line": hits[0]["id"],
                        "confidence": "0.90",
                        "reason": f"same amount on the statement "
                                  f"{hits[0]['date']}: {hits[0]['payee']}"})
    diff = st["difference"] - sum(o["amount"] for o in out)
    return {"suggestions": out, "difference_if_applied": diff,
            "label": "Ready to finish" if diff == 0 and out else
            ("Difference after suggestions: " + cents.fmt(diff))}


def run_recon_suggestions(office, rid) -> dict:
    """The user's 'Suggest matches' click: one ai_log row per suggestion
    made in this run (an item already suggested and still open is not
    logged twice)."""
    office.require("bank.edit", "reconciliation", rid)
    res = recon_suggestions(office, rid)
    open_ = {(json.loads(x["proposal"]) or {}).get("line_id"): x["id"]
             for x in office.db.rows(
                 "SELECT id, proposal FROM ai_log WHERE kind = 'reconcile' "
                 "AND record_type = 'reconciliation' AND record_id = ? AND "
                 "status = 'suggested'", (rid,))}
    for o in res["suggestions"]:
        o["ai_log_id"] = open_.get(o["line_id"]) or aitrail.log(
            office, "reconcile", "match", "reconciliation", rid,
            {"line_id": o["line_id"], "statement_line": o["statement_line"]},
            o["confidence"], o["reason"])
    return res


def apply_recon(office, rid, log_ids) -> dict:
    """The user's click: tick the chosen suggestions. 'Ready to finish'
    still needs the user's Finish click (reconcile.finish)."""
    from . import reconcile
    office.require("bank.edit", "reconciliation", rid)
    ids = []
    for lg in log_ids:
        r = aitrail.get(office, lg)
        if r["record_type"] != "reconciliation" or r["record_id"] != rid:
            raise AICatError("That suggestion is for another reconciliation.")
        ids.append(r["proposal"]["line_id"])
    st = reconcile.set_cleared(office, rid, ids, True)
    for lg in log_ids:
        aitrail.decide(office, lg, "accepted")
    st["label"] = "Ready to finish" if st["can_finish"] else \
        "Difference " + st["difference_text"]
    return st
