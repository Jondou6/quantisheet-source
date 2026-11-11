"""Read a sub's proposal with the local AI when the patterns couldn't
(Nov 11): lines left unread, or lines that don't add up to the total.

The model runs on this PC (Ollama on localhost; ai/review.py); nothing
leaves the computer, and it runs only when the user asks.

A model can make things up, so nothing it says is taken on trust:

* every value must be found in the quote, word for word (an amount: its
  digits on the page; an exclusion: its words in order on one line).
  A value that isn't on the page is rejected and counted, never kept;
* every kept value carries its place (page and rectangle), the same as
  the pattern reader's, so it can be shown in the file;
* kept values are only *offered*: each is marked "AI, check" and goes
  into the quote when a person accepts it (accept());
* lines that don't add up to the stated total are flagged, never changed
  to fit.

Pure Python, no Qt.
"""
import json
import re

from . import proposal_level as pl
from .dmoney import c2 as _c2

MAX_LINES = 400          # lines of the quote sent to the model
KINDS = ("line", "total", "alternate", "exclusion", "inclusion",
         "clarification")

PROMPT = (
    "Below is a subcontractor's price proposal, one line of the document "
    "per row, each row starting with its row number in square brackets.\n"
    "Copy out what it says. Do not add, estimate or correct anything. "
    "Answer with JSON only, in this shape:\n"
    '{"lines": [{"row": 12, "desc": "...", "qty": 100, "unit": "LF", '
    '"unit_price": 4.50, "amount": 450.00}], '
    '"total": {"row": 30, "amount": 12345.00}, '
    '"alternates": [{"row": 31, "desc": "...", "amount": 500.00}], '
    '"exclusions": [{"row": 33, "text": "..."}], '
    '"inclusions": [{"row": 34, "text": "..."}], '
    '"clarifications": [{"row": 35, "text": "..."}]}\n'
    "Rules: \"row\" is the row number the value is written on. Copy "
    "descriptions and texts exactly as written. A priced line needs its "
    "amount; give qty, unit and unit_price only when they are written. "
    "Leave out anything that is not in the document.\n\nPROPOSAL:\n")


def needs_ai(p):
    """Would Read with AI be worth offering for this parsed quote?"""
    return bool(p.get("unread")) or "they differ" in (p.get("check") or "") \
        or not p.get("lines")


def prompt_for(loc):
    rows = [f"[{i}] {ln['text']}" for i, ln in enumerate(loc[:MAX_LINES])]
    return PROMPT + "\n".join(rows)


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(re.sub(r"[^0-9.\-]", "", str(v)) or "x")
    except ValueError:
        return None


def _digits(v):
    """An amount's digits as they'd be written: 54000.0 -> '54000'."""
    s = f"{_c2(v):.2f}"
    whole, cents = s.split(".")
    return whole.lstrip("-"), cents


def _amount_word(ln, amount):
    """The word on this line that is this amount, or None."""
    whole, cents = _digits(amount)
    for w, r in reversed(ln.get("words") or []):
        t = re.sub(r"[^0-9.]", "", w)
        if not t:
            continue
        a, _dot, b = t.partition(".")
        if a.lstrip("0") == whole.lstrip("0") and \
                (b or "00").ljust(2, "0")[:2] == cents:
            return r
    return None


def _has_amount(ln, amount):
    whole, cents = _digits(amount)
    for t in re.findall(r"[\d,]+(?:\.\d{1,2})?", ln["text"]):
        a, _dot, b = t.replace(",", "").partition(".")
        if a.lstrip("0") == whole.lstrip("0") and \
                (b or "00").ljust(2, "0")[:2] == cents:
            return True
    return False


def _tokens(s):
    return [t for t in (pl._alnum(x) for x in str(s).split()) if t]


def _has_text(ln, text):
    want, have = _tokens(text), _tokens(ln["text"])
    n = len(want)
    return bool(n) and any(have[i:i + n] == want
                           for i in range(len(have) - n + 1))


def _row_for(loc, row, test):
    """The line the model named if the value really is on it, else the
    first line that has it, else None."""
    try:
        i = int(row)
    except (TypeError, ValueError):
        i = -1
    if 0 <= i < len(loc) and test(loc[i]):
        return loc[i]
    return next((ln for ln in loc if test(ln)), None)


def _place(ln, rect=None, part=None):
    """{"page", "rect"} or None when the line has no boxes (OCR text)."""
    if not ln.get("words"):
        return None
    if rect is not None:
        return {"page": ln["page"],
                "rect": [round(v, 3) for v in rect]}
    return pl._src(ln, part)


