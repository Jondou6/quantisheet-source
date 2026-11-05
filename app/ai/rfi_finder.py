"""Find RFIs and questions in plans and specifications.

Two kinds of finding:

* Checks that need no AI and are dependable: detail callouts that point
  to sheets not in the set, spec sections the drawings cite that the spec
  book doesn't contain, equipment tags shown on plans but missing from
  their schedule, and "TBD" / "by others" notes that leave scope open.
* An AI review with the local Ollama model (nothing leaves the computer):
  conflicts between plans and specs or between sheets, missing or unclear
  information. It works from text pulled out on the GUI thread, so the
  slow model call can run in the background.

Every finding: {"question", "reason", "reference", "quote", "page",
"doc" ("plans" | "specs"), "source" ("check" | "AI")}.
"""
import re

from . import review
from . import rfi_rules as _rules

CALLOUT = re.compile(r"\b(\d{1,2}[A-Z]?)\s*/\s*([A-Z]{1,2}-?\d{1,3}(?:\.\d{1,2})?)\b")
SPEC_SEC = re.compile(r"\b(\d{2})\s(\d{2})\s(\d{2})(?:\.\d{2})?\b")
SECTION_HEAD = re.compile(r"SECTION\s+(\d{2})\s?(\d{2})\s?(\d{2})", re.I)
EQUIP = re.compile(r"\b([A-Z]{1,4})-(\d{1,3}[A-Z]?)\b")
OPEN_SCOPE = re.compile(r"\b(TBD|T\.B\.D\.|TO BE DETERMINED|BY OTHERS|"
                        r"N\.?I\.?C\.?|NOT IN CONTRACT|VERIFY IN FIELD|"
                        r"V\.I\.F\.)\b", re.I)
# prefixes that look like tags but aren't equipment
NOT_EQUIP = {"A", "S", "M", "E", "P", "C", "L", "T", "FP", "ID", "AD", "G",
             "FA", "NO", "SHT", "REV", "DWG", "ASTM", "UL", "ANSI", "NFPA",
             "SF", "LF", "EA", "TYP"}

PROMPT = (
    "You are a construction document reviewer preparing RFIs (requests "
    "for information) for a contractor. Review the drawing and "
    "specification text below. List real problems a contractor would need "
    "answered before pricing or building: conflicts between drawings and "
    "specifications, conflicting notes or dimensions between sheets, "
    "missing or unclear information, products or materials not specified, "
    "and scope that is unassigned. Do not invent problems; skip anything "
    "you are not sure about. Reply with JSON: {\"items\": [{\"question\": "
    "the RFI question to ask the architect, \"reason\": why it matters, "
    "\"reference\": sheet number or spec section, \"page\": the [Page N] "
    "number, \"quote\": a short exact phrase copied from that page}]}."
)


SPEC_PROMPT = (
    "You are a construction document reviewer preparing RFIs (requests "
    "for information) for a contractor bidding this project. Review the "
    "specification / project manual text below. List real problems a "
    "contractor would need answered before pricing or building: "
    "requirements that conflict with each other, products or materials "
    "named without enough to price them (no manufacturer, basis of "
    "design or performance), discontinued or proprietary items with no "
    "substitution path, allowances, alternates or unit prices that are "
    "unclear, scope assigned to no one, testing or submittals with no "
    "clear responsibility, and dates, durations or quantities that don't "
    "add up. Do not invent problems; skip anything you are not sure "
    "about. Reply with JSON: {\"items\": [{\"question\": the RFI "
    "question to ask the architect, \"reason\": why it matters, "
    "\"reference\": the spec section number, \"page\": the [Page N] "
    "number, \"quote\": a short exact phrase copied from that page}]}."
)
SPEC_CHUNKS = 120      # AI passes over a spec book (each ~24k characters): the whole book, up to ~2,800 pages
SECTION_REF = re.compile(r"\bSection\s+(\d{2})\s?(\d{2})\s?(\d{2})\b")
# a section's own heading: "SECTION 08 11 13" at the start of a line
# (not "see Section 08 71 00" inside a paragraph)
HEADING = re.compile(r"^\s*SECTION\s+(\d{2})\s?(\d{2})\s?(\d{2})", re.M)
PART_HEAD = re.compile(r"\bPART\s+1\s*[-\u2013\u2014.]?\s*GENERAL\b", re.I)


