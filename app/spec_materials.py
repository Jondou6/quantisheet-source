"""What the specifications say a thing is made of, when the drawings don't.

A drawing labels a pipe '2" W' or a duct '12" round'. The project manual
says what that pipe or duct is: SECTION 221116 'Aboveground domestic water
piping, NPS 2 and smaller is to be the following: 1. Drawn-temper copper
tube, ASTM B88, Type L ...'; SECTION 220719's insulation schedule says
which pipes are insulated and how thick; SECTION 230713 says which ducts
are wrapped and with what. An estimator reads those to price the right
material and to take off the insulation. This module does the same, and
always says which section it read.

    Spec.from_pdf(doc) / Spec.from_pages([text, ...])
    spec.pipe_material(system, size_in, under_slab=False) -> (text, sec)
    spec.pipe_insulation(system, size_in) -> (material, thk_in, sec)
    spec.duct_material() -> (text, sec)
    spec.duct_insulation(shape="round", air="supply") -> (material, thk, sec)
    spec.section_for(title_rx) -> (number, title) | None
    spec.includes(number) -> ['PVC pipe and fittings.', ...]

Nothing here is a price. Sections are read as printed; when the text
doesn't say, the answer is None (never a guess).
"""
import re
from collections import Counter

_SECTION = re.compile(r"^\s*SECTION\s+(\d{2}\s?\d{2}\s?\d{2}(?:\.\d{1,2})?)\s*"
                      r"[-–—]\s*(.+?)\s*$", re.I)
_END = re.compile(r"^\s*END\s+OF\s+SECTION\b", re.I)
_FOOTER = re.compile(r"\b\d{6}(?:\.\d{1,2})?\s*-\s*\d{1,3}\s*$")
# paragraph markers: 1.1 article, A. paragraph, 1. sub, a. sub-sub
_MARK = re.compile(r"^\s*(?:(PART\s+\d)\s*[-–]?|(\d{1,2}\.\d{1,2})|"
                   r"([A-Z])\.|(\d{1,2})\.|([a-z])\.)(?:\s+(.*))?$")
_NPS = re.compile(r"NPS\s+(\d+(?:[- ]\d/\d)?|\d/\d)\s+(?:and\s+)?"
                  r"(smaller|larger|less|greater)", re.I)
_THK = re.compile(r"(\d+(?:\.\d+)?(?:[- ]\d/\d)?|\d/\d)\s*(?:inch(?:es)?|in\.?|\")"
                  r"\s+thick", re.I)

PIPE_SYSTEMS = {
    "CW": "domestic cold water", "DCW": "domestic cold water",
    "HW": "domestic hot", "DHW": "domestic hot", "HWR": "domestic hot",
    "HWC": "domestic hot", "W": "sanitary waste", "V": "vent",
    "SAN": "sanitary waste", "VTR": "vent", "G": "gas", "ST": "storm",
    "RL": "storm", "CD": "condensate", "RS": "refrigerant",
}


def _num(sec):
    return re.sub(r"\s", "", sec)


def _inch(t):
    t = t.strip()
    m = re.match(r"^(\d+)[- ](\d)/(\d)$", t)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.match(r"^(\d)/(\d)$", t)
    if m:
        return int(m.group(1)) / int(m.group(2))
    return float(t)


class Para:
    __slots__ = ("level", "mark", "text", "kids")

    def __init__(self, level, mark, text):
        self.level, self.mark, self.text, self.kids = level, mark, text, []

    def all(self):
        yield self
        for k in self.kids:
            yield from k.all()

    def __repr__(self):
        return f"Para({self.level}, {self.mark!r}, {self.text[:40]!r})"


