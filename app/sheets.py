"""Auto Bookmark: read each drawing sheet's number and title from its title
block (e.g. "A-102  DIMENSION FLOOR PLAN") to bookmark and name pages.

Works from the page's words, so it needs real text (CAD-made PDFs, or
scans after OCR)."""
import re

SHEET_NO = re.compile(r"^[A-Z]{1,3}[-.]?\d{1,3}(?:\.\d{1,2})?[A-Z]?$")
_NOISE = re.compile(r"[\\/:]|\.(dwg|rvt|dxf|pdf)$|^(AM|PM)$", re.I)
TITLE_LABELS = ("TITLE:", "TITLE")
_TAIL = re.compile(r"\s*-?\s*(?:SHT\.?|SHEET)?\s*\d*\s*OF\s*\d*\s*$", re.I)
# the usual discipline letters (US National CAD Standard), with a number:
# A-101, P1.02, FP-2, M-501A
DISCIPLINE = re.compile(
    r"^(?:G|GI|H|V|B|C|CD|CG|CS|CU|L|LP|S|A|AD|AE|I|ID|Q|F|FP|FA|P|PL|D|M|"
    r"MH|MP|E|EP|EL|ES|T|TN|R|X|Z|O|W|CV|SW|SS|WS|"
    # standard-detail sheets: MD2, SD3, HD1, ED4 (Hazen sets) - open item
    r"[ABCDEGHILMNPRSTVWZ]D)[-.]?\d{1,3}"
    r"(?:\.\d{1,2})?[A-Z]?$")
_LABEL_WORDS = ("SHEET", "SHT", "SHT.", "DWG", "DWG.", "DRAWING", "NO.",
                "NUMBER")
# trailing drafter / checker initials on a title ("COVER LRK CJB")
_KEEP_SHORT = {"MCC", "PLC", "VFD", "RTU", "AHU", "FCU", "UPS", "ATS",
               "MDP", "WWTF", "WTP", "WWTP", "PS", "HVAC", "SCADA", "BMP",
               "MEP", "RCP", "SWPPP", "TBD", "NTS"}


def _strip_initials(title):
    toks = title.split()
    while len(toks) > 1:
        t = toks[-1].strip(".,")
        if (2 <= len(t) <= 3 and t.isalpha() and t.isupper() and
                not re.search(r"[AEIOU]", t) and t not in _KEEP_SHORT):
            toks.pop()
        else:
            break
    return " ".join(toks)


def sheet_info(words, width, height, skip=()):
    """(sheet number, title) from words [(x0, y0, x1, y1, text), ...] of a
    page `width` x `height`; either may be ''. Codes in `skip` (ones that
    repeat on many sheets, like a project number) are never the number."""
    def h(w):
        return w[3] - w[1]
    # sheet number: a discipline-style code, biggest, in the title block
    # corner (bottom right) - not detail callouts elsewhere on the sheet
    cands = [w for w in words if SHEET_NO.match(w[4]) and w[4] not in skip]
    labels = [w for w in words if w[4].upper() in _LABEL_WORDS]

    def labelled(w):
        # a "SHEET" / "DWG NO." label just above or to the left
        lh = max(h(w), 1)
        return any(-lh * 4 < w[1] - lab[1] < lh * 4 and
                   -lh * 2 < w[0] - lab[0] < lh * 14 and lab is not w
                   for lab in labels)

    def score(w):
        corner = w[0] > width * 0.82 and w[1] > height * 0.8
        right = w[0] > width * 0.82
        return (bool(DISCIPLINE.match(w[4])), corner, right, labelled(w),
                h(w))
    number = ""
    if cands:
        best = max(cands, key=score)
        sc = score(best)
        if sc[1] or sc[2] or (sc[0] and sc[3]) or len(set(
                w[4] for w in cands)) == 1:
            number = best[4]
    # title: the larger words after a "SHEET TITLE:" / "DRAWING TITLE:" label
    title = ""
    labels = [w for w in words if w[4].upper() in TITLE_LABELS
              and w[0] > width * 0.7]
    for lab in sorted(labels, key=lambda w: -w[1]):
        lh = h(lab)
        x0, x1 = lab[0] - 60, lab[0] + 200
        # stop at the next label row below (SCALE / DRAWING NO.)
        stops = [w[1] for w in words if w[1] > lab[1] + lh * 0.8
                 and x0 <= w[0] <= x1 and w[4].upper().rstrip(":.") in
                 ("SCALE", "DRAWING")]
        bottom = min(stops) - 3 if stops else lab[1] + lh * 10
        near = [w for w in words
                if lab[1] - lh * 0.5 <= w[1] < bottom
                and x0 <= w[0] <= x1
                and h(w) >= lh * 1.3 and not _NOISE.search(w[4])
                and w[4] != number and w is not lab]
        if not near:
            continue
        # title lines share one text height; vertical plot stamps (file
        # paths, times) along the edge don't
        heights = {}
        for w in near:                      # weight by how wide the text is
            heights[round(h(w))] = heights.get(round(h(w)), 0) + (w[2] - w[0])
        main = max(heights, key=lambda k: (heights[k], k))
        near = [w for w in near if abs(h(w) - main) <= main * 0.08]
        near.sort(key=lambda w: (round(w[1] / (main * 0.6)), w[0]))
        title = " ".join(w[4] for w in near)
        title = _TAIL.sub("", title).strip(" -,")
        title = _strip_initials(title)
        if title:
            break
    if not title and number:
        title = _title_beside_number(words, best, width)
    return number, title.strip()


