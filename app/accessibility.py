"""Accessibility check (Document > Accessibility Check), Acrobat-style.

Checks what can be judged from the file and fixes what can be fixed
safely - including tagging the structure (autotag.py); says plainly what
needs a person (describing figures well is one).

check(doc) -> [{rule, ok, detail, fix}] where fix names an automatic fix
fix(doc, rules) -> what was changed
"""
import logging
import os
import re

import fitz

from . import annotate

log = logging.getLogger(__name__)

RULES = [
    ("tagged", "Tagged PDF", "The document has a structure tree, so screen "
     "readers know the reading order."),
    ("title", "Title", "The document has a title, shown in the window "
     "instead of the file name."),
    ("language", "Language", "The document's language is set."),
    ("text", "Text, not pictures of text", "Every page has real text a "
     "screen reader can read (scans need OCR)."),
    ("bookmarks", "Bookmarks", "Long documents (over 20 pages) have "
     "bookmarks to move around."),
    ("tab_order", "Tab order", "Pages tab through links and fields in "
     "reading order."),
    ("field_names", "Form field descriptions", "Every form field has a "
     "description (tooltip) a screen reader can announce."),
    ("annot_text", "Markup descriptions", "Comments and markups have text."),
    ("links", "Link descriptions", "Links say where they go."),
    ("security", "Assistive technology allowed", "Security settings let "
     "screen readers read the content."),
    ("fonts", "Fonts embedded", "Fonts are embedded so text displays and "
     "reads the same everywhere."),
]
NAMES = {k: n for k, n, _ in RULES}
FIXABLE = {"tagged", "title", "language", "tab_order", "field_names",
           "annot_text", "links", "bookmarks"}


def _catalog_key(doc, key):
    return doc.xref_get_key(doc.pdf_catalog(), key)


def check(doc):
    out = []

    def add(rule, ok, detail):
        out.append({"rule": rule, "name": NAMES[rule], "ok": bool(ok),
                    "detail": detail, "fix": rule in FIXABLE and not ok})

    t = _catalog_key(doc, "StructTreeRoot")[0]
    mark = _catalog_key(doc, "MarkInfo")[1] or ""
    add("tagged", t != "null" and "Marked true" in mark.replace("/", ""),
        "Tagged" if t != "null" else
        "Not tagged - Fix Automatically tags it (headings, paragraphs, "
        "figures, links, reading order). Review figure descriptions after.")
    title = (doc.metadata or {}).get("title") or ""
    vp = doc.xref_get_key(doc.pdf_catalog(), "ViewerPreferences")[1] or ""
    add("title", title.strip() and "DisplayDocTitle true" in vp.replace(
        "/", ""), f"Title: {title}" if title else "No title")
    lang = _catalog_key(doc, "Lang")
    add("language", lang[0] == "string" and lang[1],
        f"Language: {lang[1]}" if lang[0] == "string" else "Not set")
    from .acrobat import page_has_text        # fast on big plan sets
    no_text = [i + 1 for i, p in enumerate(doc)
               if not page_has_text(p, min_chars=1)]
    add("text", not no_text, "Every page has text" if not no_text else
        f"{len(no_text)} page(s) have no text: " +
        ", ".join(map(str, no_text[:12])) + " (Document > Make Searchable)")
    toc = doc.get_toc()
    add("bookmarks", doc.page_count <= 20 or toc,
        f"{len(toc)} bookmark(s)" if toc else
        ("Short document" if doc.page_count <= 20 else "No bookmarks"))
    bad_tabs = [i + 1 for i, p in enumerate(doc)
                if doc.xref_get_key(p.xref, "Tabs")[1] != "/S"
                and (p.first_annot or p.first_widget)]
    add("tab_order", not bad_tabs, "Structure order" if not bad_tabs else
        f"{len(bad_tabs)} page(s) without a tab order")
    fields = no_tip = 0
    no_text_annots = 0
    links = bad_links = 0
    for p in doc:
        for w in p.widgets() or []:
            fields += 1
            if doc.xref_get_key(w.xref, "TU")[0] != "string":
                no_tip += 1
        for a in annotate.iter_annots(p) or []:
            if a.type[0] in (fitz.PDF_ANNOT_POPUP,):
                continue
            if not (a.info or {}).get("content") and \
                    not (a.info or {}).get("subject"):
                no_text_annots += 1
        for ln in p.get_links():
            links += 1
            if ln.get("xref") and doc.xref_get_key(
                    ln["xref"], "Contents")[0] != "string":
                bad_links += 1
    add("field_names", not no_tip, f"{fields} field(s)" if not no_tip else
        f"{no_tip} of {fields} field(s) without a description")
    add("annot_text", not no_text_annots, "All have text" if not
        no_text_annots else f"{no_text_annots} markup(s) without text")
    add("links", not bad_links, f"{links} link(s)" if not bad_links else
        f"{bad_links} of {links} link(s) without a description")
    acc = getattr(fitz, "PDF_PERM_ACCESSIBILITY", 512)
    allowed = not doc.is_encrypted or bool(doc.permissions & acc)
    add("security", allowed, "Allowed" if allowed else
        "Blocked by the security settings")
    unembedded = sorted({f[3] for i in range(doc.page_count)
                         for f in doc.get_page_fonts(i)
                         if f[1] in ("Type1", "TrueType", "Type0", "Type3")
                         and not _embedded(doc, f)})
    add("fonts", not unembedded, "All embedded" if not unembedded else
        f"Not embedded: {', '.join(unembedded[:6])}")
    return out


