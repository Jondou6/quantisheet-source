import os

from . import safeio
import fitz


def images_to_pdf(paths, out):
    """One page per image, each page the size of its image."""
    doc = fitz.open()
    try:
        for p in paths:
            img = fitz.open(p)
            try:
                rect = img[0].rect
            finally:
                img.close()
            page = doc.new_page(width=rect.width, height=rect.height)
            page.insert_image(page.rect, filename=p)
        doc.save(out, garbage=safeio.gc_level(doc), deflate=True)
    finally:
        doc.close()
    return out


def pdf_to_images(path, out_dir, dpi=150):
    os.makedirs(out_dir, exist_ok=True)
    doc = fitz.open(path)
    made = []
    try:
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            fp = os.path.join(out_dir, f"page_{i + 1:03d}.png")
            pix.save(fp)
            made.append(fp)
    finally:
        doc.close()
    return made
