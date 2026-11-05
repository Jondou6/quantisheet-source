"""Company file-name rule for saved reports (Jon, Oct 23 2026):

    2026.10.23 Project Name PPR Report 001.pdf

The date always comes first (yyyy.mm.dd, so files sort by date in any
folder - a legal record and an organizer), then the project name, then
the report kind, then the 3-digit report number when there is one.
Characters Windows can't put in a file name are replaced with "-".
"""
import re
from datetime import date, datetime

_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def stamp(d=None):
    """'2026.10.23' for `d` (a date, datetime or ISO text); today if None
    or unreadable."""
    return (_as_date(d) or date.today()).strftime("%Y.%m.%d")


def clean(s):
    s = _BAD.sub("-", str(s or ""))
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return s


def report_file_name(kind, project="", number=None, when=None, ext=".pdf"):
    """'<yyyy.mm.dd> <Project> <kind> <###><ext>'. `number` is padded to 3
    digits when it's a whole number; text numbers are kept as typed."""
    parts = [stamp(when)]
    p = clean(project)
    if p:
        parts.append(p)
    parts.append(clean(kind) or "Report")
    if number not in (None, ""):
        try:
            parts.append(f"{int(str(number).strip()):03d}")
        except ValueError:
            parts.append(clean(number))
    name = " ".join(parts)
    if len(name) > 150:                      # keep the full path well under 260
        name = name[:150].rstrip()
    return name + (ext or "")