def check_answer(answer, loc):
    """(offers, rejected): the model's values that are in the quote word
    for word, each {"kind", ..., "src", "src_amount", "ai": True}; and
    [(kind, what, why)] for the ones that aren't."""
    if isinstance(answer, str):
        m = re.search(r"\{.*\}", answer, re.S)
        try:
            answer = json.loads(m.group(0) if m else answer)
        except ValueError:
            raise ValueError("The model's answer wasn't the list it was "
                             "asked for. Try again.") from None
    if not isinstance(answer, dict):
        raise ValueError("The model's answer wasn't the list it was asked "
                         "for. Try again.")
    offers, rejected = [], []

    def no(kind, what, why):
        rejected.append((kind, str(what)[:120], why))

    def money(kind, item, extra):
        amt = _num(item.get("amount"))
        desc = str(item.get("desc") or "").strip()
        if amt is None:
            return no(kind, desc or item, "no amount")
        ln = _row_for(loc, item.get("row"), lambda L: _has_amount(L, amt)
                      and (not desc or _has_text(L, desc)))
        if ln is None:
            ln = _row_for(loc, item.get("row"),
                          lambda L: _has_amount(L, amt))
            if ln is None:
                return no(kind, f"{desc} {_c2(amt):,.2f}",
                          "that amount isn't in the quote")
            if kind != "total" and desc and not any(
                    t in _tokens(ln["text"]) for t in _tokens(desc)):
                return no(kind, f"{desc} {_c2(amt):,.2f}", "the description "
                          "isn't on the line with that amount")
        src = _place(ln)
        if src is None:
            return no(kind, f"{desc} {_c2(amt):,.2f}",
                      "no place on the page to show for it")
        box = _amount_word(ln, amt)
        o = {"kind": kind, "amount": amt, "src": src,
             "src_amount": _place(ln, box) if box else src, "ai": True}
        o.update(extra(ln))
        offers.append(o)

    for it in answer.get("lines") or []:
        if not isinstance(it, dict):
            continue

        def line_extra(ln, it=it):
            desc = str(it.get("desc") or "").strip() or ln["text"]
            qty, up = _num(it.get("qty")), _num(it.get("unit_price"))
            unit = str(it.get("unit") or "").strip().upper()
            amt = _num(it.get("amount"))
            # qty, unit and unit price are kept only when they are on the
            # line and multiply out; otherwise the line is a lump sum
            ok = (qty and up is not None and unit and
                  _has_amount(ln, up) and
                  re.search(rf"(?<![\d.]){re.escape(f'{qty:g}')}(?![\d.])",
                            ln["text"].replace(",", "")) and
                  abs(qty * up - amt) <= max(1.0, 0.01 * abs(amt)))
            if ok:
                return {"desc": pl._norm_desc(desc), "qty": qty,
                        "unit": unit, "price": up}
            return {"desc": pl._norm_desc(desc), "qty": 1.0, "unit": "LS",
                    "price": amt}
        money("line", it, line_extra)
    tot = answer.get("total")
    if isinstance(tot, dict) and _num(tot.get("amount")) is not None:
        money("total", {"row": tot.get("row"), "amount": tot.get("amount")},
              lambda ln: {})
    for it in answer.get("alternates") or []:
        if isinstance(it, dict):
            money("alternate", it, lambda ln, it=it: {
                "desc": str(it.get("desc") or "").strip() or ln["text"]})
    for key, kind in (("exclusions", "exclusion"),
                      ("inclusions", "inclusion"),
                      ("clarifications", "clarification")):
        for it in answer.get(key) or []:
            text = (it.get("text") if isinstance(it, dict) else it) or ""
            text = str(text).strip(" .-•*")
            if not text:
                continue
            ln = _row_for(loc, it.get("row") if isinstance(it, dict)
                          else None, lambda L: _has_text(L, text))
            if ln is None:
                no(kind, text, "those words aren't in the quote")
                continue
            src = _place(ln, part=text)
            if src is None:
                no(kind, text, "no place on the page to show for it")
                continue
            offers.append({"kind": kind, "text": text, "src": src,
                           "ai": True})
    return offers, rejected


def _key(o):
    return (o["kind"], o["src"]["page"], tuple(o["src"]["rect"]),
            o.get("amount"), o.get("text"))


def new_only(p, offers):
    """Offers the pattern reader doesn't already have."""
    have_amt = {(r["src"]["page"], tuple(r["src"]["rect"]))
                for r in p.get("lines") or [] if r.get("src")}
    have_txt = {pl._alnum(t) for k in ("exclusions", "inclusions")
                for t in p.get(k) or []}
    out, seen = [], set()
    for o in offers:
        if _key(o) in seen:
            continue
        seen.add(_key(o))
        if o["kind"] == "line" and (o["src"]["page"],
                                    tuple(o["src"]["rect"])) in have_amt:
            continue
        if o["kind"] in ("exclusion", "inclusion") and \
                pl._alnum(o["text"]) in have_txt:
            continue
        if o["kind"] == "total" and p.get("total") is not None and \
                abs(p["total"] - o["amount"]) < 0.005:
            continue
        out.append(o)
    return out


