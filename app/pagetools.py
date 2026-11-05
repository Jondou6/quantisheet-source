"""Page-level operations on an open document (no Qt; easy to test).

Each keeps the takeoff scales with their pages (see jobdata)."""
from . import safeio
import fitz

from . import jobdata


def rotate(doc, pages, degrees):
    if degrees % 90:
        raise ValueError("rotation must be a multiple of 90 degrees")
    for i in pages:
        p = doc[i]
        p.set_rotation((p.rotation + degrees) % 360)


def delete(doc, pages):
    pages = sorted(set(pages))
    if len(pages) >= doc.page_count:
        raise ValueError("A PDF must keep at least one page.")
    with jobdata.keep_scales(doc):
        doc.delete_pages(pages)


def move(doc, frm, to):
    """Move page `frm` so it ends up at index `to`."""
    n = doc.page_count
    if not (0 <= frm < n and 0 <= to < n) or frm == to:
        return
    with jobdata.keep_scales(doc):
        if to > frm:
            doc.move_page(frm, to + 1 if to + 1 < n else -1)
        else:
            doc.move_page(frm, to)


def insert_blank(doc, after):
    """Insert a blank page (same size as page `after`) after it."""
    ref = doc[after].rect if 0 <= after < doc.page_count else fitz.paper_rect("letter")
    with jobdata.keep_scales(doc):
        doc.new_page(after + 1, width=ref.width, height=ref.height)
    return after + 1


def insert_pdf(doc, path, after):
    """Insert all pages of another PDF after page `after`. Returns count."""
    src = fitz.open(path)
    try:
        if src.needs_pass:
            raise ValueError("That PDF is password-protected.")
        n = src.page_count
        with jobdata.keep_scales(doc):
            doc.insert_pdf(src, start_at=after + 1)
        # the inserted sheets bring their own scales (and job data the
        # document doesn't have yet)
        jobdata.copy_job(src, doc, {k: after + 1 + k for k in range(n)})
    finally:
        src.close()
    return n


def insert_doc(doc, src, after):
    """Insert all pages of an open PDF (with its scales) after page
    `after`. Returns the count."""
    n = src.page_count
    with jobdata.keep_scales(doc):
        doc.insert_pdf(src, start_at=after + 1)
    jobdata.copy_job(src, doc, {k: after + 1 + k for k in range(n)})
    return n


def extract(doc, pages, out_path):
    out = fitz.open()
    try:
        for i in sorted(pages):
            out.insert_pdf(doc, from_page=i, to_page=i)
        jobdata.copy_job(doc, out, {p: k for k, p in enumerate(sorted(pages))})
        safeio.atomic_save(out, out_path, garbage=safeio.gc_level(out), deflate=True)
    finally:
        out.close()
    return out_path