def _title_beside_number(words, num, width):
    """Title blocks with no "TITLE" label (Hazen: the title is printed in
    the sheet number's lettering, just left of "DRAWING NUMBER:" and above
    the number): the words in that lettering in the block to the left of
    and above the number."""
    nh = num[3] - num[1]
    if nh <= 0:
        return ""
    near = [w for w in words if w is not num
            and abs((w[3] - w[1]) - nh) <= nh * 0.08
            and num[0] - width * 0.2 <= w[0] < num[0]
            and num[1] - nh * 6 <= w[1] <= num[1] + nh * 0.5
            and not _NOISE.search(w[4]) and not SHEET_NO.match(w[4])]
    if not near:
        return ""
    near.sort(key=lambda w: (round(w[1] / (nh * 0.6)), w[0]))
    title = " ".join(w[4] for w in near)
    title = _TAIL.sub("", title).strip(" -,")
    return _strip_initials(title)


# title-block labels the title is printed after (Oct 31: public bid sets
# print "DRAWING:" with the title sideways beside it, or "SHEET NAME" with
# the title on the lines under it)
_LINE_LABEL = re.compile(r"^(?:SHEET\s+(?:NAME|TITLE)|DRAWING\s+(?:TITLE|NAME)|"
                         r"DRAWING|TITLE)\s*:?$", re.I)
_STOP_LABEL = re.compile(r"^(?:SHEET(?:\s+(?:NO\.?|NUMBER))?|SCALE|DATE|"
                         r"PROJECT(?:\s+(?:NO\.?|NUMBER|NAME))?|DRAWN|"
                         r"CHECKED|ISSUE|JOB(?:\s+NO\.?)?|DRAWING\s+NO\.?)"
                         r"\s*:?$", re.I)


def title_from_lines(page, number=""):
    """The sheet title from a title block whose text lines sideways or
    under a label: a "DRAWING:" / "SHEET NAME" / "SHEET TITLE" label in
    the right-hand strip or bottom band, then the bigger lines that follow
    it in the label's own reading direction (bottom-to-top text included),
    up to the next label. '' when there is no such label or nothing bigger
    after it - never a guess."""
    import fitz
    W, H = page.rect.width, page.rect.height
    m = page.rotation_matrix
    rot = fitz.Matrix(m.a, m.b, m.c, m.d, 0, 0)
    lines = []
    try:
        d = page.get_text("dict")
    except Exception:                                    # noqa: BLE001
        return ""
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            t = " ".join(sp.get("text", "") for sp in ln.get("spans", []))
            t = " ".join(t.split())
            if not t:
                continue
            r = (fitz.Rect(ln["bbox"]) * m).normalize()
            if not (r.x0 > W * 0.8 or r.y0 > H * 0.8):
                continue
            dv = fitz.Point(ln.get("dir", (1, 0))) * rot
            dv = (round(dv.x), round(dv.y))
            size = max(sp.get("size", 0) for sp in ln.get("spans", []))
            # into the line's reading frame: x along the text, y down
            if dv == (0, -1):
                fr = (-r.y1, r.x0, -r.y0, r.x1)
            elif dv == (0, 1):
                fr = (r.y0, -r.x1, r.y1, -r.x0)
            elif dv == (-1, 0):
                fr = (-r.x1, -r.y1, -r.x0, -r.y0)
            else:
                fr = (r.x0, r.y0, r.x1, r.y1)
            lines.append((fr, dv, size, t))
    for lab in sorted((x for x in lines if _LINE_LABEL.match(x[3])),
                      key=lambda x: -x[2]):
        (lx0, ly0, _lx1, ly1), dv, lsize, _ = lab
        after = [x for x in lines if x is not lab and x[1] == dv and
                 x[0][1] >= ly0 + lsize * 0.5 and
                 x[0][1] <= ly1 + lsize * 12 and
                 lx0 - lsize * 2 <= x[0][0] <= lx0 + lsize * 25]
        after.sort(key=lambda x: x[0][1])
        out, main = [], None
        for x in after:
            if _STOP_LABEL.match(x[3]) or _LINE_LABEL.match(x[3]):
                break
            if x[2] < lsize * 1.3 or x[3] == number or \
                    SHEET_NO.match(x[3]) or _NOISE.search(x[3]):
                if out:
                    break
                continue
            if main is None:
                main = x[2]
            elif abs(x[2] - main) > main * 0.08:
                break
            if out and x[0][1] - out[-1][0][3] > main * 1.2:
                break
            out.append(x)
        title = " ".join(x[3] for x in out)
        title = _TAIL.sub("", title).strip(" -,")
        title = _strip_initials(title) if title else ""
        if title:
            return title
    return ""