def read(p, ask=None, loc=None):
    """Ask the local model about the parsed quote `p`. Returns {"offers",
    "rejected", "note"}; nothing in `p` changes. `ask(prompt)` gives the
    model's answer (default: the local Ollama model, JSON mode); `loc`:
    the quote's located lines (default: read from p["path"])."""
    if loc is None:
        loc = pl.located_lines(p["path"])
    if not loc:
        raise ValueError("There is no text in this quote to read.")
    if ask is None:
        from .ai import review
        ask = lambda prompt: review._ollama(prompt, json_mode=True)  # noqa
    offers, rejected = check_answer(ask(prompt_for(loc)), loc)
    offers = new_only(p, offers)
    bits = [f"{len(offers)} value(s) found in the quote and offered"]
    if rejected:
        bits.append(f"{len(rejected)} the model gave that are not in the "
                    "quote were thrown out")
    if len(loc) > MAX_LINES:
        bits.append(f"only the first {MAX_LINES} lines were read")
    return {"offers": offers, "rejected": rejected,
            "note": "; ".join(bits) + "."}


def accept(p, offers, by=""):
    """Put the accepted offers into the quote (a copy is returned; `p` is
    not changed). Each keeps "ai": True and who accepted it. The math
    check is run again: a difference is reported, never hidden."""
    q = json.loads(json.dumps(p))
    S = q.setdefault("sources", {})
    for k in ("exclusions", "inclusions", "alternates", "unread"):
        S.setdefault(k, [None] * len(q.get(k) or []))
    for o in offers:
        k = o["kind"]
        if k == "line":
            q["lines"].append({
                "item_no": "", "desc": o["desc"], "qty": o["qty"],
                "unit": o["unit"], "price": o["price"],
                "amount": o["amount"], "src": o["src"],
                "src_amount": o["src_amount"], "ai": True,
                "accepted_by": by})
        elif k == "total":
            q["total"] = o["amount"]
            S["total"] = o["src_amount"]
            q["total_ai"] = True
        elif k == "alternate":
            q["alternates"].append({"no": "", "desc": o["desc"],
                                    "amount": o["amount"], "ai": True})
            S["alternates"].append(o["src"])
        elif k in ("exclusion", "inclusion"):
            q[k + "s"].append(o["text"])
            S[k + "s"].append(o["src"])
            q.setdefault("ai_texts", []).append(o["text"])
        elif k == "clarification":
            q.setdefault("clarifications", []).append(o["text"])
            S.setdefault("clarifications", []).append(o["src"])
            q.setdefault("ai_texts", []).append(o["text"])
    # an unread line now read is no longer unread
    got = []
    for o in offers:
        if o["kind"] in ("line", "total", "alternate"):
            s_ = o.get("src_amount") or o["src"]
            r = s_["rect"]
            got.append((s_["page"], (r[0] + r[2]) / 2, (r[1] + r[3]) / 2))

    def read_now(u):
        return bool(u) and any(
            pg == u["page"] and u["rect"][0] - 1 <= x <= u["rect"][2] + 1
            and u["rect"][1] - 1 <= y <= u["rect"][3] + 1
            for pg, x, y in got)
    if len(S.get("unread") or []) == len(q.get("unread") or []):
        keep = [i for i, u in enumerate(S["unread"]) if not read_now(u)]
        q["unread"] = [q["unread"][i] for i in keep]
        S["unread"] = [S["unread"][i] for i in keep]
    q["check"] = pl.check(q)
    n = sum(1 for r in q["lines"] if r.get("ai"))
    if n:
        q["check"] = (f"{n} line(s) read by AI and accepted"
                      f"{' by ' + by if by else ''} - check them. " +
                      q["check"]).strip()
    return q


def label(o):
    """One offer in words, for a list."""
    if o["kind"] == "line":
        q = "" if o["unit"] == "LS" else \
            f"{o['qty']:g} {o['unit']} x ${_c2(o['price']):,.2f} = "
        return f"{o['desc']}: {q}${_c2(o['amount']):,.2f}"
    if o["kind"] == "total":
        return f"Total ${_c2(o['amount']):,.2f}"
    if o["kind"] == "alternate":
        return f"Alternate: {o['desc']} ${_c2(o['amount']):,.2f}"
    return o["text"]
