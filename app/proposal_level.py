"""Level subs' emailed PDF proposals, with plug numbers from past bids
(v21).

What's already there: leveling.py / level_core.py level bids line by line
(omissions, carries, buy-ins, plugs at this job's median), and bidtab.py
reads bid *tables* and keeps a library of past bid prices. A sub's
free-form quote PDF ("8 in PVC ... 1,200 LF $45.00 $54,000.00 ...
Exclusions: permits") couldn't be read, and plugs never used past bids.

* parse(pdf): bidder, line items (qty, unit, unit price, amount), lump-sum
  lines, total, alternates, exclusions, inclusions, plus a check that the
  lines add up to the total.
* to_bids(proposals): the {bidder: rows} shape leveling.run takes.
* suggest_plugs(leveling result, library): for every item a bidder left
  out, a plug from the past-bid library (bidtab.analyze, escalated median,
  same unit, closest description), else this job's median, with the source
  named. as_plugs() turns them into leveling plugs.
* exclusions_matrix(proposals): who excludes what, side by side.

Scanned quotes and photos are read with OCR (ocr.py) when Tesseract is
installed. The parser is pattern-based, no AI. Low-confidence lines are
left out, never guessed (see "check"). Nov 11: every value read keeps
where it came from in the file (page and rectangle), see parse().
"""
import difflib
import os
import re
import statistics

import fitz
from .dmoney import c2 as _c2

UNITS = r"LF|EA|CY|SY|SF|LS|TON|TONS|HR|HRS|GAL|AC|VF|VLF|DAY|DAYS|MO|WK|LB|CF"
_MONEY = r"\$?\s?([\d,]+(?:\.\d{1,2})?)"
_ITEM = re.compile(rf"^(?:(\d{{1,3}})[.)]?\s+)?(.+?)\s+([\d,]+(?:\.\d+)?)\s+"
                   rf"({UNITS})\.?\s+{_MONEY}\s+{_MONEY}$", re.I)
_LUMP = re.compile(rf"^(?:(\d{{1,3}})[.)]?\s+)?(.+?)\s+(?:lump\s*sum|l\.?s\.?)"
                   rf"\s+{_MONEY}$", re.I)
_TOTAL = re.compile(rf"^(?:total\s+base\s+bid|base\s+bid|total\s+bid|"
                    rf"grand\s+total|total\s+price|total|lump\s+sum\s+total)"
                    rf"\b[\s:]*{_MONEY}\s*$", re.I)
_ALT = re.compile(rf"^alt(?:ernate)?\.?\s*#?\s*(\w+)\s*[:.-]\s*(.+?)\s+"
                  rf"(?:\(?(?:add|deduct)\)?\s+)?{_MONEY}\s*$", re.I)
_HEAD = re.compile(r"^(exclusions?|excludes|not included|inclusions?|"
                   r"includes|qualifications?|clarifications?|notes?)\s*:?"
                   r"\s*(.*)$", re.I)
_SKIP_NAME = re.compile(r"^(proposal|quotation|quote|bid( proposal)?|"
                        r"estimate|project\b.*|date\b.*|to\b.*|page\b.*)$",
                        re.I)


def _f(v):
    return float(str(v).replace(",", "").replace("$", "").strip())


def _norm_desc(d):
    d = re.sub(r"(\d+)\s*(?:inch|in\.?)(?=\s|$)", r'\1"', d, flags=re.I)
    d = re.sub(r"\s{2,}", " ", d).strip(" .-:")
    return d


def _split_list(s):
    parts = re.split(r",|;|\band\b(?![^()]*\))", s)
    return [p.strip(" .-•*") for p in parts if p.strip(" .-•*")]


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif")
MIN_TEXT = 30            # fewer letters than this on a page: it's a scan


def _open(path):
    """A PDF, or a picture of a quote (a phone photo, a scan) as a PDF."""
    if path.lower().endswith(IMAGE_EXT):
        img = fitz.open(path)
        pdf = fitz.open("pdf", img.convert_to_pdf())
        img.close()
        return pdf
    return fitz.open(path)


