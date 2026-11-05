"""The price database, carefully (r36 v2 step 5).

0.13.9's heavy.library() fills an EMPTY price database with the starter
civil library the first time anything reads it, and pricedb.connect()
makes the database file when it isn't there - even to read. The
estimating tools only read, so here:

  * reading() - while it's on, a read of a price database that isn't
    there yet fails quietly (the host's readers then go on with nothing,
    just as with an empty database) instead of making the file;
  * read_civil_library() - the civil library (crews, labor, equipment)
    opened read-only, never filled in;
  * civil_library(ask) - the same, and the starter civil library goes in
    only when ask(question) says Yes;
  * backup() - a copy of the database in the data folder's backups
    folder before a bulk change;
Writes still go through pricedb.connect(write=True), the host's own way
in (shared database, offline copy)."""
import contextlib
import datetime
import json
import logging
import os
import re
import sqlite3

log = logging.getLogger(__name__)

SEED_QUESTION = (
    "Your price database has no civil library yet (no crews, labor or "
    "equipment).\n\nAdd QuantiSheet's starter civil library to your price "
    "database now?\n\nYes: the starter crews, labor and equipment are "
    "added - check them and enter your own rates.\nNo: the price database "
    "is left exactly as it is; civil activities show $0 until you add "
    "crews (Civil Estimate window).")


def path():
    from .. import pricedb
    return pricedb.path()


def exists():
    try:
        return os.path.isfile(path())
    except OSError:
        return False


# ---- reading ---------------------------------------------------------------

_DEPTH = [0]


@contextlib.contextmanager
def reading():
    """Reads inside never make the price database file. Re-entrant."""
    from .. import pricedb
    if _DEPTH[0] or exists():
        _DEPTH[0] += 1
        try:
            yield
        finally:
            _DEPTH[0] -= 1
        return
    real = pricedb.connect

    def connect(write=False):
        if not write and not exists():
            raise pricedb.PriceDBError(
                "no price database yet (not made by a read)")
        return real(write)
    pricedb.connect = connect
    _DEPTH[0] += 1
    try:
        yield
    finally:
        _DEPTH[0] -= 1
        if pricedb.connect is connect:
            pricedb.connect = real


def read_only(fn):
    """A decorator: fn runs inside reading()."""
    import functools

    @functools.wraps(fn)
    def run(*a, **k):
        with reading():
            return fn(*a, **k)
    return run


def _uri(p):
    p = os.path.abspath(p).replace("\\", "/")
    p = p.replace("%", "%25").replace("?", "%3f").replace("#", "%23")
    if re.match(r"^[A-Za-z]:", p):
        p = "/" + p                                   # file:/C:/...
    elif p.startswith("//"):
        p = "//" + p                                  # file:////server/share
    return "file:" + p + "?mode=ro"


def _ro(p):
    con = sqlite3.connect(_uri(p), uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    return con


def _starter_settings():
    from .. import heavy
    try:
        with open(heavy.STARTER, encoding="utf-8") as f:
            return dict(json.load(f).get("settings") or {})
    except (OSError, ValueError, AttributeError):
        return {}


def _read(p):
    from .. import heavy
    out = {k: {} for k in heavy.KINDS}
    settings = None
    con = _ro(p)
    try:
        have = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for kind, table in heavy.KINDS.items():
            if table not in have:
                continue
            for r in con.execute(f"SELECT code, data FROM {table}"):
                try:
                    out[kind][r["code"]] = json.loads(r["data"])
                except (TypeError, ValueError):
                    pass
        if "meta" in have:
            row = con.execute("SELECT value FROM meta WHERE "
                              "key='heavy_settings'").fetchone()
            if row:
                try:
                    settings = json.loads(row["value"])
                except (TypeError, ValueError):
                    settings = {}
    finally:
        con.close()
    return out, settings


def read_civil_library():
    """(library, empty): the civil library as heavy.library() gives it,
    read-only - an empty or missing database is never filled in."""
    from .. import heavy, pricedb
    p = path()
    out, settings = {k: {} for k in heavy.KINDS}, None
    if os.path.isfile(p):
        try:
            out, settings = _read(p)
        except sqlite3.Error as e:
            cache = pricedb.cache_path()
            if pricedb.is_shared(p) and os.path.isfile(cache):
                out, settings = _read(cache)
            else:
                raise pricedb.PriceDBError(
                    f"Can't read the price database {p}: {e}") from e
    empty = not any(out.values()) and settings is None
    out["settings"] = dict(_starter_settings(), **(settings or {}))
    return out, empty


def needs_seed():
    return read_civil_library()[1]


def civil_library(ask=None):
    """The civil library; when the database has none, the starter
    library is added only if ask(SEED_QUESTION) says Yes."""
    from .. import heavy
    lib, empty = read_civil_library()
    if not empty:
        return lib
    if ask is None or not ask(SEED_QUESTION):
        return lib
    return heavy.library()            # the host's starter fill


# ---- writing ------------------------------------------------------------------

def backup(why):
    """A copy of the price database in <data folder>/backups before a
    bulk change; its path, or None when there's no database yet."""
    from . import _io
    p = path()
    if not os.path.isfile(p):
        return None
    tag = re.sub(r"[^A-Za-z0-9-]+", "-", str(why)).strip("-")[:40] or "change"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = _io.data_file("backups", f"prices-before-{tag}-{stamp}.db")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    src = _ro(p)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    finally:
        src.close()
    log.info("price database backed up to %s", dest)
    return dest
