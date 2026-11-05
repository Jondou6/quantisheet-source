"""Automatic accessibility tagging (Acrobat's "Autotag Document").

Builds the structure tree screen readers need from the page content:
every piece of text is wrapped in marked content and grouped into
headings and paragraphs in reading order; pictures become Figures with
alternate text; lines, fills and other decoration become Artifacts that
readers skip; links and form fields join the tree too.

    from app import autotag
    report = autotag.tag(doc)      # in place; save the document after

What it can't know - whether a picture needs a better description, or
whether a table is really a table - the accessibility check still asks
a person to review.
"""
import logging
import re
import statistics

import fitz

log = logging.getLogger(__name__)

PAINT = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"n"}
PATH_START = {b"m", b"re"}
WS = b" \t\r\n\f\x00"
DELIM = b"()<>[]{}/%"


class TagError(RuntimeError):
    pass


# --------------------------------------------------------------- tokenizer
def tokens(data):
    """(kind, start, end, value) for a content stream. kind is 'op' or
    'arg'; inline images come back as one 'op' named BI."""
    i, n = 0, len(data)
    while i < n:
        c = data[i:i + 1]
        if c in (b" ", b"\t", b"\r", b"\n", b"\f", b"\x00"):
            i += 1
            continue
        if c == b"%":
            while i < n and data[i:i + 1] not in (b"\r", b"\n"):
                i += 1
            continue
        s = i
        if c == b"(":
            depth = 0
            while i < n:
                ch = data[i:i + 1]
                if ch == b"\\":
                    i += 2
                    continue
                if ch == b"(":
                    depth += 1
                elif ch == b")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                i += 1
            yield "arg", s, i, None
            continue
        if data[i:i + 2] == b"<<":
            depth = 0
            while i < n:
                if data[i:i + 2] == b"<<":
                    depth += 1
                    i += 2
                elif data[i:i + 2] == b">>":
                    depth -= 1
                    i += 2
                    if depth == 0:
                        break
                elif data[i:i + 1] == b"(":
                    for _k, _s, e, _v in tokens(data[i:]):
                        i += e
                        break
                else:
                    i += 1
            yield "arg", s, i, None
            continue
        if c == b"<":
            j = data.find(b">", i)
            i = n if j < 0 else j + 1
            yield "arg", s, i, None
            continue
        if c in (b"[", b"]"):
            i += 1
            yield "arg", s, i, None
            continue
        if c == b"/":
            i += 1
            while i < n and data[i:i + 1] not in WS and \
                    data[i:i + 1] not in DELIM:
                i += 1
            yield "arg", s, i, data[s:i]
            continue
        while i < n and data[i:i + 1] not in WS and \
                data[i:i + 1] not in DELIM:
            i += 1
        if i == s:
            i += 1
            continue
        word = data[s:i]
        if re.fullmatch(rb"[+-]?(\d+\.?\d*|\.\d+)", word) or \
                word in (b"true", b"false", b"null"):
            yield "arg", s, i, word
            continue
        if word == b"BI":
            j = data.find(b"ID", i)
            k = j + 3 if j >= 0 else n
            m = re.compile(rb"\sEI(?=[\s]|$)").search(data, k)
            i = (m.end() if m else n)
            yield "op", s, i, b"BI"
            continue
        yield "op", s, i, word


def operations(data):
    """[(start, end, operator, [arg values])] - start is where the
    operation's first operand begins."""
    out, args, first = [], [], None
    for kind, s, e, v in tokens(data):
        if kind == "arg":
            if first is None:
                first = s
            args.append(v if v is not None else data[s:e])
            continue
        out.append((first if first is not None else s, e, v, args))
        args, first = [], None
    return out


def _num(b):
    try:
        return float(b)
    except (TypeError, ValueError):
        return 0.0


def _mul(a, b):
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4],
            a[4] * b[1] + a[5] * b[3] + b[5])


ID = (1, 0, 0, 1, 0, 0)