def _clean(ln):
    return re.sub(r"\s+", " ", ln.replace("\u2013", "-")).strip()


def located_lines(path, ocr=True, info=None):
    """The quote's lines of text, each with where it is on the page:
    [{"text", "page", "words": [(word, (x0, y0, x1, y1))]}]. A scanned
    page (or a picture) is read with OCR when Tesseract is installed;
    `info` gets "ocr": "used", "unavailable" or "". A line OCR gave as
    text only has no words (so no place on the page)."""
    out, used, missing = [], False, False
    with _open(path) as d:
        for n, page in enumerate(d):
            text = page.get_text("text")
            if ocr and len(re.sub(r"\s", "", text)) < MIN_TEXT:
                try:
                    from . import ocr as _ocr
                    try:
                        got = _ocr.ocr_page_lines(page)
                    except Exception:                     # noqa: BLE001
                        got = []
                    if got:
                        used = True
                        for ln in got:
                            t = _clean(ln["text"])
                            if t:
                                out.append({"text": t, "page": n,
                                            "words": ln["words"]})
                        continue
                    text = _ocr.ocr_page(page)
                    used = True
                except Exception:                         # noqa: BLE001
                    missing = True
                for ln in text.splitlines():
                    ln = _clean(ln)
                    if ln:
                        out.append({"text": ln, "page": n, "words": []})
                continue
            # the same lines get_text("text") gives, with each word's box
            rows, order = {}, []
            for x0, y0, x1, y1, w, blk, line, _no in page.get_text("words"):
                k = (blk, line)
                if k not in rows:
                    rows[k] = []
                    order.append(k)
                rows[k].append((w, (x0, y0, x1, y1)))
            for k in order:
                t = _clean(" ".join(w for w, _r in rows[k]))
                if t:
                    out.append({"text": t, "page": n, "words": rows[k]})
    if info is not None:
        info["ocr"] = "used" if used else "unavailable" if missing else ""
    return out


def text_lines(path, ocr=True, info=None):
    """The quote's lines of text (see located_lines)."""
    return [ln["text"] for ln in located_lines(path, ocr, info)]


def _union(rects):
    return [min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects)]