class Spec:
    def __init__(self, sections):
        # {number: {"title", "paras": [Para] (tree roots), "text"}}
        self.sections = sections
        self.raw = ""

    # ---------------------------------------------------------- reading
    @classmethod
    def from_pdf(cls, doc, max_pages=3000):
        pages = []
        for i in range(min(doc.page_count, max_pages)):
            try:
                pages.append(doc[i].get_text("text", sort=True))
            except Exception:                             # noqa: BLE001
                pages.append("")
        return cls.from_pages(pages)

    @classmethod
    def from_pages(cls, pages):
        # lines printed on many pages are the running header / footer
        seen = Counter()
        for p in pages:
            for ln in {re.sub(r"\s+", " ", x).strip() for x in
                       p.splitlines()}:
                if ln:
                    seen[ln] += 1
        n = max(1, len(pages))
        running = {ln for ln, k in seen.items()
                   if k >= max(5, 0.2 * n) and not _SECTION.match(ln)
                   and not _MARK.match(ln)}
        sections, cur = {}, None
        for p in pages:
            for raw in p.splitlines():
                ln = re.sub(r"\s+", " ", raw).strip()
                if not ln or ln in running or _FOOTER.search(ln):
                    continue
                m = _SECTION.match(ln)
                if m:
                    cur = {"title": m.group(2).strip().upper(),
                           "lines": []}
                    sections[_num(m.group(1))] = cur
                    continue
                if _END.match(ln):
                    cur = None
                    continue
                if cur is not None:
                    cur["lines"].append(ln)
        for s in sections.values():
            s["paras"] = _tree(s.pop("lines"))
            s["text"] = " ".join(p.text for r in s["paras"] for p in r.all())
        sp = cls(sections)
        sp.raw = re.sub(r"\s+", " ", " ".join(pages))
        return sp

    # ---------------------------------------------------------- lookups
    def section_for(self, title_rx):
        rx = re.compile(title_rx, re.I)
        for num in sorted(self.sections):
            if rx.search(self.sections[num]["title"]):
                return num, self.sections[num]["title"]
        return None

    def includes(self, num):
        """The 'Section Includes:' list of a section."""
        s = self.sections.get(num)
        if not s:
            return []
        for p in (q for r in s["paras"] for q in r.all()):
            if re.match(r"^Section Includes\s*:", p.text, re.I):
                return [k.text for k in p.kids]
        return []

    def _schedule(self, num, article_rx):
        """The paragraphs under an article ('PIPING APPLICATIONS',
        'INDOOR PIPING INSULATION SCHEDULE')."""
        s = self.sections.get(num)
        if not s:
            return []
        rx = re.compile(article_rx, re.I)
        out = []
        for r in s["paras"]:
            for p in r.all():
                if p.level <= 1 and rx.search(p.text):
                    out += p.kids
        return out

    def pipe_material(self, system, size_in=None, under_slab=False):
        """(material text, section) for a pipe system code ('CW', 'W')."""
        what = PIPE_SYSTEMS.get((system or "").upper(), "")
        if not what:
            return None
        if "domestic" in what:
            found = self.section_for(r"DOMESTIC\s+WATER\s+PIPING$")
        elif what in ("sanitary waste", "vent"):
            found = self.section_for(r"SANITARY\s+WASTE\s+AND\s+VENT\s+PIPING$")
        elif what == "storm":
            found = self.section_for(r"STORM\s+DRAINAGE\s+PIPING$")
        elif what == "gas":
            found = self.section_for(r"FUEL\s+GAS\s+PIPING$")
        elif what == "refrigerant":
            found = self.section_for(r"REFRIGERANT\s+PIPING$")
        elif what == "condensate":
            found = self.section_for(r"HYDRONIC\s+PIPING$|CONDENSATE")
        else:
            found = None
        if not found:
            return None
        num = found[0]
        best = None
        for p in self._schedule(num, r"PIPING\s+(?:APPLICATIONS|SCHEDULE)"):
            t = p.text
            if not re.search(r"following\s*:?\s*$|:\s*$", t) or not p.kids:
                continue
            slab = bool(re.search(r"under[- ]?(?:building[- ]?)?slab|"
                                  r"underground|below\s+grade", t, re.I))
            if slab != bool(under_slab):
                continue
            if "domestic" in what and re.search(r"building[- ]service",
                                                t, re.I):
                continue
            if what == "vent" and re.search(r"\bwaste\b", t, re.I) and \
                    not re.search(r"\bvent\b", t, re.I):
                continue
            if size_in is not None and not _size_ok(t, size_in):
                continue
            best = p
            break
        if best is not None:
            return _first_clause(best.kids[0].text), num
        # no applications article: what the section is about
        inc = [x for x in self.includes(num) if re.search(
            r"\bpipe|\btube|\btubing", x, re.I)]
        if inc:
            return inc[0].rstrip("."), num
        return None

    def pipe_insulation(self, system, size_in=None):
        """(material, thickness in, section) for an insulated system, or
        None when the schedule doesn't insulate it."""
        what = PIPE_SYSTEMS.get((system or "").upper(), "")
        if not what:
            return None
        found = self.section_for(r"PLUMBING\s+PIPING\s+INSULATION$") if \
            what.startswith("domestic") or what in ("sanitary waste", "vent",
                                                    "storm") else \
            self.section_for(r"HVAC\s+PIPING\s+INSULATION$")
        if not found:
            return None
        num = found[0]
        key = {"domestic cold water": r"domestic\s+cold\s+water",
               "domestic hot": r"domestic\s+hot",
               "storm": r"storm|roof\s+drain",
               "condensate": r"condensate",
               "refrigerant": r"refrigerant"}.get(what)
        if not key:
            return None
        for p in self._schedule(num, r"INDOOR\s+PIPING\s+INSULATION\s+"
                                     r"SCHEDULE"):
            if not re.search(key, p.text, re.I):
                continue
            opts = p.kids or [p]
            for o in opts:
                if size_in is not None and _NPS.search(o.text) and \
                        not _size_ok(o.text, size_in):
                    continue
                leaf = o.kids[0] if o.kids else o
                m = _THK.search(leaf.text)
                if not m:
                    continue
                mat = leaf.text.split(":")[0].strip().rstrip(",")
                return mat, _inch(m.group(1)), num
        return None

    def duct_material(self):
        found = self.section_for(r"^METAL\s+DUCTS$")
        if not found:
            return None
        num = found[0]
        for p in self._schedule(num, r"DUCT\s+SCHEDULE"):
            m = re.search(r"(galvanized\s+sheet\s+steel|stainless[- ]steel|"
                          r"aluminum|black\s+steel)", p.text, re.I)
            if m:
                return m.group(1).lower(), num
        txt = self.sections[num]["text"]
        m = re.search(r"galvanized\s+(?:sheet\s+)?steel", txt, re.I)
        return (m.group(0).lower(), num) if m else None

    def duct_insulation(self, shape="round", air="supply"):
        """(material, thickness in, section) for concealed duct of this
        shape and air stream, or None when not insulated / not said."""
        found = self.section_for(r"^DUCT\s+INSULATION$")
        if not found:
            return None
        num = found[0]
        shape_rx = r"round" if shape == "round" else r"rectangular"
        for p in self._schedule(num, r"INDOOR\s+DUCT\s+AND\s+PLENUM\s+"
                                     r"INSULATION\s+SCHEDULE"):
            t = p.text
            if not (re.search(shape_rx, t, re.I) and
                    re.search(air, t, re.I) and
                    re.search(r"concealed", t, re.I)):
                continue
            leaf = p.kids[0] if p.kids else p
            m = _THK.search(leaf.text)
            if m:
                return (leaf.text.split(":")[0].strip(), _inch(m.group(1)),
                        num)
        return None