# --------------------------------------------------------------- rewriting
def _xobject_kinds(doc, page):
    """{name: 'image' | 'form'} for the page's XObjects."""
    out = {}
    for item in page.get_images(full=True):
        out[item[7]] = "image"
    for item in page.get_xobjects():
        out[item[1]] = "form"
    return out


def mark_page(doc, page, start_mcid=0):
    """Rewrite the page content with marked content. Returns (new bytes,
    [(mcid, kind, info)]) where kind is 'text' (info: origin in PDF
    space) or 'figure' (info: xobject name)."""
    page.clean_contents()
    data = page.read_contents()
    ops = operations(data)
    xkinds = _xobject_kinds(doc, page)
    out, pos, marks = [], 0, []
    mcid = start_mcid
    ctm, stack = ID, []
    in_bt = False
    bt_start = None
    tm = tlm = ID
    leading = 0.0
    first_origin = None
    path_start = None
    depth = 0                          # existing marked content depth
    for k, (s, e, op, args) in enumerate(ops):
        if op == b"q":
            stack.append(ctm)
        elif op == b"Q":
            ctm = stack.pop() if stack else ID
        elif op == b"cm" and len(args) >= 6:
            ctm = _mul(tuple(_num(a) for a in args[:6]), ctm)
        elif op in (b"BDC", b"BMC"):
            depth += 1
        elif op == b"EMC":
            depth = max(0, depth - 1)
        if op == b"BT":
            in_bt, bt_start = True, s
            tm = tlm = ID
            first_origin = None
            continue
        if in_bt:
            if op == b"Tm" and len(args) >= 6:
                tm = tlm = tuple(_num(a) for a in args[:6])
            elif op in (b"Td", b"TD") and len(args) >= 2:
                tlm = _mul((1, 0, 0, 1, _num(args[0]), _num(args[1])), tlm)
                tm = tlm
                if op == b"TD":
                    leading = -_num(args[1])
            elif op == b"TL" and args:
                leading = _num(args[0])
            elif op in (b"T*", b"'", b'"'):
                tlm = _mul((1, 0, 0, 1, 0, -leading), tlm)
                tm = tlm
            if op in (b"Tj", b"TJ", b"'", b'"') and first_origin is None:
                m = _mul(tm, ctm)
                first_origin = (m[4], m[5])
            if op == b"ET":
                in_bt = False
                if first_origin is None:      # empty text object: skip
                    continue
                out.append(data[pos:bt_start])
                out.append(b"/P <</MCID %d>> BDC\n" % mcid)
                out.append(data[bt_start:e])
                out.append(b"\nEMC\n")
                pos = e
                marks.append((mcid, "text", first_origin))
                mcid += 1
            continue
        if op in PATH_START and path_start is None:
            path_start = s
            continue
        if op in PAINT and path_start is not None:
            out.append(data[pos:path_start])
            out.append(b"/Artifact BMC\n")
            out.append(data[path_start:e])
            out.append(b"\nEMC\n")
            pos = e
            path_start = None
            continue
        if path_start is not None and op not in (b"l", b"c", b"v", b"y",
                                                 b"h", b"m", b"re", b"W",
                                                 b"W*"):
            path_start = None              # malformed path: leave it
        if op == b"Do" and args:
            name = args[-1].decode("latin-1").lstrip("/")
            kind = xkinds.get(name, "form")
            m = ctm
            bbox = fitz.Rect(m[4], m[5], m[4] + m[0] + m[2],
                             m[5] + m[1] + m[3]).normalize()
            out.append(data[pos:s])
            out.append(b"/Figure <</MCID %d>> BDC\n" % mcid)
            out.append(data[s:e])
            out.append(b"\nEMC\n")
            pos = e
            marks.append((mcid, "figure", {"name": name, "kind": kind,
                                           "bbox": bbox}))
            mcid += 1
            continue
        if op == b"BI":
            out.append(data[pos:s])
            out.append(b"/Figure <</MCID %d>> BDC\n" % mcid)
            out.append(data[s:e])
            out.append(b"\nEMC\n")
            pos = e
            m = ctm
            marks.append((mcid, "figure", {"name": "inline", "kind":
                                           "image", "bbox": fitz.Rect(
                                               m[4], m[5], m[4] + m[0],
                                               m[5] + m[3]).normalize()}))
            mcid += 1
    out.append(data[pos:])
    return b"".join(out), marks


