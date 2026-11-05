"""Open a bid download as a job (Nov 3, Jon approved Chief's list, #3).

A plan room's .zip goes into a job folder: unzipped (zips inside zips
too), every file sorted into Drawings, Specs, Addenda or Other, exact
duplicates kept once, and the drawings combined into one set. Files that
aren't PDFs are kept in Other and listed - nothing is dropped silently.
Sheet naming and scales are then read by the usual Sheet Setup, and the
folder becomes a Project Center job (the window does those two steps).

The zip is only read; entries that would land outside the job folder
(../ paths) are skipped and listed."""
import hashlib
import io
import os
import re
import zipfile

KINDS = ("Drawings", "Specs", "Addenda", "Other")
MAX_DEPTH = 4
MAX_BYTES = 4 * 1024 ** 3            # stop at 4 GB unpacked
_ADD = re.compile(r"\badd(?:endum|enda|\.)?\s*(?:no\.?\s*)?#?\s*\d+|"
                  r"\baddend", re.I)
_SPEC = re.compile(r"\bspec(?:s|ification|ifications)?\b|project\s*manual|"
                   r"\bdiv(?:ision)?\s*\d{1,2}\b|\bsection\s*\d{2}\s?\d{2}",
                   re.I)
_DWG = re.compile(r"\bdrawings?\b|\bplans?\b|\bsheets?\b|\bdwg\b|"
                  r"\b(?:[ACEFGLMPS]|FP)-?\d{2,3}\b|\bset\b", re.I)


class ZipJobError(Exception):
    pass


def _safe_name(name):
    parts = [p for p in re.split(r"[\\/]+", name) if p not in ("", ".")]
    if any(p == ".." for p in parts) or (name[:1] in "\\/") or \
            re.match(r"^[A-Za-z]:", name):
        return None
    return parts


def _walk(data, depth, prefix, out, skipped, budget):
    try:
        z = zipfile.ZipFile(io.BytesIO(data) if isinstance(data, bytes)
                            else data)
    except zipfile.BadZipFile:
        raise ZipJobError("That isn't a zip file (or it is damaged).")
    for info in z.infolist():
        if info.is_dir():
            continue
        parts = _safe_name(info.filename)
        if parts is None:
            skipped.append((prefix + info.filename, "outside the job folder"))
            continue
        budget[0] += info.file_size
        if budget[0] > MAX_BYTES:
            raise ZipJobError("The download unpacks to more than 4 GB.")
        try:
            raw = z.read(info)
        except Exception as e:                            # noqa: BLE001
            skipped.append((prefix + info.filename, f"can't be read ({e})"))
            continue
        rel = prefix + "/".join(parts)
        if parts[-1].lower().endswith(".zip"):
            if depth >= MAX_DEPTH:
                skipped.append((rel, "zip nested too deep"))
                continue
            _walk(raw, depth + 1, rel[:-4] + "/", out, skipped, budget)
            continue
        out.append((rel, raw))


def classify(name, data):
    """Drawings, Specs, Addenda or Other for one file."""
    low = name.lower()
    if not low.endswith(".pdf"):
        return "Other"
    base = os.path.basename(low)
    if _ADD.search(base) or "/addend" in low:
        return "Addenda"
    if _SPEC.search(base) or "/spec" in low:
        return "Specs"
    try:
        import fitz
        d = fitz.open(stream=data, filetype="pdf")
        n = d.page_count
        big = sum(1 for p in d if max(p.rect.width, p.rect.height) > 1100)
        head = " ".join(d[i].get_text("text")[:3000]
                        for i in range(min(4, n))).upper()
        d.close()
    except Exception:                                     # noqa: BLE001
        return "Other"
    if re.search(r"\bADDENDUM\s+(?:NO\.?\s*)?\d", head):
        return "Addenda"
    if re.search(r"\bSECTION\s+\d{2}\s?\d{2}\s?\d{2}\b|PROJECT MANUAL|"
                 r"TABLE OF CONTENTS", head) and big < n / 2:
        return "Specs"
    if big >= max(1, n / 2) or _DWG.search(base):
        return "Drawings"
    return "Other"


def _natural(s):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", s)]


def unpack(zip_path, folder):
    """Unzip into folder/Drawings, Specs, Addenda, Other. Returns
    {"files": {kind: [paths]}, "duplicates": [(name, same as)],
    "not_pdf": [paths], "skipped": [(name, why)]}."""
    out, skipped = [], []
    with open(zip_path, "rb") as f:
        _walk(f.read(), 0, "", out, skipped, [0])
    seen, dups = {}, []
    files = {k: [] for k in KINDS}
    not_pdf = []
    for rel, raw in sorted(out, key=lambda x: _natural(x[0])):
        h = hashlib.sha1(raw).hexdigest()
        if h in seen:
            dups.append((rel, seen[h]))
            continue
        seen[h] = rel
        kind = classify(rel, raw)
        dest_dir = os.path.join(folder, kind)
        os.makedirs(dest_dir, exist_ok=True)
        base = os.path.basename(rel)
        dest = os.path.join(dest_dir, base)
        k = 2
        while os.path.exists(dest):          # same name, other content
            stem, ext = os.path.splitext(base)
            dest = os.path.join(dest_dir, f"{stem} ({k}){ext}")
            k += 1
        with open(dest, "wb") as f:
            f.write(raw)
        files[kind].append(dest)
        if not base.lower().endswith(".pdf"):
            not_pdf.append(dest)
    return {"files": files, "duplicates": dups, "not_pdf": not_pdf,
            "skipped": skipped}


def combine(paths, out_path):
    """The drawings in one set, in file-name order, a bookmark per file.
    Returns (out_path, pages) or (None, 0) with no drawings."""
    import fitz
    if not paths:
        return None, 0
    out = fitz.open()
    toc = []
    for p in sorted(paths, key=lambda x: _natural(os.path.basename(x))):
        try:
            d = fitz.open(p)
        except Exception:                                 # noqa: BLE001
            continue
        toc.append([1, os.path.splitext(os.path.basename(p))[0],
                    out.page_count + 1])
        out.insert_pdf(d)
        d.close()
    if not out.page_count:
        return None, 0
    try:
        out.set_toc(toc)
    except Exception:                                     # noqa: BLE001
        pass
    out.save(out_path, garbage=3, deflate=True)
    n = out.page_count
    out.close()
    return out_path, n


def report_text(rep):
    lines = []
    for k in KINDS:
        fs = rep["files"][k]
        if fs:
            lines.append(f"{k}: {len(fs)} file(s)")
    if rep["duplicates"]:
        lines.append(f"Duplicates kept once: {len(rep['duplicates'])} - " +
                     ", ".join(os.path.basename(a) for a, _b in
                               rep["duplicates"][:6]))
    if rep["not_pdf"]:
        lines.append("Not PDFs (in Other): " + ", ".join(
            os.path.basename(p) for p in rep["not_pdf"][:10]) +
            (" ..." if len(rep["not_pdf"]) > 10 else ""))
    if rep["skipped"]:
        lines.append("Skipped: " + "; ".join(f"{a} ({b})" for a, b in
                                             rep["skipped"][:6]))
    return "\n".join(lines)