def is_spec_book(pages):
    """True when the open PDF reads like a specification book / project
    manual (SECTION xx xx xx and PART 1 - GENERAL headings, few sheet
    numbers) rather than drawings."""
    if not pages:
        return False
    spec = sum(1 for _i, _n, _t, text in pages
               if SECTION_HEAD.search(text) or PART_HEAD.search(text))
    sheets_ = sum(1 for _i, n, _t, _x in pages if n)
    words = sum(len(t.split()) for _i, _n, _t, t in pages) / len(pages)
    return (spec >= max(2, len(pages) * 0.15) and sheets_ < len(pages) / 2) \
        or (words > 350 and sheets_ < len(pages) / 4)


def spec_checks(specs):
    """Rule checks for a spec book on its own: sections it cites that it
    doesn't contain."""
    have, cited = set(), {}
    for i, _n, _t, text in specs:
        for m in HEADING.finditer(text):
            have.add("".join(m.groups()))
    for i, num, _t, text in specs:
        for m in SECTION_REF.finditer(text):
            key = "".join(m.groups())
            if key not in have and key not in cited:
                cited[key] = (i, m.group(0))
    out = []
    if len(have) < 3:            # not enough headings to judge what's missing
        return out
    for key, (i, quote) in sorted(cited.items())[:60]:
        sec = f"{key[:2]} {key[2:4]} {key[4:]}"
        out.append(_finding(
            f"{quote} is referenced, but Section {sec} is not in the "
            "project manual. Please issue the section or confirm which "
            "section governs this work.",
            "Work tied to a missing section can't be priced or "
            "submitted on.", f"Section {sec}", quote, i, "specs"))
    return out


# ---- text, gathered on the GUI thread --------------------------------------------

def gather(doc, label="plans", pages=None):
    """[(page index, sheet number, title, text)] for the chosen pages."""
    from .. import sheets
    out = []
    for i, page in enumerate(doc):
        if pages is not None and i not in pages:
            continue
        # one text extraction per page, shared by the words and the text
        # (it was two: v36)
        try:
            tp = page.get_textpage()
        except Exception:
            tp = None
        try:
            number, title = sheets.sheet_info(sheets.page_words(page, tp),
                                              page.rect.width,
                                              page.rect.height)
        except Exception:
            number, title = "", ""
        out.append((i, number, title, page.get_text(textpage=tp)))
    return out


# ---- dependable checks ----------------------------------------------------------------

def _finding(question, reason, reference, quote, page, doc="plans"):
    """`page` is the 0-based page index (the viewer, locate(), the RFI
    log); `page_no` the 1-based page number people read (phase 2)."""
    return {"question": question, "reason": reason, "reference": reference,
            "quote": quote, "page": page, "page_no": _rules.page_no(page),
            "doc": doc, "source": "check"}


INDEX_HEAD = re.compile(r"\b(?:SHEET|DRAWING)\s+(?:INDEX|LIST)\b|"
                        r"\bINDEX\s+OF\s+(?:DRAWINGS|SHEETS)\b|"
                        r"\bLIST\s+OF\s+DRAWINGS\b", re.I)
INDEX_NUM = re.compile(r"(?m)^\s*([A-Z]{1,2}-?\d{1,3}(?:\.\d{1,2})?[A-Z]?)"
                       r"(?=\s|$)")
SPEC_DWG = re.compile(r"\b(?:drawings?|sheets?|dwgs?\.?)\s+(?:no\.?\s*)?"
                      r"([A-Z]{1,2}-?\d{1,3}(?:\.\d{1,2})?)\b", re.I)


def _index_checks(plans, sheet_nums):
    """Sheet index entries (on a cover / index sheet) with no such sheet in
    the set. Only an index most of whose entries are in the set counts."""
    found = []
    for i, num, _t, text in plans:
        if not INDEX_HEAD.search(text):
            continue
        listed = []
        for m in INDEX_NUM.finditer(text):
            n = m.group(1).upper()
            if n not in listed:
                listed.append(n)
        if len(listed) < 3:
            continue
        have = [n for n in listed if n.replace("-", "") in sheet_nums]
        if len(have) < 0.5 * len(listed):
            continue                     # not a sheet list we can trust
        for n in listed:
            if n.replace("-", "") in sheet_nums:
                continue
            found.append(_finding(
                f"The sheet index on {num or 'page ' + str(i + 1)} lists "
                f"sheet {n}, but it is not in the drawing set. Please "
                "issue the sheet or correct the index.",
                "A listed sheet that wasn't issued may hold work that has "
                "to be priced.", num or f"Page {i + 1}", n, i))
    return found