# --------------------------------------------------------------- structure
def _blocks(page):
    """Text blocks in reading order with their spans' sizes and origins
    (unrotated page space)."""
    d = page.get_text("dict", sort=True)
    inv = ~page.rotation_matrix
    out = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        spans = [s for ln in b.get("lines", []) for s in ln.get("spans", [])
                 if s.get("text", "").strip()]
        if not spans:
            continue
        text = " ".join(" ".join(s["text"] for s in ln["spans"]).strip()
                        for ln in b["lines"]).strip()
        out.append({"text": text, "lines": len(b["lines"]),
                    "size": max(s["size"] for s in spans),
                    "bold": all("bold" in s["font"].lower() or
                                s.get("flags", 0) & 16 for s in spans),
                    "origins": [fitz.Point(s["origin"]) * inv
                                for s in spans],
                    "bbox": fitz.Rect(b["bbox"]) * inv})
    return out


def _role(b, body):
    words = len(b["text"].split())
    if b["size"] >= body * 1.6 and words <= 20:
        return "H1"
    if (b["size"] >= body * 1.2 or b["bold"]) and words <= 14 and \
            b["lines"] <= 2:
        return "H2"
    if re.match(r"^\s*([•▪●◦\-–]|\(?\d{1,2}[.)]|[a-z][.)])\s+\S", b["text"]):
        return "LI"
    return "P"


def is_tagged(doc):
    return doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] != \
        "null"