def _first_clause(t):
    return re.split(r";", t)[0].strip().rstrip(".")


def _size_ok(text, size_in):
    m = _NPS.search(text)
    if not m:
        return True
    lim = _inch(m.group(1))
    small = m.group(2).lower() in ("smaller", "less")
    return size_in <= lim + 1e-6 if small else size_in >= lim - 1e-6


def _tree(lines):
    """Lines of one section -> paragraph tree (PART / 1.1 / A. / 1. / a.);
    a line with no marker continues the paragraph before it."""
    roots, stack = [], []
    order = {"part": 0, "art": 1, "A": 2, "1": 3, "a": 4}
    for ln in lines:
        m = _MARK.match(ln)
        if m:
            kind = "part" if m.group(1) else "art" if m.group(2) else \
                "A" if m.group(3) else "1" if m.group(4) else "a"
            lv = order[kind]
            p = Para(lv, (m.group(1) or m.group(2) or m.group(3) or
                          m.group(4) or m.group(5)), (m.group(6) or "").strip())
            while stack and stack[-1].level >= lv:
                stack.pop()
            (stack[-1].kids if stack else roots).append(p)
            stack.append(p)
        elif stack:
            stack[-1].text += " " + ln
        else:
            roots.append(Para(1, "", ln))
            stack.append(roots[-1])
    return roots


