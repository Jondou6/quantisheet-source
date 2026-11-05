"""Back Office's own settings and data folder. Never QuantiSheet's
~/.quantisheet.

Home: QS_BACKOFFICE_HOME if set, else %LOCALAPPDATA%\\QuantiSheetBackOffice
on Windows (not OneDrive: a synced SQLite file can be damaged by the sync
client), else ~/.quantisheet_backoffice. settings.json holds only the PC
level choices (data folder, backup folder, last user); company settings
live in the database.
"""
from __future__ import annotations

import json
import os
import tempfile

_cache: dict | None = None
DEFAULTS = {"data_folder": "", "backup_folder": "", "last_user": "",
            "backup_keep": 30}


class UnsafePathError(RuntimeError):
    """A path inside QuantiSheet's own settings folder was requested."""


def quantisheet_dirs() -> tuple:
    """QuantiSheet's settings folder (~/.quantisheet): only used to REFUSE
    paths in it."""
    home = os.path.expanduser("~")
    return (os.path.realpath(os.path.join(home, ".quantisheet")),)


def check_safe(path: str) -> str:
    rp = os.path.realpath(path)
    for bad in quantisheet_dirs():
        if rp == bad or rp.startswith(bad + os.sep):
            raise UnsafePathError(
                f"refusing to use QuantiSheet's folder: {path}")
    low = os.path.basename(rp).lower()
    if low.startswith("price") and low.endswith((".db", ".sqlite")):
        raise UnsafePathError(f"refusing to open a price database: {path}")
    return path


def home() -> str:
    env = os.environ.get("QS_BACKOFFICE_HOME")
    if env:
        h = env
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        h = os.path.join(os.environ["LOCALAPPDATA"], "QuantiSheetBackOffice")
    else:
        h = os.path.join(os.path.expanduser("~"), ".quantisheet_backoffice")
    return check_safe(h)


def settings_path() -> str:
    return os.path.join(home(), "settings.json")


def reload() -> None:
    global _cache
    _cache = None


def load() -> dict:
    global _cache
    if _cache is None:
        data = dict(DEFAULTS)
        p = settings_path()
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as fh:
                    got = json.load(fh)
                if isinstance(got, dict):
                    data.update(got)
            except (OSError, ValueError):
                pass
        _cache = data
    return _cache


def get(key, default=None):
    return load().get(key, default)


def set(key, value) -> None:  # noqa: A001
    data = load()
    data[key] = value
    atomic_write_json(settings_path(), data)


def data_folder() -> str:
    f = get("data_folder") or os.path.join(home(), "data")
    return check_safe(f)


def backup_folder() -> str:
    f = get("backup_folder") or os.path.join(home(), "backups")
    return check_safe(f)


def db_path() -> str:
    return os.path.join(data_folder(), "backoffice.sqlite")


def onedrive_warning(path: str) -> str:
    """A warning when the data folder sits in a synced folder."""
    low = os.path.realpath(path).lower()
    if "onedrive" in low or "dropbox" in low:
        return ("The database is in a synced folder; keep it on this PC and "
                "copy encrypted backups to the synced folder instead.")
    return ""


def atomic_write_json(path: str, data) -> None:
    check_safe(path)
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
