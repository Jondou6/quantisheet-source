"""Read the measurements out of a roof measurement report the user already
has (an EagleView report or a similar PDF / text report).

Nothing is downloaded and nothing is sent anywhere: the user picks a file
on their own computer and this reads its text. Only the roof numbers are
kept (area, pitch and the edge lengths); addresses, names and anything
else in the report are ignored.

EagleView is a trademark of EagleView Technologies, Inc. QuantiSheet is
not affiliated with or endorsed by EagleView; it only reads the text of a
report the user supplies.
"""
import os
import re

# a text report larger than this is refused; a PDF is read up to MAX_PAGES
MAX_TEXT_BYTES = 50 * 1024 * 1024
MAX_PAGES = 200

TRADEMARK_NOTE = ("EagleView is a trademark of EagleView Technologies, Inc.; "
                  "QuantiSheet is not affiliated.")
GENERIC_NOTE = ("QuantiSheet is not affiliated with the maker of this "
                "report; it only reads the numbers in it.")
PASSWORD_NOTE = ("This PDF is password-protected; open it, save an "
                 "unprotected copy, then import it.")


class RoofReportError(Exception):
    """A report file that can't be read; str() is a plain message."""


# field -> label patterns (case-insensitive), checked in order
_LABELS = {
    "sloped_sf": (r"total\s+roof\s+area", r"total\s+area(?:\s*\(all\s+pitches\))?",
                  r"roof\s+area"),
    "pitch": (r"predominant\s+pitch", r"primary\s+pitch", r"main\s+pitch",
              r"pitch"),
    "ridge": (r"ridges?",),
    "hip": (r"hips?",),
    "valley": (r"valleys?",),
    "rake": (r"rakes?",),
    "eave": (r"eaves?(?:\s*/\s*starter)?",),
}
# 3,120 / 2,480.5 / 72 / 96.58; never right after a minus sign, a digit or a
# comma (so "-72" is not read as 72)
_NUM = r"(?<![\d,\-\u2212])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
# label, then only punctuation / spaces (=, :, leader dots, dashes, footnote
# marks), at most one line break, then the number. No letters, so "Hip and
# Ridge Cap = 120 ft" is not read as the hip length.
_GAP = r"[ \t=:.\-*–—†‡]{0,30}\n?[ \t=:]{0,10}"
# a label starts its line or follows a space ("Structure 1  Ridges = 72 ft"),
# but not "(Eaves", "+ Rakes", "& Ridges", "/ Hips" or "and Ridge": those are
# parts of a combined total, not the length itself
_START = (r"(?:^|(?<=[ \t]))(?<![(/+&][ \t])(?<![(/+&][ \t]{2})"
          r"(?<!\band[ \t])")
# the label is not followed by "/", "+", "&" or "and" (a combined total)
_NOT_COMBINED = r"(?!\w)(?!\s*(?:[/+&]|and\b))"
_PITCH = r"(\d{1,2}(?:\.\d+)?)\s*(?:/|:|\bin\b)\s*12\b"
_AREA_UNIT = (r"\s*(?:(sq\.?\s*ft\b\.?|square\s+f(?:ee|oo)t\b|sf\b|ft2\b|ft²)"
              r"|(squares?\b))")
_LEN_UNIT = (r"\s*(?:ft\b\.?|feet\b|foot\b|lf\b|l\.f\.|')"
             r"(?:\s*(\d+(?:\.\d+)?)\s*(?:in\b\.?|inch(?:es)?\b|\"))?")


def _num(s):
    return float(s.replace(",", ""))


def _first_value(field, p, text):
    """Value of the first acceptable match of label pattern `p`, or None."""
    if field == "pitch":
        rx = re.compile(_START + p + _NOT_COMBINED + _GAP + _PITCH,
                        re.I | re.M)
        for m in rx.finditer(text):
            return float(m.group(1))
        return None
    unit = _AREA_UNIT if field == "sloped_sf" else _LEN_UNIT
    rx = re.compile(_START + p + _NOT_COMBINED + _GAP + _NUM + unit,
                    re.I | re.M)
    for m in rx.finditer(text):
        v = _num(m.group(1))
        if field == "sloped_sf":
            if m.group(3):                      # area given in squares
                v *= 100.0
        elif m.group(2):
            inches = float(m.group(2))
            if inches > 11:                     # "72 ft 18 in" is not a size
                continue
            v += inches / 12.0
        return round(v, 2)
    return None


def parse(text):
    """{field: value} for every roof number found in `text`, plus
    'missing': [fields not found] and 'eagleview': whether the text names
    EagleView. Lengths in feet (inches added when the report gives
    "ft ... in"), area in sq ft (squares x 100), pitch in inches per 12.
    A negative number, or inches over 11, counts as not found."""
    text = (text or "").replace("†", "").replace("‡", "")
    text = text.replace(" ", " ").replace("﻿", "")
    out = {}
    for field, pats in _LABELS.items():
        for p in pats:
            v = _first_value(field, p, text)
            if v is not None:
                out[field] = v
                break
    out["missing"] = [f for f in _LABELS if f not in out]
    out["eagleview"] = bool(re.search(r"eagle\s*view", text, re.I))
    return out


def _decode(raw):
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def read_text(path):
    """(text, notes) of a PDF or text report on this computer. Raises
    RoofReportError with a plain message for a password-protected PDF or a
    text file over MAX_TEXT_BYTES; a PDF is read up to MAX_PAGES pages."""
    notes = []
    if path.lower().endswith(".pdf"):
        import fitz
        with fitz.open(path) as d:
            if d.needs_pass:
                raise RoofReportError(PASSWORD_NOTE)
            n = d.page_count
            parts = []
            for i in range(min(n, MAX_PAGES)):
                parts.append(d[i].get_text())
            if n > MAX_PAGES:
                notes.append(f"Only the first {MAX_PAGES} of {n} pages "
                             "were read.")
            return "\n".join(parts), notes
    size = os.path.getsize(path)
    if size > MAX_TEXT_BYTES:
        raise RoofReportError(
            f"That file is too large ({size / 1048576:,.0f} MB); a roof "
            f"report text file can be at most "
            f"{MAX_TEXT_BYTES // 1048576} MB. Nothing was read.")
    with open(path, "rb") as f:
        return _decode(f.read()), notes


def read_file(path):
    """Text of a PDF or text report on this computer."""
    return read_text(path)[0]


def import_file(path):
    """parse() of the report at `path`, plus 'notes': [reading notes]."""
    text, notes = read_text(path)
    got = parse(text)
    got["notes"] = notes
    return got


NAMES = {"sloped_sf": "Roof area", "pitch": "Pitch", "ridge": "Ridges",
         "hip": "Hips", "valley": "Valleys", "rake": "Rakes",
         "eave": "Eaves"}
