"""Select and copy a drawing's text (Nov 3, Jon: "i need to be able to copy
text if I open a pdf").

Drag from a word to a word and everything between them in reading order
is selected, the way a PDF reader does it; a drag that starts off the
text selects the words inside the box instead (handy for a schedule or a
general-notes block on a busy sheet). Coordinates are the page's own
(unrotated) ones, as text extraction gives them. No Qt here."""
import fitz

NEAR = 6.0                  # points: a press this close to a word starts on it


def words(page):
    """The page's words in reading order: (x0, y0, x1, y1, text, block,
    line, n)."""
    try:
        w = page.get_text("words", sort=False)
    except Exception:                                     # noqa: BLE001
        return []
    return sorted(w, key=lambda t: (t[5], t[6], t[7]))


def _dist(w, p):
    dx = max(w[0] - p.x, 0, p.x - w[2])
    dy = max(w[1] - p.y, 0, p.y - w[3])
    return (dx * dx + dy * dy) ** 0.5


def word_at(ws, p, near=NEAR):
    """Index of the word under (or within `near` of) point p, or None."""
    best, bd = None, near
    for i, w in enumerate(ws):
        d = _dist(w, p)
        if d <= bd:
            best, bd = i, d
            if d == 0:
                break
    return best


def nearest(ws, p):
    best, bd = None, float("inf")
    for i, w in enumerate(ws):
        d = _dist(w, p)
        if d < bd:
            best, bd = i, d
    return best


def pick(ws, a, b, start=None):
    """Indexes of the words selected by a drag from a to b. `start` is
    the word the drag began on (word_at(a)); None = box mode."""
    if not ws:
        return []
    if start is None:
        r = fitz.Rect(a, b).normalize()
        return [i for i, w in enumerate(ws)
                if fitz.Rect(w[:4]).intersects(r)]
    end = nearest(ws, b)
    lo, hi = sorted((start, end))
    return list(range(lo, hi + 1))


def word_and_line(ws, i, line=False):
    """The word i (double-click) or its whole line (triple-click)."""
    if not line:
        return [i]
    k = ws[i][5:7]
    return [j for j, w in enumerate(ws) if w[5:7] == k]


def text_of(ws, idx):
    """The selected words as text: spaces between words, a line break
    between lines, a blank line between blocks."""
    out, prev = [], None
    for i in sorted(set(idx)):
        w = ws[i]
        if prev is not None:
            if w[5] != prev[5]:
                out.append("\n")
            elif w[6] != prev[6]:
                out.append("\n")
            else:
                out.append(" ")
        out.append(w[4])
        prev = w
    return "".join(out)


def rects(ws, idx):
    """One box per selected run on a line (for painting the selection)."""
    lines = {}
    for i in sorted(set(idx)):
        w = ws[i]
        r = fitz.Rect(w[:4])
        k = (w[5], w[6])
        lines[k] = lines[k] | r if k in lines else r
    return list(lines.values())


def table(ws, idx):
    """The selected words as a table (rows of cells), for a schedule:
    words on the same level are a row; words close together are one
    cell; cells are lined up in columns by where they sit across the
    sheet. Returns [[cell, ...], ...]."""
    sel = [ws[i] for i in sorted(set(idx))]
    if not sel:
        return []
    hs = sorted(w[3] - w[1] for w in sel)
    h = max(hs[len(hs) // 2], 1.0)
    # rows: by the middle of each word, top to bottom
    rows = []
    for w in sorted(sel, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        mid = (w[1] + w[3]) / 2
        if rows and abs(rows[-1]["mid"] - mid) <= h * 0.5:
            rows[-1]["w"].append(w)
        else:
            rows.append({"mid": mid, "w": [w]})
    # cells: words closer than about one letter height
    cells = []
    for r in rows:
        line = []
        for w in sorted(r["w"], key=lambda w: w[0]):
            if line and w[0] - line[-1]["x1"] <= h * 0.9:
                c = line[-1]
                c["t"] += " " + w[4]
                c["x1"] = max(c["x1"], w[2])
            else:
                line.append({"x0": w[0], "x1": w[2], "t": w[4]})
        cells.append(line)
    # columns: the cells' spans across the sheet, merged where they overlap
    spans = sorted((c["x0"], c["x1"]) for line in cells for c in line)
    cols = []
    for a, b in spans:
        if cols and a <= cols[-1][1] + h * 0.3:
            cols[-1][1] = max(cols[-1][1], b)
        else:
            cols.append([a, b])
    out = []
    for line in cells:
        row = [""] * len(cols)
        for c in line:
            mid = (c["x0"] + c["x1"]) / 2
            k = next((i for i, (a, b) in enumerate(cols) if a <= mid <= b),
                     0)
            row[k] = (row[k] + " " + c["t"]).strip()
        out.append(row)
    return out


def table_text(rows):
    """Tab between cells, a line per row: pastes into Excel cell by cell."""
    return "\n".join("\t".join(r) for r in rows)
