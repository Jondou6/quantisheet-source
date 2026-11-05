"""The module's own settings and folders. Never QuantiSheet's ~/.quantisheet
(brief 3.2).

Home: QUANTISHEET_CLAIMS_HOME if set, else %APPDATA%\\ClaimIT\\ on Windows,
else ~/.claimit/. Claims: Documents\\ClaimIT unless set. settings.json is
written atomically.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import tempfile

log = logging.getLogger(__name__)

_cache: dict | None = None

APP_DIR = "ClaimIT"                     # in %APPDATA%
DOT_DIR = ".claimit"                    # off Windows
DOCS_DIR = "ClaimIT"                    # in Documents

DEFAULTS = {
    "author": "",
    "claims_folder": "",
    "default_op": {
        "residential": {"overhead_bp": 0, "profit_bp": 0, "compound": False,
                        "application": "aggregate"},
        "commercial": {"overhead_bp": 0, "profit_bp": 0, "compound": True,
                       "application": "aggregate"},
    },
    "recent": [],
}


class UnsafePathError(RuntimeError):
    """A path inside QuantiSheet's own settings folder was requested."""


def quantisheet_dirs() -> tuple:
    """QuantiSheet's folder (~/.quantisheet) - only used to REFUSE paths
    inside it."""
    home = os.path.expanduser("~")
    return (os.path.realpath(os.path.join(home, ".quantisheet")),)


def quantisheet_dir() -> str:
    """QuantiSheet's folder (~/.quantisheet)."""
    return quantisheet_dirs()[0]


def check_safe(path: str) -> str:
    rp = os.path.realpath(path)
    for bad in quantisheet_dirs():
        if rp == bad or rp.startswith(bad + os.sep):
            raise UnsafePathError(
                f"refusing to use QuantiSheet's folder: {path}")
    return path


def home() -> str:
    env = os.environ.get("QUANTISHEET_CLAIMS_HOME")
    if env:
        h = env
    elif os.name == "nt" and os.environ.get("APPDATA"):
        h = os.path.join(os.environ["APPDATA"], APP_DIR)
    else:
        h = os.path.join(os.path.expanduser("~"), DOT_DIR)
    check_safe(h)
    try:
        os.makedirs(h, exist_ok=True)
    except OSError:
        log.warning("ClaimIT settings folder %s not ready", h, exc_info=True)
    return h


def settings_path() -> str:
    return os.path.join(home(), "settings.json")


def prices_path() -> str:
    """The module's own price list - never QuantiSheet's prices.db."""
    return os.path.join(home(), "prices.json")


def _known_documents():
    """The Documents folder Windows shows the user (OneDrive's when its
    folder backup is on), or "" off Windows. CSIDL_PERSONAL (5) follows
    folder redirection."""
    if os.name != "nt":
        return ""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:
            return buf.value
    except Exception:                                     # noqa: BLE001
        pass
    return ""


def _documents() -> str:
    """~/Documents, unless only the Documents folder Windows shows (e.g.
    OneDrive\\Documents) is in use: an existing ~/Documents\\ClaimIT keeps
    being used, so no one's claims seem to disappear (r47 #15)."""
    home_ = os.path.expanduser("~")
    plain = os.path.join(home_, "Documents")
    if os.path.isdir(os.path.join(plain, DOCS_DIR)):
        return plain
    known = _known_documents()
    # only a folder inside this user's home (tests and odd setups point
    # HOME elsewhere; never fall through to the real profile)
    if known and os.path.normcase(os.path.abspath(known)).startswith(
            os.path.normcase(os.path.abspath(home_)) + os.sep):
        return known
    return plain


def claims_folder() -> str:
    f = load().get("claims_folder")
    if not f:
        if os.environ.get("QUANTISHEET_CLAIMS_HOME"):
            f = os.path.join(home(), "Claims")
        else:
            f = os.path.join(_documents(), DOCS_DIR)
            try:
                os.makedirs(f, exist_ok=True)
            except OSError:
                log.warning("claims folder %s not ready", f, exc_info=True)
    return check_safe(f)


def exports_folder() -> str:
    return os.path.join(claims_folder(), "Exports")


def reload() -> None:
    global _cache
    _cache = None


def load() -> dict:
    global _cache
    if _cache is None:
        data = json.loads(json.dumps(DEFAULTS))
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


def set(key, value) -> None:  # noqa: A001 - mirrors app/settings.py naming
    data = load()
    data[key] = value
    atomic_write_json(settings_path(), data)


def author() -> str:
    a = (load().get("author") or "").strip()
    if a:
        return a
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


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