def _alnum(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _src(ln, part=None, last_number=False):
    """Where a value is: {"page", "rect"} for the whole line, for the
    words of `part` in it, or for the last number on it. None when the
    line has no place on the page (typed lines, OCR text without boxes)."""
    if not ln or not ln.get("words"):
        return None
    words = ln["words"]
    pick = None
    if last_number:
        for w, r in reversed(words):
            if re.search(r"\d", w):
                pick = [r]
                break
    elif part:
        want = [_alnum(t) for t in str(part).split()]
        want = [t for t in want if t]
        have = [_alnum(w) for w, _r in words]
        n = len(want)
        for i in range(len(have) - n + 1 if n else 0):
            if have[i:i + n] == want:
                pick = [r for _w, r in words[i:i + n]]
                break
        if pick is None and n:             # the words, wherever they are
            hits = [r for (w, r), h in zip(words, have) if h and h in want]
            pick = hits or None
    return {"page": ln["page"],
            "rect": [round(v, 3) for v in _union(
                pick or [r for _w, r in words])]}


def parse(path, lines=None):
    """Read a quote. Every value read from the file says where it came
    from: lines carry "src" (the line) and "src_amount" (the amount on
    it); "sources" has "bidder", "total", and lists alongside
    "exclusions", "inclusions", "alternates" and "unread" - each
    {"page", "rect"} in PDF points, or None when there is no place to
    point at (`lines` typed in, OCR that gave text only)."""
    info = {"ocr": ""}
    if lines is not None:
        loc = [{"text": ln, "page": 0, "words": []} for ln in lines]
    else:
        loc = located_lines(path, info=info)
    p = {"file": os.path.basename(path), "path": os.path.abspath(path),
         "bidder": "", "lines": [],
         "total": None, "alternates": [], "exclusions": [], "inclusions": [],
         "unread": [],
         "sources": {"bidder": None, "total": None, "exclusions": [],
                     "inclusions": [], "alternates": [], "unread": []}}
    S = p["sources"]
    section = None
    for L in loc:
        ln = L["text"]
        t = re.sub(r"\b(\d+)\s*(?:inch|in\.)(?=\s)", r'\1"', ln.strip(),
                   flags=re.I)
        if not p["bidder"] and re.search(r"[A-Za-z]{3}", t) and \
                not _SKIP_NAME.match(t) and not _ITEM.match(t):
            p["bidder"] = t
            S["bidder"] = _src(L)
            continue
        h = _HEAD.match(t)
        if h:
            kind = h.group(1).lower()
            section = "exclusions" if kind.startswith(("excl", "not")) else \
                "inclusions" if kind.startswith("incl") else None
            if section and h.group(2):
                for part in _split_list(h.group(2)):
                    p[section].append(part)
                    S[section].append(_src(L, part))
            continue
        if section and re.match(r"^[-•*]\s*", t):
            p[section].append(t.lstrip("-•* ").strip())
            S[section].append(_src(L))
            continue
        m = _TOTAL.match(t)
        if m:
            p["total"] = _f(m.group(1))
            S["total"] = _src(L, last_number=True)
            section = None
            continue
        m = _ALT.match(t)
        if m:
            p["alternates"].append({"no": m.group(1), "desc": m.group(2)
                                    .strip(), "amount": _f(m.group(3))})
            S["alternates"].append(_src(L))
            continue
        m = _ITEM.match(t)
        if m:
            qty, price, amt = _f(m.group(3)), _f(m.group(5)), _f(m.group(6))
            if qty and abs(qty * price - amt) <= max(1.0, 0.01 * amt):
                p["lines"].append({"item_no": m.group(1) or "",
                                   "desc": _norm_desc(m.group(2)),
                                   "qty": qty, "unit": m.group(4).upper(),
                                   "price": price, "amount": amt,
                                   "src": _src(L),
                                   "src_amount": _src(L, last_number=True)})
            else:
                p["unread"].append(t)
                S["unread"].append(_src(L))
            section = None
            continue
        m = _LUMP.match(t)
        if m:
            amt = _f(m.group(3))
            p["lines"].append({"item_no": m.group(1) or "",
                               "desc": _norm_desc(m.group(2)), "qty": 1.0,
                               "unit": "LS", "price": amt, "amount": amt,
                               "src": _src(L),
                               "src_amount": _src(L, last_number=True)})
            section = None
            continue
        if section is None and re.search(r"\$\s?[\d,]+", t):
            p["unread"].append(t)                      # money we didn't read
            S["unread"].append(_src(L))
    if not p["bidder"]:
        p["bidder"] = os.path.splitext(p["file"])[0]
    p["ocr"] = info["ocr"]
    p["check"] = check(p)
    if info["ocr"] == "used":
        p["check"] = ("Read from a scan (OCR) - check the numbers. " +
                      p["check"]).strip()
    elif info["ocr"] == "unavailable" and not p["lines"]:
        p["check"] = ("This quote is a scan and OCR (Tesseract) isn't "
                      "installed, so it couldn't be read. " +
                      p["check"]).strip()
    return p


def source_of(p, kind, key):
    """Where a value of the parsed quote `p` is, as {"file", "page",
    "rect"} for the viewer, or None. kind: "line" (key: index or
    description), "amount" (same), "exclusion" / "inclusion" (the
    wording), "total", "bidder"."""
    S = p.get("sources") or {}
    src = None
    if kind in ("line", "amount"):
        rows = p.get("lines") or []
        r = rows[key] if isinstance(key, int) and 0 <= key < len(rows) \
            else next((x for x in rows if x.get("desc") == key), None)
        src = r and r.get("src_amount" if kind == "amount" else "src")
    elif kind in ("exclusion", "inclusion", "clarification"):
        names = p.get(kind + "s") or []
        want = str(key).strip().lower()
        i = next((i for i, t in enumerate(names)
                  if t.strip().lower() == want), None)
        lst = S.get(kind + "s") or []
        src = lst[i] if i is not None and i < len(lst) else None
    elif kind in ("total", "bidder"):
        src = S.get(kind)
    if not src or not p.get("path"):
        return None
    return {"file": p["path"], "page": src["page"], "rect": list(src["rect"])}


def check(p):
    s = _c2(sum(r["amount"] for r in p["lines"]))
    msgs = []
    if p.get("total") is not None and p["lines"] and \
            abs(s - p["total"]) > 1.0:
        msgs.append(f"Lines add up to ${_c2(s):,.2f}; the total says "
                    f"${_c2(p['total']):,.2f} - they differ.")
    if p.get("unread"):
        msgs.append(f"{len(p['unread'])} line(s) with prices weren't read - "
                    "check them by hand.")
    return " ".join(msgs)


def to_bids(proposals):
    bids = {}
    for p in proposals:
        rows = bids.setdefault(p["bidder"], [])
        for r in p["lines"]:
            rows.append({"desc": r["desc"], "unit": r["unit"],
                         "qty": r["qty"], "price": r["price"],
                         "item_no": "", "bidder": p["bidder"],
                         "note": "read by AI - check" if r.get("ai")
                         else ""})
    return bids


def _closest(desc, unit, library, cutoff=0.6):
    cands = [i for i in library or [] if str(i.get("unit", "")).upper() ==
             str(unit).upper()]
    names = [c["desc"].lower() for c in cands]
    hit = difflib.get_close_matches(desc.lower(), names, 1, cutoff)
    return cands[names.index(hit[0])] if hit else None


def suggest_plugs(res, library=None):
    """[{bidder, item, unit, qty, unit_price, amount, source}] for each item
    a bidder left out. `library`: bidtab.analyze() items (pass [] to skip;
    None reads the price database)."""
    if library is None:
        try:
            from . import bidtab
            library = bidtab.analyze()
        except Exception:
            library = []
    out = []
    for bidder, items in res["analysis"]["omissions"].items():
        for it in items:
            qty = float(getattr(it, "qty", 1) or 1)
            lib = _closest(it.desc, it.unit, library)
            if lib and lib.get("esc_median"):
                up = float(lib["esc_median"])
                src = (f"past bids: {lib.get('bids', '?')} bids on "
                       f"{lib.get('projects', '?')} projects "
                       f"('{lib['desc']}', escalated median)")
            elif getattr(it, "prices", None):
                up = float(it.median)
                src = f"this job's median ({len(it.prices)} bids)"
            else:
                continue
            out.append({"bidder": bidder, "item": it.desc, "unit": it.unit,
                        "qty": qty, "unit_price": _c2(up),
                        "amount": _c2(up * qty), "source": src})
    return out


def as_plugs(suggestions):
    return [{"bidder": s["bidder"], "item": s["item"], "kind": "Plug",
             "amount": s["amount"], "note": s["source"]}
            for s in suggestions]


def _ex_key(text):
    for w in re.findall(r"[a-z]+", text.lower()):
        if len(w) >= 4 and w not in ("with", "from", "work", "fees", "cost",
                                     "costs", "all", "any"):
            return w
    return text.lower().strip()


def exclusions_matrix(proposals):
    """{exclusion key: {bidder: excluded?}}."""
    keys = {}
    for p in proposals:
        for e in p["exclusions"]:
            keys.setdefault(_ex_key(e), set()).add(p["bidder"])
    return {k: {p["bidder"]: p["bidder"] in who for p in proposals}
            for k, who in sorted(keys.items())}
