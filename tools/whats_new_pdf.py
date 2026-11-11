"""Write the tester folder's "What's New" PDF from the release notes.

    python tools/whats_new_pdf.py [VERSION]

Reads docs/TEAM_NOTES_<version>.txt (default: the program's version) and
writes release/QuantiSheet <version> - Whats New.pdf. Nothing is sent.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def build(version=None, out=None):
    import fitz
    from app import __version__
    v = version or __version__
    src = os.path.join(ROOT, "docs", f"TEAM_NOTES_{v}.txt")
    text = open(src, encoding="utf-8").read().strip().splitlines()
    out = out or os.path.join(ROOT, "release",
                              f"QuantiSheet {v} - Whats New.pdf")
    W, H, M = 612, 792, 54
    font = fitz.Font("helv")
    bold = fitz.Font("hebo")
    doc = fitz.open()
    state = {"page": None, "y": 0.0}

    def new_page():
        state["page"] = doc.new_page(width=W, height=H)
        state["y"] = M

    def wrap(s, size, width):
        lines, cur = [], ""
        for word in s.split():
            t = (cur + " " + word).strip()
            if font.text_length(t, size) <= width or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = word
        return lines + ([cur] if cur else [])

    def put(s, size=10.5, indent=0, is_bold=False, gap=4, bullet=False):
        lines = wrap(s, size, W - 2 * M - indent)
        need = len(lines) * size * 1.35 + gap
        if state["y"] + min(need, 3 * size * 1.35) > H - M:
            new_page()
        for i, ln in enumerate(lines):
            if state["y"] + size * 1.35 > H - M:
                new_page()
            if bullet and i == 0:
                state["page"].insert_text((M, state["y"] + size), "-",
                                          fontsize=size, fontname="helv")
            state["page"].insert_text(
                (M + indent, state["y"] + size), ln, fontsize=size,
                fontname="hebo" if is_bold else "helv")
            state["y"] += size * 1.35
        state["y"] += gap

    new_page()
    put(text[0], 18, is_bold=True, gap=4)
    put("What's new in this version", 11, gap=12)
    for ln in text[1:]:
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("- "):
            head, sep, rest = ln[2:].partition(": ")
            if sep and len(head) < 60:
                put(head, 11, indent=12, is_bold=True, gap=1, bullet=True)
                put(rest, 10.5, indent=12, gap=7)
            else:
                put(ln[2:], 10.5, indent=12, gap=7, bullet=True)
        else:
            put(ln, 10.5, gap=7)
    _ = bold
    doc.set_metadata({"title": f"QuantiSheet {v} - What's New"})
    os.makedirs(os.path.dirname(out), exist_ok=True)
    doc.save(out, deflate=True)
    n = len(doc)
    doc.close()
    return out, n


if __name__ == "__main__":
    path, pages = build(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"wrote {path} ({pages} page(s))")
