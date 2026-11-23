"""Build the QuantiSheet Features and How-To Guide PDF from guide_src.txt.
Chromium (Playwright) renders it; pypdf adds the cover and bookmarks.
menus.json (chapter 8) comes from: pytest tests/dump_menus_once.py on the PC.
python3 build.py VERSION OUT.pdf"""
import html
import json
import os
import re
import subprocess
import sys

import pypdf

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO = os.path.join(HERE, "logo512.png")


def _logo_uri():
    import base64
    with open(LOGO, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()
V = sys.argv[1]
OUT = sys.argv[2]

CSS = """
@page { size: Letter; margin: 0.95in 0.88in 0.9in 0.88in; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { font-family: 'Liberation Sans', Arial, Helvetica, sans-serif;
       font-size: 10.6pt; line-height: 1.55; color: #2b1f1e; }
b { color: #9a1f1f; }
a { color: #b8312b; }
h1 { font-size: 20pt; color: #8e1b1b; margin: 0 0 14px; padding-bottom: 10px;
     border-bottom: 2.4px solid #d23a33; line-height: 1.2; }
h1.page { break-before: page; }
h1.same { margin-top: 26px; }
h2 { font-size: 13.2pt; color: #b8312b; margin: 20px 0 8px; line-height: 1.25;
     break-after: avoid; }
h3 { font-size: 10.6pt; color: #9a1f1f; margin: 12px 0 6px; break-after: avoid; }
p { margin: 0 0 8px; }
ul, ol { margin: 0 0 9px; padding-left: 22px; }
li { margin: 0 0 3px; padding-left: 2px; }
li.sub { margin-left: 22px; list-style: circle; }
code { font-family: 'Liberation Mono', Consolas, monospace; font-size: 9.4pt;
       background: #f6eeed; padding: 1px 4px; border-radius: 3px; }
table.keys { width: 100%; border-collapse: collapse; font-size: 9.8pt;
             margin: 4px 0 12px; }
table.keys th { background: #8e1b1b; color: #fff; text-align: left;
                padding: 7px 9px; font-weight: bold; }
table.keys td { padding: 6px 9px; border-bottom: 1px solid #ead9d7;
                vertical-align: middle; }
table.keys tr:nth-child(even) td { background: #fbf3f2; }
table.keys td:first-child, table.keys th:first-child { width: 55%; }
table.keys tr { break-inside: avoid; }
thead { display: table-header-group; }
.toc h1 { margin-bottom: 8px; }
.toc .row { display: flex; justify-content: space-between; align-items: baseline;
            border-bottom: 1px dotted #d6c2c0; padding: 7px 0 5px; }
.toc .row.top { font-size: 11.4pt; padding: 9px 0 6px; }
.toc .row.sub { font-size: 9.8pt; padding-left: 22px; }
.toc .row .n { color: #b8312b; font-weight: bold; }
.dummy { break-after: page; }
.wm { position: fixed; left: 50%; top: 50%; width: 4.6in; height: 4.6in;
      margin: -2.3in 0 0 -2.3in; opacity: 0.06; z-index: -1; }
"""

COVER = """<!doctype html><html><head><meta charset="utf-8"><style>
@page { size: Letter; margin: 0; }
html, body { margin: 0; }
body { width: 8.5in; height: 11in; font-family: 'Liberation Sans', Arial, sans-serif;
  color: #fff; background: linear-gradient(170deg, #ec4b42 0%, #d23a33 50%, #a91d1d 100%);
  position: relative; overflow: hidden; }
.k { position: absolute; left: 0.9in; top: 2.65in; letter-spacing: 4px; font-size: 13pt;
     color: #ffe3e0; }
.t { position: absolute; left: 0.9in; top: 3.15in; font-size: 44pt; font-weight: bold;
     line-height: 1.12; }
.s { position: absolute; left: 0.9in; top: 4.72in; font-size: 18pt; color: #fff3f2; }
.logo { position: absolute; left: 0.9in; top: 0.9in; width: 1.25in; height: 1.25in;
        border-radius: 0.22in; box-shadow: 0 6px 18px rgba(80,0,0,.35); }
.v { position: absolute; left: 0.9in; top: 9.45in; background: #fff; color: #a91d1d;
     font-weight: bold; font-size: 15pt; padding: 9px 16px; border-radius: 22px; }
.c { position: absolute; left: 0.9in; top: 10.2in; font-size: 9.5pt; color: #ffe3e0; }
</style></head><body>
<img class="logo" src="{LOGO}">
<div class="k">QUANTISHEET</div>
<div class="t">Features and<br>How-To Guide</div>
<div class="s">Construction takeoff and estimating for Windows</div>
<div class="v">Version {V}</div>
<div class="c">Covers QuantiSheet through version {V}</div>
</body></html>"""

FOOTER = ("<div style=\"width:100%;font-family:'Liberation Sans',Arial,sans-serif;"
          "font-size:11px;color:#8a7d7c;padding:0 0.8in;\">"
          "<div style=\"border-top:1px solid #e9dedd;padding-top:8px;display:flex;"
          "justify-content:space-between;\"><span>QuantiSheet&nbsp; | &nbsp;"
          "Features and How-To Guide&nbsp; | &nbsp;Version " + V +
          "</span><span>Page <span class=\"pageNumber\"></span></span></div></div>")


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\[\[(.+?)\]\]", lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return s.replace("{V}", V)


def parse(src):
    """-> (body html, toc entries [(level, title, id)])"""
    out, toc, lst = [], [], None
    table = None

    def close():
        nonlocal lst
        if lst:
            out.append(f"</{lst}>")
            lst = None

    n = 0
    for raw in src.splitlines():
        line = raw.rstrip()
        if table is not None:
            if line == "@endtable":
                rows = table
                out.append('<table class="keys"><thead><tr>' + "".join(
                    f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr></thead><tbody>")
                for r in rows[1:]:
                    out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r)
                               + "</tr>")
                out.append("</tbody></table>")
                table = None
            else:
                table.append([c.strip() for c in line.split("|")])
            continue
        if not line:
            close()
            continue
        if line == "@table":
            close()
            table = []
            continue
        m = re.match(r"@h([123]) (.+)$", line)
        if m:
            close()
            lvl = int(m.group(1))
            parts = [p.strip() for p in m.group(2).split("|")]
            title, hid = parts[0], (parts[1] if len(parts) > 1 else f"x{n}")
            n += 1
            cls = ""
            if lvl == 1:
                cls = ' class="same"' if "samepage" in parts else ' class="page"'
            out.append(f'<h{lvl} id="{hid}"{cls}>{inline(title)}</h{lvl}>')
            if lvl == 1 or (lvl == 2 and re.match(r"\d+\.\d+ ", title)):
                toc.append((lvl, title, hid))
            continue
        if line.startswith("  - "):
            out.append(f'<li class="sub">{inline(line[4:])}</li>')
            continue
        if line.startswith("- "):
            if lst != "ul":
                close()
                out.append("<ul>")
                lst = "ul"
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if re.match(r"1\. ", line):
            if lst != "ol":
                close()
                out.append("<ol>")
                lst = "ol"
            out.append(f"<li>{inline(line[3:])}</li>")
            continue
        close()
        out.append(f"<p>{inline(line)}</p>")
    close()
    return "\n".join(out), toc


def page_html(body, toc, pages):
    rows = []
    for lvl, title, hid in toc:
        num = pages.get(hid, 88)
        cls = "top" if lvl == 1 else "sub"
        rows.append(f'<div class="row {cls}"><span>{inline(title)}</span>'
                    f'<span class="n">{num}</span></div>')
    return ("<!doctype html><html><head><meta charset='utf-8'><title>QuantiSheet "
            f"Features and How-To Guide (Version {V})</title><style>{CSS}</style>"
            "</head><body><img class='wm' src='" + _logo_uri() + "'>"
            "<div class='dummy'>&nbsp;</div>"
            "<div class='toc'><h1>Contents</h1>" + "".join(rows) + "</div>"
            + body + "</body></html>")


def render(html_path, pdf_path, footer=True):
    js = os.path.join(HERE, "render.js")
    subprocess.run(["node", js, html_path, pdf_path, json.dumps(
        FOOTER if footer else "")], check=True, cwd=HERE)


def heading_pages(pdf_path, toc):
    """id -> printed page number, from the PDF outline Chromium wrote."""
    r = pypdf.PdfReader(pdf_path)
    found = {}

    def walk(items):
        for it in items:
            if isinstance(it, list):
                walk(it)
            else:
                found.setdefault(it.title.strip(), r.get_destination_page_number(it) + 1)
    walk(r.outline)
    pages = {}
    for lvl, title, hid in toc:
        t = html.unescape(inline(title).replace("<b>", "").replace("</b>", ""))
        if t in found:
            pages[hid] = found[t]
        else:
            print("NOT IN OUTLINE:", t)
    return pages


# ------------------------------------------------- the command reference
# other companies' product names never appear in the guide (Jon, Nov 23):
# only open source we use (Tesseract, Ollama) and the platform (Windows)
PRODUCT_WORDS = [
    (r"\s*\(for Excel\)", " (for a spreadsheet)"),
    (r"Link Quantities to Excel", "Link Quantities to a Spreadsheet"),
    (r"Excel Workbook", "Workbook"), (r"Word Document", "Document"),
    (r"PowerPoint", "Slides"), (r"\s*\(Excel\)", " (.xlsx)"),
    (r"\bExcel\b", "spreadsheet"), (r"AutoCAD\s+", ""),
    (r"Google Earth \(KML,", "KML ("), (r"Google Earth\s*", ""),
    (r"Sage 300 Job Cost", "Job Cost"),
    (r"^Sage 300$", "Job Cost Export"), (r"\bSage( 300)?\b", "accounting"),
    (r"CivilBid[- ]Coded", "Cost-Coded"), (r"CivilBid codes", "cost codes"),
    (r"^CivilBid Library$", "Coded Library"),
    (r"Export to CivilBid", "Export to Civil Estimating"),
    (r"^CivilBid$", "Civil Export"),
    (r"CivilBid|HeavyBid", "civil estimating"),
    (r"Microsoft Project|MS Project", "XML schedule"),
    (r"Primavera\s*P6|\bP6\b", "XER"), (r"\bOutlook\b", "email"),
    (r"QuickBooks", "accounting"), (r"\bhh2\b", "payroll"),
    (r"FedEx, UPS, USPS,? (?:and|&) DHL", "parcel carriers"),
    (r"YouTube", "video"), (r"Dropbox", "Cloud Storage"), (r"Bluebeam|Acrobat|Adobe", ""),
]


def scrub(text):
    text = text.replace("&&", "&")
    for a, b in PRODUCT_WORDS:
        text = re.sub(a, b, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def command_reference(path):
    """@-source lines for the chapter listing every menu and ribbon tab."""
    data = json.load(open(path, encoding="utf-8"))
    out = ["@h1 8. Every command, menu by menu | commands",
           "Every command in the menus, as the program shows them, with its "
           "shortcut. Press **F10** (or Alt) to open the menus from the "
           "keyboard, or type any of these names in **Ctrl+K**."]

    def rows(items, prefix, acc):
        for it in items:
            name = scrub(it["text"]).replace("…", "").strip()
            if not name:
                continue
            if it.get("menu"):
                rows(it["menu"], prefix + [name], acc)
            else:
                acc.append((" > ".join(prefix[1:]), name, it.get("keys", "")))

    for top in data["menus"]:
        title = scrub(top["text"]).strip()
        acc = []
        rows(top.get("menu", []), [title], acc)
        if not acc:
            continue
        out.append(f"@h2 {title} menu")
        out.append("@table")
        out.append("Command | Shortcut")
        for sub, name, keys in acc:
            label = (sub + " > " + name) if sub else name
            out.append(f"{label} | {keys}")
        out.append("@endtable")
    out.append("@h2 Ribbon tabs")
    out.append("The ribbon groups the same commands by task. Each tab and its "
               "groups:")
    for tab, groups in data["ribbon"].items():
        parts = []
        for g, btns in groups.items():
            names = [scrub(b.get("label") or b.get("action") or "")
                     .replace("\n", " ") for b in btns]
            names = [n for n in names if n]
            if names:
                parts.append(f"**{scrub(g)}:** " + ", ".join(names))
        if parts:
            out.append(f"@h3 {scrub(tab)} tab")
            for p_ in parts:
                out.append("- " + p_)
    return "\n".join(out)


def main():
    src = open(os.path.join(HERE, "guide_src.txt"), encoding="utf-8").read()
    menus = os.path.join(HERE, "menus.json")
    if os.path.exists(menus):
        src += "\n\n" + command_reference(menus)
    body, toc = parse(src)
    pages = {}
    for _ in range(3):
        hp = os.path.join(HERE, "body.html")
        open(hp, "w", encoding="utf-8").write(page_html(body, toc, pages))
        render(hp, os.path.join(HERE, "body.pdf"))
        new = heading_pages(os.path.join(HERE, "body.pdf"), toc)
        if new == pages:
            break
        pages = new
    cp = os.path.join(HERE, "cover.html")
    open(cp, "w", encoding="utf-8").write(COVER.replace("{V}", V).replace("{LOGO}", _logo_uri()))
    render(cp, os.path.join(HERE, "cover.pdf"), footer=False)
    w = pypdf.PdfWriter()
    w.append(os.path.join(HERE, "cover.pdf"))
    b = pypdf.PdfReader(os.path.join(HERE, "body.pdf"))
    for p in b.pages[1:]:
        w.add_page(p)
    # bookmarks
    parent = None
    w.add_outline_item("Contents", 1)
    for lvl, title, hid in toc:
        t = html.unescape(re.sub(r"<.+?>", "", inline(title)))
        if hid not in pages:
            continue
        if lvl == 1:
            parent = w.add_outline_item(t, pages[hid] - 1)
        else:
            w.add_outline_item(t, pages[hid] - 1, parent=parent)
    w.add_metadata({"/Title": f"QuantiSheet Features and How-To Guide (Version {V})",
                    "/Author": "QuantiSheet"})
    w.page_mode = "/UseOutlines"
    with open(OUT, "wb") as f:
        w.write(f)
    print("pages", len(w.pages), pages)


if __name__ == "__main__":
    main()
