"""One JSON file per claim (<claim number>.claim.json), atomic save,
last 10 copies kept in .backup/. Lives in the module's claims folder,
never in QuantiSheet's folders (brief 3.2)."""
from __future__ import annotations

import dataclasses
import os
import re
import shutil
import typing
from datetime import datetime
from decimal import Decimal

from . import settings

# 2 (ClaimIT 0.2): diary and payments. A 0.1 program refuses a version-2
# file instead of opening it and dropping them on save; 0.2 reads both.
SCHEMA_VERSION = 2
# 3: a room has odd-shape parts, or the claim has contents (0.2.2). Written only then, so ClaimIT
# 0.2.1 refuses such a file instead of opening it without the parts.
SCHEMA_SHAPED = 3
READABLE = (1, 2, 3)
KEEP_BACKUPS = 10


def to_jsonable(obj):
    if dataclasses.is_dataclass(obj):
        return {f.name: to_jsonable(getattr(obj, f.name))
                for f in dataclasses.fields(obj)}
    if isinstance(obj, (tuple, list)):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, float):
        raise TypeError("floats are not stored")
    return obj


def from_jsonable(tp, data):
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is typing.Union or (origin is not None and
                                  str(origin) == "<class 'types.UnionType'>"):
        if data is None:
            return None
        real = [a for a in args if a is not type(None)]
        return from_jsonable(real[0], data)
    if origin is tuple:
        return tuple(from_jsonable(args[0], x) for x in (data or []))
    if dataclasses.is_dataclass(tp):
        hints = typing.get_type_hints(tp)
        kw = {}
        for f in dataclasses.fields(tp):
            if f.name in data:
                kw[f.name] = from_jsonable(hints[f.name], data[f.name])
        return tp(**kw)
    if tp is Decimal:
        return Decimal(str(data))
    if tp is int:
        if isinstance(data, bool) or not isinstance(data, int):
            raise ValueError(f"expected a whole number, got {data!r}")
        return data
    if tp is bool:
        return bool(data)
    if tp is str:
        return "" if data is None else str(data)
    return data


def _safe_name(claim_number: str) -> str:
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", claim_number or "").strip(" .")
    return n or "untitled"


def path_for(claim, folder: str | None = None) -> str:
    folder = folder or settings.claims_folder()
    return os.path.join(folder, _safe_name(claim.claim_number) + ".claim.json")


def save(claim, revisions=(), folder: str | None = None) -> str:
    p = path_for(claim, folder)
    settings.check_safe(p)
    if os.path.exists(p):
        bdir = os.path.join(os.path.dirname(p), ".backup")
        os.makedirs(bdir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(p, os.path.join(bdir, f"{os.path.basename(p)}.{stamp}"))
        olds = sorted(x for x in os.listdir(bdir)
                      if x.startswith(os.path.basename(p) + "."))
        for x in olds[:-KEEP_BACKUPS]:
            os.unlink(os.path.join(bdir, x))
    settings.atomic_write_json(p, {
        "schema_version": (SCHEMA_SHAPED if _shaped(claim, revisions)
                           else SCHEMA_VERSION),
        "claim": to_jsonable(claim),
        "revisions": [to_jsonable(r) for r in revisions],
    })
    return p


def _shaped(claim, revisions) -> bool:
    """Anything ClaimIT 0.2.1 would drop without a word - an odd-shaped
    room or a contents list - in the claim or a saved revision."""
    cs = [claim] + [v.claim for v in revisions]
    return any(c.contents or c.contents_cov != type(c.contents_cov)()
               or any(r.parts for r in c.rooms) for c in cs)


def claim_id_in(path: str):
    """The id of the claim saved at path, or None (no file, or not a
    claim file) - so a save never replaces a different claim."""
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return str(data["claim"]["id"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def load(path: str):
    """-> (Claim, [Revision])"""
    import json
    from .model import Claim
    from .revision import Revision
    settings.check_safe(path)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("claim"), dict):
        raise ValueError("not a ClaimIT claim file")
    if data.get("schema_version") not in READABLE:
        raise ValueError(f"unsupported claim file schema "
                         f"{data.get('schema_version')!r}")
    claim = from_jsonable(Claim, data["claim"])
    revs = [from_jsonable(Revision, r) for r in data.get("revisions", [])]
    return claim, revs
