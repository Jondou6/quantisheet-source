import fitz

from . import safeio


def _insert_visual(page, pt, text, **kw):
    """insert_text at a point given in what-you-see coordinates, so text
    lands upright and in the right corner on rotated pages too."""
    page.insert_text(pt * page.derotation_matrix, text,
                     rotate=page.rotation, **kw)


def bates_number(doc, prefix="DOC", start=1, margin=40, fontsize=9):
    n = start
    for page in doc:
        label = f"{prefix}{n:06d}"
        w = fitz.get_text_length(label, fontsize=fontsize)
        r = page.rect                                  # as displayed
        _insert_visual(page, fitz.Point(r.width - margin - w,
                                        r.height - margin / 2),
                       label, fontsize=fontsize)
        n += 1
    return n - start


def add_watermark(doc, text="DRAFT", opacity=0.25, rotate=45, size=60):
    """Semi-transparent diagonal text across each page.

    The original used render_mode=3 (invisible text), ignored `opacity`, and
    passed rotate=45, which insert_text rejects (it only takes multiples of
    90), so it either failed or drew nothing.
    """
    for page in doc:
        r = page.rect                              # as displayed
        center = fitz.Point(r.width / 2, r.height / 2) * page.derotation_matrix
        tw = fitz.get_text_length(text, fontsize=size)
        start = fitz.Point(center.x - tw / 2, center.y + size * 0.35)
        page.insert_text(start, text, fontsize=size, color=(0.5, 0.5, 0.5),
                         fill_opacity=opacity, overlay=True,
                         morph=(center, fitz.Matrix(rotate)))


def compress(doc, out):
    doc.save(out, garbage=4, deflate=True, deflate_images=True,
             deflate_fonts=True, clean=True)
    return out


def extract_pages(doc, pages):
    """`pages` are 0-based page indexes."""
    from . import jobdata
    out = fitz.open()
    pmap = {}
    for i in pages:
        if 0 <= i < doc.page_count:
            out.insert_pdf(doc, from_page=i, to_page=i)
            pmap.setdefault(i, out.page_count - 1)
    jobdata.copy_job(doc, out, pmap)
    return out


def merge(paths, out):
    from . import jobdata
    m = fitz.open()
    for p in paths:
        d = fitz.open(p)
        start = m.page_count
        m.insert_pdf(d)
        jobdata.copy_job(d, m, {k: start + k for k in range(d.page_count)})
        d.close()
    m.save(out, garbage=safeio.gc_level(m), deflate=True)
    m.close()
    return out


def rotate_pages(doc, degrees=90):
    if degrees % 90:
        raise ValueError("rotation must be a multiple of 90 degrees")
    for page in doc:
        page.set_rotation((page.rotation + degrees) % 360)


def delete_pages(doc, pages):
    from . import jobdata
    with jobdata.keep_scales(doc):
        for i in sorted(set(pages), reverse=True):
            if 0 <= i < doc.page_count:
                doc.delete_page(i)
