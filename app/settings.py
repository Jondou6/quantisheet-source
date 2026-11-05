"""Per-user settings, stored in ~/.quantisheet/settings.json.

DIR is the one per-user data folder (settings, logs, keys, autosave,
catalogs...): everything else uses settings.DIR."""
import builtins
import getpass
import json
import logging
import datetime
import os
import re
import shutil

log = logging.getLogger(__name__)

DIR_NAME = ".quantisheet"
DIR = os.path.join(os.path.expanduser("~"), DIR_NAME)
PATH = os.path.join(DIR, "settings.json")
LOG_NAME = "quantisheet.log"
_cache = None


def _load():
    global _cache
    if _cache is None:
        _cache = {}
        try:
            with open(PATH, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _cache = data
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            log.warning("settings file unreadable; using defaults")
    return _cache


def get(key, default=None):
    return _load().get(key, default)


_MISSING = object()


def set(key, value):
    data = _load()
    old = data.get(key, _MISSING)
    # nothing new: skip the disk write - but only for plain values; a list
    # or dict from get() may have been changed in place by the caller
    if isinstance(value, (bool, int, float, str, type(None))) and \
            type(old) is type(value) and old == value:
        return
    data[key] = value
    try:
        os.makedirs(DIR, exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, PATH)
    except OSError:
        log.warning("could not save settings", exc_info=True)


def author():
    name = get("author")
    if name:
        return name
    try:
        return getpass.getuser()
    except Exception:
        return "User"


# folders the program makes in Temp (every one starts "quantisheet-" or
# "pdfs_ocr_"). Older builds' build check used
# Python's plain mkdtemp()
# name - "tmp" and 8 of [a-z0-9_] - for its smoke.pdf: only that file name
# in such a folder counts, so a real %TEMP%\tmp3dmodels\ is left alone
# (both Oct 18 round-2 reviews).
TEMP_PREFIX = "quantisheet-"
_OWN_TEMP = (TEMP_PREFIX, "pdfs_ocr_")
_PY_TEMP = re.compile(r"tmp[a-z0-9_]{8}$")
_OLD_THROWAWAY = ("smoke.pdf",)


def _is_temp(path):
    """A throwaway file or folder the program itself made in the temp
    folder (the build check's smoke.pdf, compare and recovery copies...),
    or the temp folder itself. Other files in Temp, like a drawing opened
    straight from an email, are real. Also used for folders (last_dir)."""
    import tempfile
    try:
        tmp = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
        tmp = tmp.rstrip("\\/")                    # "T:\\" -> "t:"
        p = os.path.normcase(os.path.realpath(path)).rstrip("\\/")
        if p == tmp:
            return True
        if not p.startswith(tmp + os.sep):
            return False
        parts = p[len(tmp) + 1:].split(os.sep)
        first = parts[0]
        if first.startswith(_OWN_TEMP):
            return True
        return bool(_PY_TEMP.match(first)) and len(parts) == 2 and \
            parts[1] in _OLD_THROWAWAY
    except (OSError, ValueError, TypeError):
        log.debug("not a path: %r", path, exc_info=True)
        return False


def recent(limit=12):
    """Recent files that still exist - never throwaway files from the
    temp folder (the build check's smoke.pdf, combined previews...)."""
    # (this module's own set() saves a setting, so a dict tracks "seen")
    out, seen = [], {}
    for p in get("recent") or []:
        if not isinstance(p, str) or os.path.normcase(p) in seen:
            continue
        if not _is_temp(p) and os.path.exists(p):
            seen[os.path.normcase(p)] = True
            out.append(p)
    return out[:limit]


def remember_recent(path):
    if not path or _is_temp(path):
        return
    items = [p for p in (get("recent") or []) if isinstance(p, str) and
             os.path.normcase(p) != os.path.normcase(path)]
    set("recent", ([path] + items)[:12])
    d = os.path.dirname(path)
    if d:
        set("last_dir", d)


def last_dir():
    """The folder you last opened or saved in (the Open and Save boxes
    start there), else Documents/Desktop."""
    d = get("last_dir")
    if isinstance(d, str) and os.path.isdir(d) and not _is_temp(d):
        return d
    home = os.path.expanduser("~")
    for c in ("Desktop", "Documents", os.path.join("OneDrive", "Desktop"),
              os.path.join("OneDrive", "Documents")):
        if os.path.isdir(os.path.join(home, c)):
            return os.path.join(home, c)
    return home
