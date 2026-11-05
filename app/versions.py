"""Saved revisions of a PDF, kept in a folder beside it (<file>.versions)."""
import difflib
import hashlib
import json
import logging
import os
import re
import time

import fitz

log = logging.getLogger(__name__)


def _vdir(path):
    d = path + ".versions"
    os.makedirs(d, exist_ok=True)
    return d


def _safe_name(name, default="main"):
    """Branch names end up in file names; keep them harmless."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "")).strip("._")
    return name[:40] or default


def _vindex(path):
    p = os.path.join(_vdir(path), "index.json")
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                idx = json.load(f)
            if isinstance(idx, dict) and isinstance(idx.get("revisions"), list):
                return idx
        except (OSError, ValueError):
            log.warning("version index %s is unreadable; starting fresh", p)
    return {"revisions": []}


def _vsave_index(path, idx):
    final = os.path.join(_vdir(path), "index.json")
    tmp = final + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=2)
    os.replace(tmp, final)          # never leaves a half-written index


def save_revision(path, data, label="manual", branch="main"):
    idx = _vindex(path)
    branch = _safe_name(branch)
    rev_id = hashlib.sha256(data + str(time.time_ns()).encode()).hexdigest()[:12]
    fname = f"{branch}_{rev_id}.pdf"
    with open(os.path.join(_vdir(path), fname), "wb") as f:
        f.write(data)
    idx["revisions"].append({
        "id": rev_id, "label": str(label)[:100], "branch": branch,
        "ts": time.time(), "file": fname, "size": len(data)})
    _vsave_index(path, idx)
    return rev_id


def auto_revision(path, data):
    return save_revision(path, data, label="auto")


def prune_auto(path, keep=20):
    idx = _vindex(path)
    autos = sorted((r for r in idx["revisions"] if r.get("label") == "auto"),
                   key=lambda r: r.get("ts", 0))
    drop = autos[:-keep] if len(autos) > keep else []
    for r in drop:
        try:
            os.remove(_rev_file(path, r))
        except (OSError, ValueError):
            pass
    idx["revisions"] = [r for r in idx["revisions"] if r not in drop]
    _vsave_index(path, idx)


def list_revisions(path):
    return _vindex(path)["revisions"]


def _rev_file(path, r):
    # only ever a plain file name inside the versions folder
    name = os.path.basename(str(r.get("file", "")))
    if not name.endswith(".pdf"):
        raise ValueError("bad revision entry")
    return os.path.join(_vdir(path), name)


def load_revision(path, rev_id):
    for r in _vindex(path)["revisions"]:
        if r.get("id") == rev_id:
            with open(_rev_file(path, r), "rb") as f:
                return f.read()
    return None


class _Writer:
    """Writes lines onto as many report pages as needed."""

    def __init__(self, out):
        self.out, self.page, self.y = out, None, 0

    def line(self, text, size=8, color=(0, 0, 0), gap=12):
        if self.page is None or self.y > 760:
            self.page = self.out.new_page(width=612, height=792)
            self.y = 40
        self.page.insert_text((30, self.y), text[:110], fontsize=size,
                              color=color)
        self.y += gap


def compare(a_path, b_path, out_path):
    """Write a PDF listing removed (-) and added (+) lines, page by page."""
    a, b = fitz.open(a_path), fitz.open(b_path)
    out = fitz.open()
    w = _Writer(out)
    try:
        for i in range(max(a.page_count, b.page_count)):
            la = a[i].get_text().splitlines() if i < a.page_count else []
            lb = b[i].get_text().splitlines() if i < b.page_count else []
            w.line(f"PAGE {i + 1}", size=12, gap=20)
            changes = 0
            for d in difflib.ndiff(la, lb):
                if d.startswith("- ") and d[2:].strip():
                    w.line("- " + d[2:], color=(0.8, 0, 0))
                    changes += 1
                elif d.startswith("+ ") and d[2:].strip():
                    w.line("+ " + d[2:], color=(0, 0.5, 0))
                    changes += 1
            if not changes:
                w.line("(no text changes)", color=(0.4, 0.4, 0.4))
            w.y += 10
        if out.page_count == 0:
            w.line("Both documents are empty.")
        out.save(out_path)
    finally:
        out.close()
        a.close()
        b.close()
    return out_path