def checks(plans, specs=None):
    """Findings computable without AI. `plans` and `specs` come from
    gather()."""
    found = []
    sheet_of = {i: n for i, n, _t, _x in plans}
    sheet_nums = {n.replace("-", "").upper() for _i, n, _t, _x in plans if n}
    own = _rules.set_sheets(plans)
    sheet_prefixes = _rules.sheet_prefixes(plans)
    # 1. detail callouts to sheets that aren't in the set
    if len(sheet_nums) >= 2:
        seen = set()
        for i, num, _t, text in plans:
            for m in CALLOUT.finditer(text):
                target = m.group(2).upper()
                key = target.replace("-", "")
                if key in sheet_nums or (i, target) in seen:
                    continue
                if not re.match(r"^[A-Z]{1,2}\d", key):
                    continue
                if _rules.is_finish_code(re.match(r"[A-Z]+", key).group(0),
                                         sheet_prefixes):
                    continue             # PT-2 is a paint, not a sheet
                seen.add((i, target))
                found.append(_finding(
                    f"Detail {m.group(0)} is referenced on sheet "
                    f"{num or 'page ' + str(i + 1)}, but sheet {target} is "
                    "not in the drawing set. Please issue the sheet or "
                    "correct the reference.",
                    "A referenced detail that isn't in the set can't be "
                    "priced or built.", num or f"Page {i + 1}", m.group(0),
                    i))
    # 2. spec sections the drawings cite but the spec book doesn't have
    if specs:
        have = set()
        for _i, _n, _t, text in specs:
            for m in SECTION_HEAD.finditer(text):
                have.add("".join(m.groups()))
        if have:
            seen = set()
            for i, num, _t, text in plans:
                for m in SPEC_SEC.finditer(text):
                    sec = "".join(m.groups())
                    if sec in have or sec in seen or \
                            not _rules.spec_ref_ok(text, m, have):
                        continue         # 12 12 12, 14 13 12, no "SECTION"
                    seen.add(sec)
                    label = " ".join(m.groups())
                    near = _rules.near_section(sec, have)
                    found.append(_finding(
                        f"Sheet {num or 'page ' + str(i + 1)} refers to "
                        f"specification Section {label}, which is not in "
                        "the project manual" +
                        (f" (the nearest is {near})" if near else "") +
                        ". Please provide the section or "
                        "confirm the correct reference.",
                        "Work tied to a missing spec section has no "
                        "requirements to price against.",
                        f"Section {label}", m.group(0), i))
    # 3. equipment tags on plans but not on any schedule
    sched_text = " ".join(t for _i, _n, title, t in plans
                          if "SCHEDULE" in (title + " " + t[:4000]).upper())
    if sched_text:
        on_sched = {m.group(0) for m in EQUIP.finditer(sched_text)}
        prefixes = {m.group(1) for m in EQUIP.finditer(sched_text)}
        seen = set()
        equip_fams = set()
        for _i, _n, title, t in plans:
            if "SCHEDULE" in (title + " " + t[:4000]).upper() and \
                    _rules.EQUIP_SCHED.search(title + " " + t[:4000]):
                equip_fams |= {m.group(1) for m in EQUIP.finditer(t)}
        for i, num, title, text in plans:
            if "SCHEDULE" in (title or "").upper() or \
                    _rules.is_code_sheet(num, title):
                continue                 # code / ADA figures aren't tags
            for m in EQUIP.finditer(text):
                tag = m.group(0)
                if m.group(1) in NOT_EQUIP or m.group(1) not in prefixes:
                    continue
                if _rules.sheet_key(tag) in own or \
                        _rules.is_finish_code(m.group(1), sheet_prefixes) or \
                        (m.group(1) in _rules.FIGURE_PREFIXES and
                         m.group(1) not in equip_fams):
                    continue             # a sheet, a finish, a figure
                if re.search(r"(?:/|\bSHEETS?\s+|\bSHT\.?\s*|"
                             r"\bFIG(?:URE)?\.?\s*)$",
                             text[max(0, m.start() - 8):m.start()], re.I):
                    continue             # 5/P-201, SEE SHEET P-201
                if tag in on_sched or tag in seen:
                    continue
                seen.add(tag)
                found.append(_finding(
                    f"Equipment tag {tag} is shown on sheet "
                    f"{num or 'page ' + str(i + 1)} but does not appear in "
                    f"the {m.group(1)} schedule. Please provide its "
                    "schedule data (size, capacity, electrical).",
                    "Unscheduled equipment can't be selected or priced.",
                    num or f"Page {i + 1}", tag, i))
    # 5. (Nov 3 dead-reference finder) sheet index entries with no sheet
    found += _index_checks(plans, sheet_nums)
    # 6. spec references to drawings that aren't in the set
    if specs and len(sheet_nums) >= 2:
        seen = set()
        for i, num, _t, text in specs:
            for m in SPEC_DWG.finditer(text):
                target = m.group(1).upper()
                key = target.replace("-", "")
                if key in sheet_nums or key in seen:
                    continue
                if not any(key[:1] == k[:1] for k in sheet_nums):
                    continue             # not this set's sheet naming
                seen.add(key)
                found.append(_finding(
                    f"The specifications refer to drawing {target} "
                    f"(\"{m.group(0).strip()}\"), which is not in the drawing "
                    "set. Please issue the sheet or correct the reference.",
                    "Work described on a drawing that wasn't issued can't be "
                    "priced.", num or f"Page {i + 1}", m.group(0).strip(), i,
                    "specs"))
    # 4. open scope: TBD, by others, NIC, verify in field
    for docname, pages in (("plans", plans), ("specs", specs or [])):
        seen = set()
        for i, num, _t, text in pages:
            for line in text.splitlines():
                m = OPEN_SCOPE.search(line)
                if not m:
                    continue
                quote = line.strip()[:90]
                if quote in seen or len(quote) < 4:
                    continue
                seen.add(quote)
                word = m.group(1).upper()
                if word.startswith(("TBD", "T.B.D", "TO BE")):
                    q = (f'"{quote}" is still to be determined. Please '
                         "provide the missing information.")
                elif word.startswith(("BY OTHERS", "N", "NOT IN")):
                    q = (f'"{quote}" - please confirm who furnishes and '
                         "installs this work and whether it is in our "
                         "contract.")
                else:
                    q = (f'"{quote}" - please confirm the intended '
                         "dimension or condition so it can be priced.")
                found.append(_finding(
                    q, "Open scope or missing information affects price "
                    "and responsibility.",
                    num or f"Page {i + 1}", quote, i, docname))
    return found