def fix_numbers(rows, doc=None):
    """Across a set: a code read as the number on more than 30% of the
    sheets (a project or job number, like "ACC778") isn't a sheet number.
    Re-read those sheets without it. rows are scan() rows with "words"."""
    from collections import Counter
    n = len(rows)
    skip = set()
    for _ in range(3):
        counts = Counter(r["number"] for r in rows if r["number"])
        # a real-looking sheet number (A-101) is only dropped when it is on
        # nearly every sheet; a set with a few duplicates keeps it (3b C6)
        bad = {k for k, c in counts.items() if c > 1 and c > 0.3 * n and
               (not DISCIPLINE.match(k) or c >= max(3, 0.9 * n))}
        if not bad - skip:
            break
        skip |= bad
        for r in rows:
            if r["number"] in skip or not r["number"]:
                if r.get("words") is None or doc is None:
                    r["number"] = "" if r["number"] in skip else r["number"]
                    continue
                pg = doc[r["page"]]
                num, title = sheet_info(r["words"], pg.rect.width,
                                        pg.rect.height, skip)
                r["number"] = num
                r["title"] = r["title"] or title
                r["label"] = " - ".join(x for x in (num, r["title"]) if x)
    return rows


def page_words(page, textpage=None):
    """fitz page -> words in the format sheet_info() takes, in the page's
    displayed (rotated) coordinates, so "bottom right" means what you see.
    Text extraction itself returns unrotated coordinates."""
    import fitz
    words = page.get_text("words", textpage=textpage)
    if not page.rotation:
        return [w[:5] for w in words]
    m = page.rotation_matrix
    out = []
    for w in words:
        r = (fitz.Rect(w[:4]) * m).normalize()
        out.append((r.x0, r.y0, r.x1, r.y1, w[4]))
    return out


def label_for(page):
    """'A-102 - DIMENSION FLOOR PLAN', or '' if nothing is found."""
    number, title = sheet_info(page_words(page), page.rect.width,
                               page.rect.height)
    return " - ".join(x for x in (number, title) if x)


def page_lines(page, textpage=None):
    """The page's text one printed line per string (spans joined), so a
    number at the end of one line can't run into the next."""
    out = []
    try:
        d = page.get_text("dict", textpage=textpage)
    except Exception:
        return [page.get_text(textpage=textpage)]
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            t = " ".join(sp.get("text", "") for sp in ln.get("spans", []))
            if t.strip():
                out.append(t.strip())
    return out


def scan(doc, pages=None, numbers=True, keep_words=False, textpages=None):
    """For each page: {page, number, title, label, scale, scales, odd}
    where scale is the sheet's main scale (label, points per unit, unit)
    or None, scales every scale written on it, and odd a scale that was
    read but isn't a standard drawing scale (never applied on its own -
    the user has to pick it).

    With `numbers`, sheet numbers are checked across the whole set
    (fix_numbers)."""
    from . import takeoff
    out = []
    for i in (pages if pages is not None else range(doc.page_count)):
        tp = (textpages or {}).get(i)        # text already read (Auto Scale)
        # a text page belongs to the page object it was read from
        page = getattr(tp, "parent", None) if tp is not None else None
        if page is None:
            page, tp = doc[i], None
        words = page_words(page, textpage=tp)
        number, title = sheet_info(words, page.rect.width, page.rect.height)
        if not title:
            title = title_from_lines(page, number)
        text = "\n".join(page_lines(page, textpage=tp))
        main = takeoff.main_scale(text)
        odd = None
        if main and not takeoff.is_standard(main[1], main[2]):
            odd, main = main, None
        out.append({"page": i, "number": number, "title": title,
                    "label": " - ".join(x for x in (number, title) if x),
                    "scale": main, "odd": odd,
                    "scales": takeoff.find_scales(text), "words": words})
    if numbers and len(out) > 2:
        fix_numbers(out, doc)
    if not keep_words:
        for r in out:
            r.pop("words", None)
    return out


def apply_bookmarks(doc, labels, replace=False, parent="Sheets"):
    """Bookmark each page {index: label}. Keeps existing bookmarks unless
    `replace`; puts the sheets under one `parent` bookmark."""
    toc = [] if replace else doc.get_toc()
    entries = [[2 if parent else 1, lab, i + 1]
               for i, lab in sorted(labels.items()) if lab]
    if not entries:
        return 0
    if parent:
        entries.insert(0, [1, parent, entries[0][2]])
    # drop the old copy of the sheet list (its children) when re-run
    cleaned, skip = [], False
    for e in toc:
        if e[0] == 1:
            skip = bool(parent) and e[1] == parent
        if not skip:
            cleaned.append(e)
    doc.set_toc(entries + cleaned)
    return len(entries) - (1 if parent else 0)
