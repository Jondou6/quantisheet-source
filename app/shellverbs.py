"""Right-click actions in File Explorer (Nov 3, Jon approved Chief's list,
#1): the installer adds, for PDFs, "Open in QuantiSheet" and "Reduce size
(QuantiSheet)"; for Word, Excel, PowerPoint, text and image files
"Convert to PDF (QuantiSheet)"; and for folders "Combine PDFs in
QuantiSheet" (every PDF in the folder, in name order, one set). They run
QuantiSheet.exe with one of the switches below.

Reduce size works without opening the window: it writes "<name>
(reduced).pdf" beside the file and says how much smaller it is. The
others open QuantiSheet with the result in a new tab (not saved until
you save it). Thumbnails / a preview pane handler need a separate Windows
component and aren't part of this."""
import os
import re

REDUCE, CONVERT, COMBINE = "--qs-reduce", "--qs-convert", "--qs-combine-folder"
SWITCHES = (REDUCE, CONVERT, COMBINE)
CONVERT_EXT = (".doc", ".docx", ".rtf", ".odt", ".xls", ".xlsx", ".xlsm",
               ".csv", ".ods", ".ppt", ".pptx", ".odp", ".txt", ".md",
               ".html", ".htm", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
               ".bmp", ".gif")


def parse(argv):
    """(switch, path) when QuantiSheet was started by a right-click
    action, else None."""
    args = list(argv or [])[1:]
    for i, a in enumerate(args):
        if a in SWITCHES and i + 1 < len(args):
            return a, args[i + 1].strip('"')
    return None


def _natural(s):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", s)]


def reduced_name(path):
    stem, _ext = os.path.splitext(path)
    out = f"{stem} (reduced).pdf"
    k = 2
    while os.path.exists(out):
        out = f"{stem} (reduced {k}).pdf"
        k += 1
    return out


def reduce(path):
    """Write a smaller copy beside the file. Returns (out, before, after)
    in bytes. The original is never changed."""
    import fitz
    from . import page_ops
    out = reduced_name(path)
    with fitz.open(path) as d:
        page_ops.compress(d, out)
    return out, os.path.getsize(path), os.path.getsize(out)


def folder_pdfs(folder):
    return sorted((os.path.join(folder, n) for n in os.listdir(folder)
                   if n.lower().endswith(".pdf") and
                   os.path.isfile(os.path.join(folder, n))),
                  key=lambda p: _natural(os.path.basename(p)))


def combine_folder(folder):
    """Every PDF in the folder (not its sub-folders), in name order, as
    one document with a bookmark per file. Returns (doc, files)."""
    import fitz
    files = folder_pdfs(folder)
    out = fitz.open()
    toc = []
    for p in files:
        try:
            with fitz.open(p) as d:
                toc.append([1, os.path.splitext(os.path.basename(p))[0],
                            out.page_count + 1])
                out.insert_pdf(d)
        except Exception:                                 # noqa: BLE001
            continue
    if toc:
        try:
            out.set_toc(toc)
        except Exception:                                 # noqa: BLE001
            pass
    return out, files


def size_text(n):
    return f"{n / 1e6:,.1f} MB" if n >= 1e6 else f"{n / 1e3:,.0f} KB"


def run_in_window(win, switch, path):
    """Open the right-click action's result in the main window. Returns
    the new tab's document (None when there was nothing to open)."""
    from PySide6.QtWidgets import QMessageBox
    name = os.path.basename(path.rstrip("\\/")) or path
    try:
        if switch == COMBINE:
            doc, files = combine_folder(path)
            if not files or not doc.page_count:
                QMessageBox.information(win, "Combine PDFs",
                                        f"There are no PDFs in {name}.")
                return None
            win.open_document(doc, f"{name} - Combined.pdf")
            return doc
        if switch == CONVERT:
            from . import acrobat2
            doc = acrobat2.create_pdf(path)
            win.open_document(doc, os.path.splitext(name)[0] + ".pdf")
            return doc
    except Exception as e:                                # noqa: BLE001
        QMessageBox.warning(win, "QuantiSheet", f"{name}: {e}")
    return None
