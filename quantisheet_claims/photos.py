"""Damage photos on a claim, a room or a line (PM review NW-16).

A photo is copied into <claims folder>/<claim number>.photos/ under its
SHA-256 (the original is never moved or changed); the claim keeps the
hash, the original name, a caption, the date it was taken (from the
photo's own EXIF date when there is one, else the file's date) and the
room or line it shows. verify() reports a photo whose file is missing or
no longer matches its hash. The PDF export prints them on photo pages."""
from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import os
import shutil

from . import model as m
from . import settings

EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".heic", ".webp")


def folder_for(claim, folder: str | None = None) -> str:
    from .store import _safe_name
    base = folder or settings.claims_folder()
    return os.path.join(base, _safe_name(claim.claim_number) + ".photos")


def path_of(claim, photo, folder: str | None = None) -> str:
    return os.path.join(folder_for(claim, folder), photo.sha256 + photo.ext)


def _sha(path) -> str:
    d = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            d.update(b)
    return d.hexdigest()


def taken_date(path) -> str:
    """The EXIF date the photo was taken, else the file's modified date."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex = im.getexif()
            raw = ex.get(36867) or ex.get(306)        # DateTimeOriginal
            if not raw:
                sub = ex.get_ifd(0x8769) if hasattr(ex, "get_ifd") else {}
                raw = sub.get(36867) if sub else None
            if raw:
                return str(raw)[:10].replace(":", "-")
    except Exception:                                     # noqa: BLE001
        pass
    return _dt.date.fromtimestamp(os.path.getmtime(path)).isoformat()


def add(claim, src: str, caption: str = "", line_id: str = "",
        room_id: str = "", folder: str | None = None):
    """A new Claim with the photo at `src` added (copied, never moved)."""
    ext = os.path.splitext(src)[1].lower()
    if ext not in EXTS:
        raise ValueError(f"{os.path.basename(src)}: not a photo "
                         f"({', '.join(EXTS)})")
    if line_id and line_id not in {ln.id for ln in claim.lines}:
        raise ValueError(f"unknown line {line_id!r}")
    if room_id and room_id not in {r.id for r in claim.rooms}:
        raise ValueError(f"unknown room {room_id!r}")
    sha = _sha(src)
    p = m.Photo(id=m.new_id(), sha256=sha, file_name=os.path.basename(src),
                ext=ext, caption=caption.strip(), taken=taken_date(src),
                line_id=line_id, room_id=room_id)
    dest = path_of(claim, p, folder)
    settings.check_safe(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        shutil.copy2(src, dest)
    return dataclasses.replace(claim, photos=claim.photos + (p,))


def remove(claim, photo_id: str):
    """The claim without that photo (its file stays, as other claims or
    revisions may use it)."""
    return dataclasses.replace(
        claim, photos=tuple(p for p in claim.photos if p.id != photo_id))


def verify(claim, folder: str | None = None) -> list[str]:
    """Problems: a photo file missing or changed since it was added."""
    out = []
    for p in claim.photos:
        f = path_of(claim, p, folder)
        if not os.path.exists(f):
            out.append(f"{p.file_name}: the photo file is missing")
        elif _sha(f) != p.sha256:
            out.append(f"{p.file_name}: the photo file was changed")
    return out


def where(claim, photo) -> str:
    if photo.line_id:
        ln = next((x for x in claim.lines if x.id == photo.line_id), None)
        if ln is not None:
            return f"Line {ln.item_code} {ln.description}".strip()
    if photo.room_id:
        r = next((x for x in claim.rooms if x.id == photo.room_id), None)
        if r is not None:
            return f"Room {r.name}"
    return "Claim"


def for_export(claim, folder: str | None = None):
    """((path, caption, taken, where)) of the photos whose files check
    out, for the PDF."""
    out = []
    for p in claim.photos:
        f = path_of(claim, p, folder)
        if os.path.exists(f) and _sha(f) == p.sha256:
            out.append((f, p.caption or p.file_name, p.taken,
                        where(claim, p)))
    return tuple(out)