# ------------------------------------------------------------- trenches
_COVER = [
    re.compile(r"(\d{2})-inch\s+minimum\s+cover", re.I),
    re.compile(r"minimum\s+cover\s+of\s+(\d{2})\s+inches", re.I),
    re.compile(r"at\s+least\s+(\d{2})\s+inches\s+of\s+cover", re.I),
    re.compile(r"minimum\s+of\s+(\d)\s+feet\s+of\s+cover", re.I),
]
_CLEAR = re.compile(r"Clearance\s*:\s*(\d{1,2})\s+inches\s+each\s+side",
                    re.I)
_BED = re.compile(r"Excavate\s+trenches\s+(\d{1,2})\s+inches\s+deeper\s+"
                  r"than\s+bottom\s+of\s+pipe", re.I)
_MINW = re.compile(r"minimum\s+trench\s+width\s+(?:should\s+generally\s+be|"
                   r"(?:shall|is)\s+(?:be\s+)?)?\s*(?:no\s+less\s+than\s+)?"
                   r"(\d{2})\s+inches", re.I)
_SYS_TITLE = {"sanitary": r"SANITARY\s+SEWER", "storm": r"STORM",
              "water": r"WATER\s+(?:DISTRIBUTION|SERVICE|UTILIT|MAIN)|"
                       r"FACILITY\s+WATER"}


def _feet_or_in(m, rx):
    v = int(m.group(1))
    return v * 12 if "feet" in rx.pattern else v


def _trench_rules(self, system):
    """{"cover_in", "clear_in", "bed_in", "min_w_in", "src": [sections]}
    from the earth moving section and the utility's own section, each
    None when the project manual doesn't say."""
    out = {"cover_in": None, "clear_in": None, "bed_in": None,
           "min_w_in": None, "src": []}
    em = self.section_for(r"^EARTH\s+MOVING$|^TRENCHING|EXCAVATION\s+AND\s+"
                          r"FILL")
    if em:
        t = self.sections[em[0]]["text"]
        m = _CLEAR.search(t)
        if m:
            out["clear_in"] = int(m.group(1))
        m = _BED.search(t)
        if m:
            out["bed_in"] = int(m.group(1))
        out["src"].append(em[0])
    rx = _SYS_TITLE.get(system)
    sec = self.section_for(rx) if rx else None
    texts = [(sec[0], self.sections[sec[0]]["text"])] if sec else []
    if system == "water":
        # city water standards are often appended without SECTION heads:
        # read the whole manual for the service cover rule
        texts.append(("project manual", self.raw))
    for src, t in texts:
        if out["cover_in"] is None:
            for crx in _COVER:
                m = crx.search(t) if system != "water" else re.search(
                    crx.pattern + r".{0,60}water|water.{0,80}" +
                    crx.pattern, t, re.I | re.S)
                if m:
                    g = next(x for x in m.groups() if x)
                    out["cover_in"] = int(g) * (12 if "feet" in crx.pattern
                                                else 1)
                    out["src"].append(src)
                    break
        if out["min_w_in"] is None:
            m = _MINW.search(t)
            if m:
                out["min_w_in"] = int(m.group(1))
    return out


Spec.trench_rules = _trench_rules


def _shade_locations(self):
    """('At exterior windows', section) when the window shade section says
    where shades go, else None."""
    found = self.section_for(r"WINDOW\s+SHADES|ROLLER\s+SHADES|"
                             r"WINDOW\s+TREATMENTS?|HORIZONTAL\s+LOUVER\s+"
                             r"BLINDS")
    if not found:
        return None
    t = self.sections[found[0]]["text"]
    m = re.search(r"(?:Roller\s+)?Shade\s+Locations?\s*:\s*([^.]{3,80})",
                  t, re.I)
    if not m:
        return None
    return m.group(1).strip(), found[0]


Spec.shade_locations = _shade_locations