# ---- the AI review -------------------------------------------------------------------

def _chunks(pages, limit):
    buf, size = [], 0
    for i, num, title, text in pages:
        head = f"[Page {i + 1}]" + (f" Sheet {num}" if num else "") + \
            (f" - {title}" if title else "")
        block = f"{head}\n{text.strip()}\n"
        if buf and size + len(block) > limit:
            yield "\n".join(buf)
            buf, size = [], 0
        buf.append(block[:limit])
        size += len(block)
    if buf:
        yield "\n".join(buf)



class Findings(list):
    """AI findings, plus .skipped: parts the AI failed on (kept going -
    review 0.12.30 N3: one bad part used to lose every finding)."""
    def __init__(self, *a):
        super().__init__(*a)
        self.skipped = []


def _ask_part(ask, prompt, n, total, out):
    try:
        return ask(prompt)
    except Exception as e:                                # noqa: BLE001
        out.skipped.append(f"AI skipped part {n + 1} of {total} ({e})")
        return None

def ai_review(plans, specs=None, ask=None, limit=None, max_chunks=12):
    """Findings from the local model. `ask(prompt) -> reply text` defaults
    to Ollama in JSON mode (tests pass a stub)."""
    ask = ask or (lambda p: review._ollama(p, json_mode=True))
    limit = limit or review.TEXT_LIMIT
    spec_digest = ""
    if specs:
        heads = []
        for _i, _n, _t, text in specs:
            for m in SECTION_HEAD.finditer(text):
                heads.append(" ".join(m.groups()))
        spec_text = "\n".join(t for _i, _n, _t, t in specs)
        spec_digest = ("\n\nSPECIFICATION SECTIONS: " +
                       ", ".join(sorted(set(heads))[:200]) +
                       "\n\nSPECIFICATIONS (excerpt):\n" +
                       spec_text[:limit // 3])
    out = Findings()
    parts = list(_chunks(plans, limit - len(spec_digest)))[:max_chunks]
    for n, chunk in enumerate(parts):
        raw = _ask_part(ask, PROMPT + "\n\nDRAWINGS:\n" + chunk +
                        spec_digest, n, len(parts), out)
        if raw is None:
            continue
        for d in review._items(raw, "items"):
            q = str(d.get("question", "")).strip()
            if not q:
                continue
            try:
                page = int(d.get("page")) - 1
            except (TypeError, ValueError):
                page = None
            out.append({"question": q[:1000],
                        "reason": str(d.get("reason", ""))[:500],
                        "reference": str(d.get("reference", ""))[:80],
                        "quote": str(d.get("quote", ""))[:200],
                        "page": page, "page_no": _rules.page_no(page),
                        "doc": "plans", "source": "AI"})
    if parts and len(out.skipped) == len(parts):
        raise RuntimeError(out.skipped[0])   # nothing came back
    return out


def ai_review_specs(specs, ask=None, limit=None, max_chunks=SPEC_CHUNKS):
    """AI findings for a spec book open on its own. Reads up to
    max_chunks x limit characters; coverage() says how much that was."""
    ask = ask or (lambda p: review._ollama(p, json_mode=True))
    limit = limit or review.TEXT_LIMIT
    out = Findings()
    parts = list(_chunks(specs, limit))[:max_chunks]
    for n, chunk in enumerate(parts):
        raw = _ask_part(ask, SPEC_PROMPT + "\n\nSPECIFICATIONS:\n" + chunk,
                        n, len(parts), out)
        if raw is None:
            continue
        for d in review._items(raw, "items"):
            q = str(d.get("question", "")).strip()
            if not q:
                continue
            try:
                page = int(d.get("page")) - 1
            except (TypeError, ValueError):
                page = None
            out.append({"question": q[:1000],
                        "reason": str(d.get("reason", ""))[:500],
                        "reference": str(d.get("reference", ""))[:80],
                        "quote": str(d.get("quote", ""))[:200],
                        "page": page, "page_no": _rules.page_no(page),
                        "doc": "specs", "source": "AI"})
    if parts and len(out.skipped) == len(parts):
        raise RuntimeError(out.skipped[0])   # nothing came back
    return out


def coverage(pages, limit=None, max_chunks=SPEC_CHUNKS):
    """(pages the AI read, total pages) for ai_review_specs."""
    limit = limit or review.TEXT_LIMIT
    read, n = 0, 0
    for chunk in _chunks(pages, limit):
        if n >= max_chunks:
            break
        read += chunk.count("[Page ")
        n += 1
    return read, len(pages)


def dedupe(findings):
    seen, out = set(), []
    for f in findings:
        key = re.sub(r"\W+", " ", f["question"].lower()).strip()[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


# ---- turning accepted findings into RFIs -----------------------------------------------

def locate(doc, f):
    """(page, rect) for a finding's quote in `doc` (op coordinates), or
    (page, None) if the quote can't be found."""
    pages = [f["page"]] if isinstance(f.get("page"), int) and \
        0 <= f["page"] < doc.page_count else []
    pages += [i for i in range(doc.page_count) if i not in pages]
    quote = (f.get("quote") or "").strip()
    for probe in (quote, quote[:40], " ".join(quote.split()[:4])):
        if len(probe) < 3:
            continue
        for i in pages:
            hits = doc[i].search_for(probe)
            if hits:
                r = hits[0]
                for h in hits[1:]:
                    if abs(h.y0 - r.y1) < 20 and len(probe) == len(quote):
                        r |= h
                return i, r
    return (pages[0] if pages else None), None