def _embedded(doc, f):
    try:
        return bool(doc.extract_font(f[0])[3])
    except Exception:
        return True


def fix(doc, rules=None, title=None, lang="en-US"):
    """Apply the automatic fixes (all fixable failures, or `rules`).
    Returns a list of what was done."""
    todo = rules or [r["rule"] for r in check(doc) if r["fix"]]
    done = []
    cat = doc.pdf_catalog()
    if "tagged" in todo:
        from . import autotag
        if not autotag.is_tagged(doc):
            n = autotag.tag(doc, lang=lang)
            done.append(f"Tagged: {n['H1'] + n['H2']} heading(s), "
                        f"{n['P'] + n['LI']} paragraph(s), {n['Figure']} "
                        f"figure(s), {n['Link']} link(s), {n['Form']} "
                        "field(s)")
    if "title" in todo:
        md = dict(doc.metadata or {})
        if not (md.get("title") or "").strip():
            md["title"] = title or os.path.splitext(
                os.path.basename(doc.name or "Document"))[0]
            doc.set_metadata(md)
        vp = doc.xref_get_key(cat, "ViewerPreferences")
        if vp[0] == "xref":
            x = int(vp[1].split()[0])
            doc.xref_set_key(x, "DisplayDocTitle", "true")
        else:
            doc.xref_set_key(cat, "ViewerPreferences",
                             "<</DisplayDocTitle true>>")
        done.append(f"Title set to \"{doc.metadata.get('title')}\"")
    if "language" in todo:
        doc.xref_set_key(cat, "Lang", fitz.get_pdf_str(lang))
        done.append(f"Language set to {lang}")
    if "tab_order" in todo:
        n = 0
        for p in doc:
            if p.first_annot or p.first_widget:
                doc.xref_set_key(p.xref, "Tabs", "/S")
                n += 1
        done.append(f"Tab order set on {n} page(s)")
    if "field_names" in todo:
        n = 0
        for p in doc:
            for w in p.widgets() or []:
                if doc.xref_get_key(w.xref, "TU")[0] != "string":
                    label = re.sub(r"[_\-.]+", " ", w.field_name or
                                   "Field").strip()
                    doc.xref_set_key(w.xref, "TU", fitz.get_pdf_str(label))
                    n += 1
        done.append(f"Descriptions added to {n} field(s)")
    if "annot_text" in todo:
        n = 0
        for p in doc:
            for a in annotate.iter_annots(p) or []:
                info = a.info or {}
                if not info.get("content") and not info.get("subject"):
                    a.set_info(content=a.type[1])
                    a.update()
                    n += 1
        done.append(f"Text added to {n} markup(s)")
    if "links" in todo:
        n = 0
        for p in doc:
            for ln in p.get_links():
                x = ln.get("xref")
                if not x or doc.xref_get_key(x, "Contents")[0] == "string":
                    continue
                where = ln.get("uri") or (f"Go to page {ln['page'] + 1}"
                                          if ln.get("page", -1) >= 0
                                          else "Link")
                doc.xref_set_key(x, "Contents", fitz.get_pdf_str(where))
                n += 1
        done.append(f"Descriptions added to {n} link(s)")
    if "bookmarks" in todo and not doc.get_toc() and doc.page_count > 20:
        try:
            from . import sheets
            labels = {i["page"]: i["label"] for i in sheets.scan(doc)}
            toc = [[1, labels.get(i) or f"Page {i + 1}", i + 1]
                   for i in range(doc.page_count)]
            doc.set_toc(toc)
            done.append(f"{len(toc)} bookmark(s) added (sheet numbers "
                        "and titles where found)")
        except Exception:
            log.warning("bookmarks", exc_info=True)
    return done