def tag(doc, lang="en-US", force=False, progress=None):
    """Tag the document in place. Returns a report dict."""
    if is_tagged(doc) and not force:
        raise TagError("This document is already tagged.")
    cat = doc.pdf_catalog()
    root = doc.get_new_xref()
    docel = doc.get_new_xref()
    parent_tree = doc.get_new_xref()
    doc_kids, nums = [], []
    counts = {"H1": 0, "H2": 0, "P": 0, "LI": 0, "Figure": 0, "Link": 0,
              "Form": 0, "pages": 0}
    sizes = []
    for page in doc:
        for b in _blocks(page):
            sizes.append(b["size"])
    body = statistics.median(sizes) if sizes else 10.0
    sp_key = 0
    for pno, page in enumerate(doc):
        if progress:
            progress(pno, doc.page_count)
        new, marks = mark_page(doc, page)
        xref = page.get_contents()[0]
        doc.update_stream(xref, new)
        to_fitz = page.transformation_matrix
        blocks = _blocks(page)
        groups = {}                     # block index -> [mcid]
        loose = []
        for mcid, kind, info in marks:
            if kind != "text":
                continue
            pt = fitz.Point(info) * to_fitz
            best, bd = None, 1e9
            for bi, b in enumerate(blocks):
                if b["bbox"].contains(pt):
                    d = 0
                else:
                    d = min(abs(o - pt) for o in b["origins"])
                if d < bd:
                    best, bd = bi, d
            if best is None or bd > 40:
                loose.append(mcid)
            else:
                groups.setdefault(best, []).append(mcid)
        page_ref = f"{page.xref} 0 R"
        elems = []                       # (sort key, xref, mcids)
        mcid_owner = {}
        for bi, mcids in groups.items():
            b = blocks[bi]
            role = _role(b, body)
            counts[role] += 1
            ex = doc.get_new_xref()
            k = mcids[0] if len(mcids) == 1 else \
                "[" + " ".join(map(str, sorted(mcids))) + "]"
            doc.update_object(ex, f"<</Type/StructElem/S/{role}/P {docel} "
                                  f"0 R/Pg {page_ref}/K {k}>>")
            elems.append(((0, bi), ex))
            for m in mcids:
                mcid_owner[m] = ex
        for m in loose:
            ex = doc.get_new_xref()
            doc.update_object(ex, f"<</Type/StructElem/S/Span/P {docel} 0 R"
                                  f"/Pg {page_ref}/K {m}>>")
            elems.append(((1, m), ex))
            mcid_owner[m] = ex
        for mcid, kind, info in marks:
            if kind != "figure":
                continue
            counts["Figure"] += 1
            alt = "Drawing" if info["kind"] == "form" else "Image"
            ex = doc.get_new_xref()
            doc.update_object(ex, f"<</Type/StructElem/S/Figure/P {docel} "
                                  f"0 R/Pg {page_ref}/K {mcid}/Alt "
                                  f"{fitz.get_pdf_str(alt)}>>")
            y = (fitz.Point(info["bbox"].x0, info["bbox"].y1) *
                 to_fitz).y
            elems.append(((0.5, y), ex))
            mcid_owner[mcid] = ex
        elems.sort(key=lambda t: t[0])
        doc_kids += [ex for _k, ex in elems]
        if marks:
            arr = " ".join(f"{mcid_owner[m]} 0 R" if m in mcid_owner
                           else "null" for m, _k, _i in marks)
            doc.xref_set_key(page.xref, "StructParents", str(sp_key))
            nums.append(f"{sp_key} [{arr}]")
            sp_key += 1
        # links and form fields
        annots = doc.xref_get_key(page.xref, "Annots")
        refs = []
        if annots[0] == "array":
            refs = [int(x) for x in re.findall(r"(\d+) 0 R", annots[1])]
        elif annots[0] == "xref":
            arr = doc.xref_object(int(annots[1].split()[0]))
            refs = [int(x) for x in re.findall(r"(\d+) 0 R", arr)]
        for ax in refs:
            sub = doc.xref_get_key(ax, "Subtype")[1]
            if sub not in ("/Link", "/Widget"):
                continue
            role = "Link" if sub == "/Link" else "Form"
            counts[role] += 1
            ex = doc.get_new_xref()
            doc.update_object(ex, f"<</Type/StructElem/S/{role}/P {docel} "
                                  f"0 R/Pg {page_ref}/K <</Type/OBJR/Obj "
                                  f"{ax} 0 R>>>>")
            doc.xref_set_key(ax, "StructParent", str(sp_key))
            nums.append(f"{sp_key} {ex} 0 R")
            sp_key += 1
            doc_kids.append(ex)
        if refs:
            doc.xref_set_key(page.xref, "Tabs", "/S")
        counts["pages"] += 1
    kids = " ".join(f"{x} 0 R" for x in doc_kids)
    doc.update_object(docel, f"<</Type/StructElem/S/Document/P {root} 0 R"
                             f"/K [{kids}]>>")
    doc.update_object(parent_tree, f"<</Nums [{' '.join(nums)}]>>")
    doc.update_object(root, f"<</Type/StructTreeRoot/K {docel} 0 R"
                            f"/ParentTree {parent_tree} 0 R"
                            f"/ParentTreeNextKey {sp_key}>>")
    doc.xref_set_key(cat, "StructTreeRoot", f"{root} 0 R")
    doc.xref_set_key(cat, "MarkInfo", "<</Marked true>>")
    if doc.xref_get_key(cat, "Lang")[0] != "string":
        doc.xref_set_key(cat, "Lang", fitz.get_pdf_str(lang))
    counts["body_size"] = round(body, 1)
    return counts


def structure(doc):
    """[(role, text)] of the tagged document, in tree order (for review
    and tests): text is gathered from each element's marked content."""
    root = doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")
    if root[0] == "null":
        return []
    docel = int(re.search(r"/K (\d+) 0 R",
                          doc.xref_object(int(root[1].split()[0])))
                .group(1))
    kids = re.findall(r"(\d+) 0 R", doc.xref_get_key(docel, "K")[1])
    out = []
    for k in kids:
        obj = doc.xref_object(int(k))
        role = re.search(r"/S\s*/(\w+)", obj).group(1)
        alt = re.search(r"/Alt\s*\(([^)]*)\)", obj)
        out.append((role, alt.group(1) if alt else ""))
    return out
