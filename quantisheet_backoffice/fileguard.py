"""Refuses QuickBooks company files on every import and export path.

Back Office never reads or writes .QBW/.QBB/.QBM/.QBX company files and
uses no Intuit API: the user exports from QuickBooks with QuickBooks' own
export (IIF or Export data files) and Back Office reads that file.
"""
from __future__ import annotations

import os

COMPANY_EXTS = (".qbw", ".qbb", ".qbm", ".qbx", ".qbw.tlg", ".qbw.nd")
MESSAGE = ("QuantiSheet does not open QuickBooks company files; export IIF "
           "or Export data files from QuickBooks first")
TRADEMARK_NOTICE = ("QuickBooks is a trademark of Intuit Inc. QuantiSheet is "
                    "not affiliated with or endorsed by Intuit.")


class CompanyFileError(ValueError):
    pass


def is_company_file(path) -> bool:
    return os.fspath(path).lower().endswith(COMPANY_EXTS)


def refuse_company_file(path) -> None:
    """Call before opening any user-chosen file (import or export)."""
    if is_company_file(path):
        raise CompanyFileError(MESSAGE)


# ---- safe output names and cells (review fixes) --------------------------

import re as _re                                         # noqa: E402

_BAD_CHARS = _re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_PLAIN_NUMBER = _re.compile(r"^[+-]?\d+(\.\d+)?$")


class UnsafeNameError(ValueError):
    pass


def safe_name(text, default="file", max_len=120) -> str:
    """A file name built from user data (invoice number, customer, job):
    no path separators, ':' or other characters Windows refuses, no '..',
    no leading/trailing dots or spaces, never a reserved device name."""
    s = _BAD_CHARS.sub("-", str(text or ""))
    s = _re.sub(r"\.{2,}", ".", s)
    s = _re.sub(r"-{2,}", "-", s)
    s = s.strip(" .-")
    if not s:
        return default
    stem = s.split(".")[0].upper().strip()
    if stem in _RESERVED:
        s = "_" + s
    if len(s) > max_len:
        root, dot, ext = s.rpartition(".")
        s = (root[:max_len - len(ext) - 1] + "." + ext) if dot and \
            len(ext) <= 8 else s[:max_len]
    return s


def safe_path(folder, name, subdir="") -> str:
    """folder/[subdir/]safe_name(name), refused unless it stays inside
    folder."""
    base = os.path.realpath(folder)
    target = os.path.realpath(os.path.join(base, subdir, safe_name(name)))
    if not (target.startswith(base + os.sep)):
        raise UnsafeNameError(f"{name!r} would be written outside {folder}")
    refuse_company_file(target)
    return target


def write_target(path) -> str:
    """Every user-chosen output file goes through here: never a QuickBooks
    company file, never QuantiSheet's settings folder."""
    from . import settings
    refuse_company_file(path)
    settings.check_safe(path)
    return path


def safe_cell(v):
    """CSV / Excel formula injection guard: text starting with = + - @
    tab or CR gets a leading apostrophe. Plain numbers (-312.47, +5) and
    non-text values are left alone."""
    if not isinstance(v, str) or not v:
        return v
    if v.startswith(_FORMULA_START) and not _PLAIN_NUMBER.match(v):
        return "'" + v
    return v


def safe_row(row):
    return [safe_cell(v) for v in row]
