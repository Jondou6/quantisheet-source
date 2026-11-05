"""The price database: cost books, labor rates, your own catalogs and bid
tab history in one SQLite file that can live on an office network folder
(a server or NAS share - not OneDrive/Dropbox, which corrupt databases
while syncing).

* Several estimators can read it at once; saves are short transactions, so
  one person saves at a time (the others wait a few seconds).
* Every price change is kept in a history table (who, when, old -> new).
* Editing checks that nobody changed the same item since you opened it.
* A copy is kept on this PC; if the network folder can't be reached the
  copy is used read-only and saving is refused until it's back.

Settings > "price_db" holds the file's location (default
~/.quantisheet/prices.db).
"""
import contextlib
import datetime as _dt
import getpass
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time

from . import settings

log = logging.getLogger(__name__)

SCHEMA = 3
# the file's name in a folder chosen for it (Use a Network Folder)
FILENAME = "QuantiSheet Prices.db"
ITEM_FIELDS = ("desc", "unit", "material", "labor", "crew", "sub", "type",
               "basis", "source", "equipment", "edition", "imported",
               "license")
NUMERIC = ("material", "labor", "sub", "equipment")
# fields older versions had: a book's content hash covers these always and
# the newer ones only when they're filled in, so a book saved before the
# Equipment $ column hashes (and so updates) exactly as it did
HASH_FIELDS = ITEM_FIELDS[:9]
# an item imported from a licensed price list carries license "local-only"
# and its book "local_only": it may live only in this PC's own price
# database (never a shared one, never the shipped books)
LOCAL_ONLY = "local-only"
LOCATION_BOOK = "Location Factors"   # history rows for the factors table
LOCATION_FIELDS = ("state", "cities", "zips", "materials", "labor",
                   "equipment", "source")

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS books (
    name TEXT PRIMARY KEY, effective TEXT, region TEXT, escalation REAL,
    notes TEXT, version TEXT, index_json TEXT, regions_json TEXT,
    created TEXT, modified TEXT, modified_by TEXT);
CREATE TABLE IF NOT EXISTS rates (
    book TEXT, region TEXT, trade TEXT, rate REAL,
    PRIMARY KEY (book, region, trade));
CREATE TABLE IF NOT EXISTS items (
    book TEXT, code TEXT, desc TEXT, unit TEXT, material REAL, labor REAL,
    crew TEXT, sub REAL, type TEXT, basis TEXT, source TEXT,
    modified TEXT, modified_by TEXT, PRIMARY KEY (book, code));
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT, book TEXT, code TEXT, field TEXT,
    old TEXT, new TEXT, at TEXT, by TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS history_book ON history (book, code);
CREATE TABLE IF NOT EXISTS catalogs (
    name TEXT PRIMARY KEY, csv TEXT, modified TEXT, modified_by TEXT);
CREATE TABLE IF NOT EXISTS bid_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, owner TEXT,
    location TEXT, state TEXT, bid_date TEXT, source TEXT, notes TEXT,
    added TEXT, added_by TEXT);
CREATE TABLE IF NOT EXISTS bid_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT, project INTEGER, bidder TEXT,
    item_no TEXT, desc TEXT, unit TEXT, qty REAL, price REAL, trade TEXT);
CREATE INDEX IF NOT EXISTS bid_rows_project ON bid_rows (project);
CREATE TABLE IF NOT EXISTS vocab_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT, canonical TEXT NOT NULL,
    unit TEXT NOT NULL, trade TEXT, code TEXT, created TEXT,
    created_by TEXT, UNIQUE (canonical, unit));
CREATE TABLE IF NOT EXISTS vocab_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT, item INTEGER NOT NULL,
    text TEXT, norm TEXT NOT NULL, source TEXT, hits INTEGER DEFAULT 0,
    UNIQUE (item, norm));
CREATE INDEX IF NOT EXISTS vocab_alias_norm ON vocab_aliases (norm);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY, number TEXT UNIQUE, name TEXT, client TEXT,
    type TEXT, estimator TEXT, book TEXT, region TEXT, bid_date TEXT,
    status TEXT, bid_total TEXT, contract TEXT, closed TEXT, folder TEXT,
    file TEXT, added TEXT, added_by TEXT);
CREATE TABLE IF NOT EXISTS job_lines (
    id INTEGER PRIMARY KEY, job INTEGER, code TEXT, desc TEXT, unit TEXT,
    est_qty TEXT, est_unit_cost TEXT, act_qty TEXT, act_cost TEXT,
    source TEXT);
CREATE INDEX IF NOT EXISTS job_lines_job ON job_lines (job);
CREATE TABLE IF NOT EXISTS unit_cost_obs (
    id INTEGER PRIMARY KEY, code TEXT, unit TEXT, unit_cost TEXT, qty TEXT,
    job INTEGER, date TEXT, region TEXT, kind TEXT, source TEXT,
    added_by TEXT);
CREATE INDEX IF NOT EXISTS obs_code ON unit_cost_obs (code, date);
CREATE TABLE IF NOT EXISTS heavy_equipment (
    code TEXT PRIMARY KEY, data TEXT, modified TEXT, modified_by TEXT,
    note TEXT);
CREATE TABLE IF NOT EXISTS heavy_labor (
    code TEXT PRIMARY KEY, data TEXT, modified TEXT, modified_by TEXT,
    note TEXT);
CREATE TABLE IF NOT EXISTS heavy_crews (
    code TEXT PRIMARY KEY, data TEXT, modified TEXT, modified_by TEXT,
    note TEXT);
CREATE TABLE IF NOT EXISTS heavy_activities (
    code TEXT PRIMARY KEY, data TEXT, modified TEXT, modified_by TEXT,
    note TEXT);
CREATE TABLE IF NOT EXISTS heavy_masters (
    code TEXT PRIMARY KEY, data TEXT, modified TEXT, modified_by TEXT,
    note TEXT);
CREATE TABLE IF NOT EXISTS production_obs (
    id INTEGER PRIMARY KEY, code TEXT, unit TEXT, qty TEXT,
    crew_hours TEXT, rate TEXT, job TEXT, date TEXT, conditions TEXT,
    source TEXT, added_by TEXT);
CREATE INDEX IF NOT EXISTS prod_code ON production_obs (code, date);
CREATE TABLE IF NOT EXISTS location_factors (
    region TEXT PRIMARY KEY, state TEXT, cities TEXT, zips TEXT,
    materials REAL, labor REAL, equipment REAL, source TEXT,
    deleted INTEGER DEFAULT 0, modified TEXT, modified_by TEXT);
CREATE TABLE IF NOT EXISTS vocab_review (
    id INTEGER PRIMARY KEY AUTOINCREMENT, project INTEGER, desc TEXT,
    unit TEXT, item INTEGER, score REAL, reason TEXT,
    status TEXT DEFAULT 'open', created TEXT, decided_by TEXT);
"""


class PriceDBError(RuntimeError):
    pass


class Conflict(PriceDBError):
    """Someone else changed an item you were editing."""

    def __init__(self, items):
        self.items = items
        super().__init__(
            f"{len(items)} item(s) were changed by someone else since you "
            "opened them: " + ", ".join(
                f"{c} ({who}, {at[:16]})" for c, who, at in items[:6]))


# ---- location -----------------------------------------------------------------

def managed():
    """The IT department set the database location (policy.py)."""
    from . import policy
    return policy.get("PriceDatabasePath")


def path():
    p = managed() or settings.get("price_db")
    return p if p else os.path.join(settings.DIR, "prices.db")


def file_in(folder):
    """The database file in `folder`: QuantiSheet Prices.db."""
    return os.path.join(folder, FILENAME)


def cache_path():
    return os.path.join(settings.DIR, "prices-local-copy.db")


def is_shared(p=None):
    p = os.path.normcase(os.path.abspath(p or path()))
    return not p.startswith(os.path.normcase(os.path.abspath(settings.DIR)))


def sync_folder_warning(p):
    """A reason not to put the database at `p`, or ''."""
    low = os.path.abspath(p).lower().replace("\\", "/")
    for word in ("onedrive", "dropbox", "google drive", "googledrive",
                 "icloud", "box sync", "/box/"):
        if word in low:
            return (f"{p} is in a {word.title().strip('/')} folder. Sync "
                    "services copy the file while it's being written and "
                    "can corrupt it. Use a network share (\\\\server\\"
                    "folder or a mapped drive) instead.")
    return ""


def user():
    try:
        from . import proposal
        name = proposal.company().get("estimator", "")
    except Exception:
        name = ""
    if not name:
        try:
            name = getpass.getuser()
        except Exception:
            name = "unknown"
    return name


def now():
    return _dt.datetime.now().isoformat(timespec="microseconds")


# ---- connections --------------------------------------------------------------

state = {"offline": "", "copied": 0.0, "left_out": []}


def _open(p, readonly=False):
    if readonly:
        uri = "file:" + p.replace("\\", "/") + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=15)
    else:
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        con = sqlite3.connect(p, timeout=15)
    con.row_factory = sqlite3.Row
    # rollback journal, not WAL: WAL needs shared memory, which network
    # shares don't provide
    if not readonly:
        con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA busy_timeout=15000")
    return con


EXTRA = ("escalation_by_div", "escalation_source", "local_only",
         "license_note")


class LocalOnlyError(PriceDBError):
    """A licensed (local-only) book can't go into a shared database."""


def _init(con):
    con.executescript(DDL)
    cols = {r[1] for r in con.execute("PRAGMA table_info(books)")}
    if "extra_json" not in cols:
        con.execute("ALTER TABLE books ADD COLUMN extra_json TEXT")
    cols = {r[1] for r in con.execute("PRAGMA table_info(items)")}
    if "sizes" not in cols:          # price by size (pipe diameter), JSON
        con.execute("ALTER TABLE items ADD COLUMN sizes TEXT")
    # Equipment $ apart from material, and where an imported price came
    # from (edition, import date, licence); old rows read as 0 / blank
    for col, kind in (("equipment", "REAL"), ("edition", "TEXT"),
                      ("imported", "TEXT"), ("license", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE items ADD COLUMN {col} {kind}")
    cols = {r[1] for r in con.execute("PRAGMA table_info(bid_rows)")}
    if "note" not in cols:          # "included" for INCL lines
        con.execute("ALTER TABLE bid_rows ADD COLUMN note TEXT")
    # our own bid's result (Won / Lost / Pending / No bid) for the
    # Estimating Dashboard's hit rate; older jobs read as blank
    cols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
    if "result" not in cols:
        con.execute("ALTER TABLE jobs ADD COLUMN result TEXT")
    row = con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    if row is None:
        con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)",
                    (str(SCHEMA),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('created', ?)",
                    (now(),))
    else:
        try:
            have = int(row["value"])
        except (TypeError, ValueError):
            have = 1
        if have > SCHEMA:
            con.rollback()
            con.close()
            raise PriceDBError(
                f"This price database was made by a newer QuantiSheet "
                f"(format {have}; this one reads up to {SCHEMA}). Update "
                "QuantiSheet on this computer.")
        if have < SCHEMA:
            # 1 -> 2: job history tables; 2 -> 3: heavy civil libraries
            # and production history (all created above); nothing to move.
            # (The activity library and master estimates were added to
            # format 3 as new tables; older 3s simply don't see them.)
            con.execute("UPDATE meta SET value=? WHERE key='schema'",
                        (str(SCHEMA),))
            con.execute("INSERT OR REPLACE INTO meta VALUES ('migrated', ?)",
                        (f"{have}->{SCHEMA} {now()}",))
    from . import oldnames                 # a book saved under the old name
    oldnames.convert_price_db(con)
    con.commit()


def _refresh_copy(force=False):
    """Keep a local copy of a shared database (at most every 5 minutes)."""
    if not is_shared() or (not force and time.time() - state["copied"] < 300):
        return
    try:
        src = _open(path())
        dst = sqlite3.connect(cache_path())
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        state["copied"] = time.time()
    except Exception:
        log.warning("couldn't refresh the local copy of the price database",
                    exc_info=True)


@contextlib.contextmanager
def connect(write=False):
    """A connection to the price database (the local copy, read-only, if
    the shared one can't be reached)."""
    p = path()
    con = None
    try:
        folder = os.path.dirname(os.path.abspath(p))
        if not is_shared(p):
            os.makedirs(folder, exist_ok=True)
        elif not os.path.isdir(folder):
            raise sqlite3.OperationalError(f"folder not found: "
                                           f"{os.path.dirname(p)}")
        con = _open(p)
        _init(con)
        state["offline"] = ""
    except sqlite3.Error as e:
        if not is_shared(p) or not os.path.exists(cache_path()):
            raise PriceDBError(f"Can't open the price database {p}: {e}")
        state["offline"] = (f"The price database {p} can't be reached ({e}); "
                            "using the copy on this PC, read-only.")
        if write:
            raise PriceDBError(state["offline"].replace(
                "read-only.", "read-only, so changes can't be saved now."))
        con = _open(cache_path(), readonly=True)
    try:
        yield con
        if write:
            con.commit()
    except Exception:
        if write:
            con.rollback()
        raise
    finally:
        con.close()
    if write or not state["copied"]:
        _refresh_copy(force=write)


def meta(key, default=None):
    with connect() as con:
        r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r and r[0] and r[0][:1] in "[{\"" \
        else (r[0] if r else default)


def set_meta(key, value):
    with connect(write=True) as con:
        con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                    (key, json.dumps(value) if not isinstance(value, str)
                     else value))


# ---- books ---------------------------------------------------------------------

def book_names():
    with connect() as con:
        return [r[0] for r in con.execute(
            "SELECT name FROM books ORDER BY name COLLATE NOCASE")]


def book_stamp(name):
    with connect() as con:
        r = con.execute("SELECT modified FROM books WHERE name=?",
                        (name,)).fetchone()
    return r[0] if r else None


_BOOK_CACHE = {}


def load_book(name):
    """The book as the dict costbook.Book takes, or None. Each item also
    carries "modified" / "modified_by"."""
    from . import oldnames                 # a name saved before the rename
    name = oldnames.new_book_name(name)
    with connect() as con:
        b = con.execute("SELECT * FROM books WHERE name=?", (name,)).fetchone()
        if b is None:
            return None
        hit = _BOOK_CACHE.get((path(), name))
        if hit and hit[0] == b["modified"]:
            return json.loads(hit[1])
        data = {"name": b["name"], "effective": b["effective"],
                "region": b["region"], "escalation": b["escalation"],
                "notes": b["notes"] or "", "version": b["version"] or "",
                "index": json.loads(b["index_json"] or "{}"),
                "regions": json.loads(b["regions_json"] or "{}"),
                "modified": b["modified"], "modified_by": b["modified_by"],
                "rates": {}, "items": {}}
        try:
            data.update(json.loads(b["extra_json"] or "{}"))
        except (IndexError, KeyError, ValueError):
            pass
        for r in con.execute("SELECT region, trade, rate FROM rates WHERE "
                             "book=?", (name,)):
            data["rates"].setdefault(r[0], {})[r[1]] = r[2]
        for r in con.execute("SELECT * FROM items WHERE book=?", (name,)):
            have = r.keys()
            data["items"][r["code"]] = {
                **{k: r[k] for k in ITEM_FIELDS if k in have and
                   r[k] not in (None, "") and
                   not (k in NEW_FIELDS and not r[k])},
                "modified": r["modified"], "modified_by": r["modified_by"]}
            if r["sizes"]:
                try:
                    data["items"][r["code"]]["sizes"] = json.loads(
                        r["sizes"])
                except ValueError:
                    pass
    _BOOK_CACHE[(path(), name)] = (data["modified"], json.dumps(data))
    return data


NEW_FIELDS = ITEM_FIELDS[9:]
ITEM_INSERT = ("INSERT OR REPLACE INTO items (book, code, desc, unit, "
               "material, labor, crew, sub, type, basis, source, modified, "
               "modified_by, sizes, equipment, edition, imported, license) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")


def _sizes_json(v):
    if isinstance(v, str):
        return v
    return json.dumps(v, sort_keys=True) if v else ""


def _item_row(book, code, it, stamp, who):
    return (book, code, str(it.get("desc", "")), str(it.get("unit", "")),
            float(it.get("material") or 0), float(it.get("labor") or 0),
            str(it.get("crew") or ""), float(it.get("sub") or 0),
            str(it.get("type") or ""), str(it.get("basis") or ""),
            str(it.get("source") or ""), stamp, who,
            _sizes_json(it.get("sizes")), float(it.get("equipment") or 0),
            str(it.get("edition") or ""), str(it.get("imported") or ""),
            str(it.get("license") or ""))


def _same(a, b, k):
    if k in NUMERIC:
        return abs(float(a or 0) - float(b or 0)) < 1e-9
    return str(a or "") == str(b or "")


def save_book(data, note="", history=True):
    """Write a whole book (a costbook.Book.to_dict()); changed prices are
    logged. Returns the number of items whose price changed."""
    name = data["name"]
    refuse_local_only(data)
    stamp, who = now(), user()
    changed = 0
    with connect(write=True) as con:
        old = {r["code"]: r for r in con.execute(
            "SELECT * FROM items WHERE book=?", (name,))}
        exists = con.execute("SELECT created FROM books WHERE name=?",
                             (name,)).fetchone()
        old_book = con.execute("SELECT escalation, extra_json FROM books "
                               "WHERE name=?", (name,)).fetchone()
        extra = {k: data[k] for k in EXTRA if data.get(k)}
        con.execute(
            "INSERT OR REPLACE INTO books (name, effective, region, "
            "escalation, notes, version, index_json, regions_json, created, "
            "modified, modified_by, extra_json) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, data.get("effective"), data.get("region"),
             float(data.get("escalation") or 0), data.get("notes") or "",
             data.get("version") or "", json.dumps(data.get("index") or {}),
             json.dumps(data.get("regions") or {}),
             exists[0] if exists else stamp, stamp, who,
             json.dumps(extra)))
        con.execute("DELETE FROM rates WHERE book=?", (name,))
        con.executemany("INSERT INTO rates VALUES (?,?,?,?)", [
            (name, reg, t, float(v))
            for reg, tr in (data.get("rates") or {}).items()
            for t, v in tr.items()])
        items = data.get("items") or {}
        log_rows, rows = [], []
        if history and old_book is not None:
            was = (old_book[0], old_book[1] or "{}")
            now_ = (float(data.get("escalation") or 0), json.dumps(extra))
            if abs(float(was[0] or 0) - now_[0]) > 1e-12 or \
                    json.loads(was[1]) != extra:
                log_rows.append((name, "", "escalation",
                                 f"{float(was[0] or 0):g} {was[1]}",
                                 f"{now_[0]:g} {now_[1]}", stamp, who,
                                 note))
        for code, it in items.items():
            o = old.get(code)
            diff = [] if o is None else [
                k for k in ITEM_FIELDS if not _same(o[k], it.get(k), k)]
            if o is not None and (o["sizes"] or "") != \
                    _sizes_json(it.get("sizes")):
                diff.append("sizes")
            if o is not None and not diff:
                continue           # unchanged: keep its stamp
            rows.append(_item_row(name, code, it, stamp, who))
            if o is not None:
                if any(k in NUMERIC or k == "crew" for k in diff):
                    changed += 1
                if history:
                    log_rows += [(name, code, k, str(o[k]), str(it.get(k)),
                                  stamp, who, note) for k in diff]
        con.executemany(ITEM_INSERT, rows)
        gone = [c for c in old if c not in items]
        con.executemany("DELETE FROM items WHERE book=? AND code=?",
                        [(name, c) for c in gone])
        if history:
            log_rows += [(name, c, "removed", "", "", stamp, who, note)
                         for c in gone]
            if exists is None:
                log_rows.append((name, "", "created", "", f"{len(items)} "
                                 "items", stamp, who, note))
        con.executemany("INSERT INTO history (book, code, field, old, new, "
                        "at, by, note) VALUES (?,?,?,?,?,?,?,?)", log_rows)
    return changed


def update_items(name, changes, loaded=None, note=""):
    """Change some items: {code: {field: value}}. `loaded` = {code:
    modified stamp when you opened it}; if any of those were changed since
    by someone else, nothing is saved and Conflict is raised."""
    stamp, who = now(), user()
    with connect(write=True) as con:
        if con.execute("SELECT 1 FROM books WHERE name=?",
                       (name,)).fetchone() is None:
            raise PriceDBError(f"No cost book named {name}.")
        clash = []
        cur = {}
        for code in changes:
            r = con.execute("SELECT * FROM items WHERE book=? AND code=?",
                            (name, code)).fetchone()
            cur[code] = r
            if loaded and code in loaded and r is not None and \
                    r["modified"] != loaded[code]:
                clash.append((code, r["modified_by"] or "?",
                              r["modified"] or ""))
        if clash:
            raise Conflict(clash)
        logs = []
        for code, fields in changes.items():
            r = cur[code]
            it = {k: (r[k] if r is not None else None) for k in ITEM_FIELDS}
            for k, v in fields.items():
                if k not in ITEM_FIELDS:
                    continue
                if k in NUMERIC:
                    v = float(v or 0)
                if r is None or not _same(it[k], v, k):
                    logs.append((name, code, k, "" if r is None else
                                 str(it[k]), str(v), stamp, who, note))
                it[k] = v
            if r is not None and r["sizes"]:
                it["sizes"] = r["sizes"]          # keep the size table
            con.execute(ITEM_INSERT, _item_row(name, code, it, stamp, who))
        con.execute("UPDATE books SET modified=?, modified_by=? WHERE name=?",
                    (stamp, who, name))
        con.executemany("INSERT INTO history (book, code, field, old, new, "
                        "at, by, note) VALUES (?,?,?,?,?,?,?,?)", logs)
    return len(logs)


def update_rates(name, rates, index=None, note=""):
    """Change labor rates {region: {trade: $/hr}} (and materials index
    {region: x}); logged in the history as code "rate:<region>"."""
    stamp, who = now(), user()
    with connect(write=True) as con:
        b = con.execute("SELECT index_json FROM books WHERE name=?",
                        (name,)).fetchone()
        if b is None:
            raise PriceDBError(f"No cost book named {name}.")
        logs = []
        for reg, tr in (rates or {}).items():
            for t, v in tr.items():
                o = con.execute("SELECT rate FROM rates WHERE book=? AND "
                                "region=? AND trade=?", (name, reg, t)
                                ).fetchone()
                if o is None or abs(o[0] - float(v)) > 1e-9:
                    logs.append((name, f"rate:{reg}", t,
                                 "" if o is None else str(o[0]), str(v),
                                 stamp, who, note))
                    con.execute("INSERT OR REPLACE INTO rates VALUES "
                                "(?,?,?,?)", (name, reg, t, float(v)))
        if index:
            idx = json.loads(b[0] or "{}")
            for reg, v in index.items():
                if abs(float(idx.get(reg, 1.0)) - float(v)) > 1e-9:
                    logs.append((name, f"index:{reg}", "materials index",
                                 str(idx.get(reg, "")), str(v), stamp, who,
                                 note))
                    idx[reg] = float(v)
            con.execute("UPDATE books SET index_json=? WHERE name=?",
                        (json.dumps(idx), name))
        con.execute("UPDATE books SET modified=?, modified_by=? WHERE name=?",
                    (stamp, who, name))
        con.executemany("INSERT INTO history (book, code, field, old, new, "
                        "at, by, note) VALUES (?,?,?,?,?,?,?,?)", logs)
    return len(logs)


def delete_book(name):
    with connect(write=True) as con:
        for t in ("books", "rates", "items"):
            con.execute(f"DELETE FROM {t} WHERE {'name' if t == 'books' else 'book'}=?",
                        (name,))
        con.execute("INSERT INTO history (book, code, field, old, new, at, "
                    "by, note) VALUES (?,?,?,?,?,?,?,?)",
                    (name, "", "deleted", "", "", now(), user(), ""))


def history(name=None, code=None, limit=500):
    q, args = "SELECT * FROM history", []
    where = []
    if name:
        where.append("book=?")
        args.append(name)
    if code:
        where.append("code=?")
        args.append(code)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    with connect() as con:
        return [dict(r) for r in con.execute(q, args)]


def content_hash(data):
    items = {}
    for c, it in (data.get("items") or {}).items():
        items[c] = {k: it.get(k) for k in HASH_FIELDS}
        items[c].update({k: it[k] for k in NEW_FIELDS if it.get(k)})
    blob = json.dumps([items, data.get("rates") or {},
                       data.get("index") or {},
                       data.get("escalation_by_div") or {}], sort_keys=True,
                      default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


# ---- tamper signal for a shared price database (threat model T-016) -------
# Each PC remembers, per book, the "modified" stamp QuantiSheet wrote and
# the book's content hash. When the same stamp comes back with different
# content, the book was changed outside QuantiSheet (an edit straight in
# the database file on the share): the user is warned before using it.

def _seen_path():
    from . import settings
    return os.path.join(settings.DIR, "pricedb_seen.json")


def _seen():
    try:
        with open(_seen_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def outside_change(name, data=None):
    """'' or a warning when book `name` changed outside QuantiSheet since
    this PC last saw it. Records what it sees."""
    data = data if data is not None else load_book(name)
    if not data:
        return ""
    key = f"{path()}|{name}"
    h = content_hash(data)
    seen = _seen()
    was = seen.get(key)
    msg = ""
    if was and was.get("modified") == data.get("modified") and \
            was.get("hash") != h:
        msg = (f"The price book \"{name}\" changed without QuantiSheet "
               "recording who changed it (its last-changed stamp didn't "
               "move). Someone may have edited the price database file "
               "directly. Check its prices before using them.")
        log.warning("price book %s changed outside QuantiSheet", name)
    if not msg:
        seen[key] = {"modified": data.get("modified"), "hash": h}
        try:
            from . import settings
            os.makedirs(settings.DIR, exist_ok=True)
            tmp = _seen_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(seen, f)
            os.replace(tmp, _seen_path())
        except OSError:
            log.debug("price book check not saved", exc_info=True)
    return msg


def accept_outside_change(name):
    """The user checked the book: remember it as it is now."""
    data = load_book(name)
    if data:
        seen = _seen()
        seen[f"{path()}|{name}"] = {"modified": data.get("modified"),
                                    "hash": content_hash(data)}
        from . import settings
        os.makedirs(settings.DIR, exist_ok=True)
        with open(_seen_path(), "w", encoding="utf-8") as f:
            json.dump(seen, f)


# ---- licensed, local-only books ----------------------------------------------

def book_is_local_only(data):
    """True for a book imported from a licensed price list (its own flag,
    or any item tagged local-only)."""
    if not data:
        return False
    if data.get("local_only"):
        return True
    return any(str((it or {}).get("license") or "") == LOCAL_ONLY
               for it in (data.get("items") or {}).values())


def local_only_message(name, where=None):
    where = where or path()
    return (f"\"{name}\" is licensed price data marked local-only. It can "
            "only be kept in this PC's local price database, not in the "
            f"shared one ({where}). Nothing was saved. To keep it, use Price "
            "Database > Use This PC Only, then import it again.")


def refuse_local_only(data, target=None):
    """Raise LocalOnlyError when `data` is a local-only book and the price
    database (or `target`) is on a shared folder."""
    if book_is_local_only(data) and is_shared(target):
        raise LocalOnlyError(local_only_message(data.get("name", "?"),
                                                target))


def local_only_books(p=None):
    """Names of the local-only books in the database at `p` (default: the
    one in use)."""
    if p is None:
        with connect() as con:
            return _local_only_in(con)
    con = _open(p)
    try:
        _init(con)
        return _local_only_in(con)
    finally:
        con.close()


def _local_only_in(con):
    out = []
    for r in con.execute("SELECT name, extra_json FROM books"):
        try:
            extra = json.loads(r[1] or "{}")
        except ValueError:
            extra = {}
        if extra.get("local_only"):
            out.append(r[0])
    try:
        for r in con.execute("SELECT DISTINCT book FROM items WHERE "
                             "license=?", (LOCAL_ONLY,)):
            if r[0] not in out:
                out.append(r[0])
    except sqlite3.OperationalError:          # a copy from before 0.13
        pass
    return sorted(out, key=str.lower)


def _drop_local_only(p):
    """Take every local-only book (prices, rates and their history) out
    of the database file at `p`. Returns the names removed."""
    con = _open(p)
    try:
        _init(con)
        names = _local_only_in(con)
        for n in names:
            for t in ("books", "rates", "items", "history"):
                col = "name" if t == "books" else "book"
                con.execute(f"DELETE FROM {t} WHERE {col}=?", (n,))
        con.commit()
        if names:
            con.execute("VACUUM")         # no leftover pages with the data
        return names
    finally:
        con.close()


# ---- location factors ---------------------------------------------------------

def location_rows():
    """Your rows of the Location Factors table (edited starter rows too;
    removed ones have deleted=1), as dicts."""
    if not is_shared() and not os.path.exists(path()):
        return []                  # no database yet: don't make one to read
    try:
        with connect() as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM location_factors ORDER BY region "
                "COLLATE NOCASE")]
    except sqlite3.OperationalError:       # read-only copy without the table
        return []


def _loc_val(row, k):
    v = (row or {}).get(k)
    if k in ("materials", "labor", "equipment"):
        try:
            return f"{float(v):g}"
        except (TypeError, ValueError):
            return ""
    return str(v or "")


def save_locations(changes, note=""):
    """Write Location Factors rows. `changes` = [(old row or None, new row
    or None)] (old is the row as shown, so a starter row's first edit logs
    the starter value); new None removes the row. Every changed field is
    logged in the price history (book "Location Factors", code = region):
    who, when, old -> new. Returns the number of logged changes."""
    stamp, who = now(), user()
    logs = []
    with connect(write=True) as con:
        for old, new in changes:
            if new is None:
                if not old:
                    continue
                region = str(old["region"])
                con.execute(
                    "INSERT OR REPLACE INTO location_factors (region, state,"
                    " cities, zips, materials, labor, equipment, source, "
                    "deleted, modified, modified_by) VALUES "
                    "(?,?,?,?,?,?,?,?,1,?,?)",
                    (region, old.get("state", ""), old.get("cities", ""),
                     old.get("zips", ""), old.get("materials"),
                     old.get("labor"), old.get("equipment"),
                     old.get("source", ""), stamp, who))
                logs.append((LOCATION_BOOK, region, "removed", "", "", stamp,
                             who, note))
                continue
            region = str(new.get("region") or "").strip()
            if not region:
                raise PriceDBError("Each location needs a region name.")
            vals = {}
            for k in ("materials", "labor", "equipment"):
                try:
                    vals[k] = float(new.get(k) if new.get(k) not in
                                    (None, "") else 1.0)
                except (TypeError, ValueError):
                    raise PriceDBError(f"{region}: the {k} factor "
                                       f"{new.get(k)!r} isn't a number.")
                if vals[k] <= 0:
                    raise PriceDBError(f"{region}: the {k} factor must be "
                                       "more than 0.")
            row = {"region": region, "state": str(new.get("state") or "")
                   .strip().upper(), "cities": str(new.get("cities") or "")
                   .strip(), "zips": str(new.get("zips") or "").strip(),
                   "source": str(new.get("source") or "").strip(), **vals}
            if old and str(old.get("region")) != region:
                con.execute("UPDATE location_factors SET deleted=1, "
                            "modified=?, modified_by=? WHERE region=?",
                            (stamp, who, str(old["region"])))
                con.execute(
                    "INSERT OR IGNORE INTO location_factors (region, "
                    "deleted, modified, modified_by) VALUES (?,1,?,?)",
                    (str(old["region"]), stamp, who))
                logs.append((LOCATION_BOOK, region, "region",
                             str(old["region"]), region, stamp, who, note))
            diff = [(k, _loc_val(old, k), _loc_val(row, k))
                    for k in LOCATION_FIELDS]
            diff = [d for d in diff if d[1] != d[2]] if old else \
                [("added", "", " ".join(f"{k}={_loc_val(row, k)}"
                                         for k in LOCATION_FIELDS
                                         if _loc_val(row, k)))]
            if not diff and old and str(old.get("region")) == region:
                continue
            con.execute(
                "INSERT OR REPLACE INTO location_factors (region, state, "
                "cities, zips, materials, labor, equipment, source, deleted,"
                " modified, modified_by) VALUES (?,?,?,?,?,?,?,?,0,?,?)",
                (region, row["state"], row["cities"], row["zips"],
                 row["materials"], row["labor"], row["equipment"],
                 row["source"], stamp, who))
            label = {"materials": "materials factor", "labor":
                     "labor factor", "equipment": "equipment factor",
                     "zips": "ZIPs"}
            logs += [(LOCATION_BOOK, region, label.get(k, k), o, n, stamp,
                      who, note) for k, o, n in diff]
        con.executemany("INSERT INTO history (book, code, field, old, new, "
                        "at, by, note) VALUES (?,?,?,?,?,?,?,?)", logs)
    return len(logs)


# ---- catalogs ------------------------------------------------------------------

def put_catalog(name, text):
    with connect(write=True) as con:
        con.execute("INSERT OR REPLACE INTO catalogs VALUES (?,?,?,?)",
                    (name, text, now(), user()))


def catalog_stamps():
    """{name: modified} without reading the CSV text."""
    with connect() as con:
        return {r[0]: r[1] for r in con.execute(
            "SELECT name, modified FROM catalogs")}


def catalog_text(name):
    with connect() as con:
        r = con.execute("SELECT csv FROM catalogs WHERE name=?",
                        (name,)).fetchone()
    return r[0] if r else None


def delete_catalog(name):
    with connect(write=True) as con:
        con.execute("DELETE FROM catalogs WHERE name=?", (name,))


# ---- moving / connecting -------------------------------------------------------

def use(new_path, copy_current=True):
    """Point QuantiSheet at the database file `new_path`. If it doesn't exist
    and copy_current, the current database is copied there first (so the
    office starts from your prices). Returns 'connected' or 'copied'.
    Local-only (licensed) books are never copied to a shared folder: they
    stay in this PC's database (state["left_out"] names them)."""
    if managed():
        raise RuntimeError("Your IT department sets the price database "
                           f"location ({managed()}).")
    state["left_out"] = []
    new_path = os.path.abspath(new_path)
    if os.path.isdir(new_path):
        new_path = file_in(new_path)
    how = "connected"
    if not os.path.exists(new_path):
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        if copy_current and os.path.exists(path()):
            src = _open(path())
            dst = sqlite3.connect(new_path)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            how = "copied"
            state["left_out"] = _drop_local_only(new_path) \
                if is_shared(new_path) else []
    con = _open(new_path)
    _init(con)
    con.close()
    settings.set("price_db", new_path)
    state["copied"] = 0.0
    _BOOK_CACHE.clear()
    _refresh_copy(force=True)
    return how


def use_local():
    if managed():
        raise RuntimeError("Your IT department sets the price database "
                           f"location ({managed()}).")
    settings.set("price_db", None)
    _BOOK_CACHE.clear()


def backup(dest):
    with connect() as con:
        out = sqlite3.connect(dest)
        with out:
            con.backup(out)
        out.close()
    return dest


def migrate_json(folder):
    """Bring cost book files (*.json) from the old cost book folder into
    the database once. Returns the names added."""
    done = meta("migrated_json") or []
    if isinstance(done, str):
        done = [done]
    added = []
    if not os.path.isdir(folder):
        return added
    have = set(book_names())
    for n in sorted(os.listdir(folder)):
        if not n.endswith(".json") or n in done:
            continue
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if data.get("name") and data["name"] not in have:
            save_book(data, note=f"moved from {n}")
            added.append(data["name"])
        done.append(n)
    set_meta("migrated_json", done)
    return added


def _cleanup_backups(folder, keep=10):
    try:
        files = sorted(f for f in os.listdir(folder) if f.endswith(".bak"))
        for f in files[:-keep]:
            os.remove(os.path.join(folder, f))
    except OSError:
        pass


def snapshot():
    """A dated backup of the database next to it (kept: last 10)."""
    folder = os.path.join(os.path.dirname(path()), "Price backups")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, _dt.datetime.now().strftime(
        "prices %Y-%m-%d %H%M.bak"))
    backup(dest)
    _cleanup_backups(folder)
    return dest


__all__ = ["path", "connect", "load_book", "save_book", "update_items",
           "update_rates", "history", "book_names", "use", "PriceDBError",
           "Conflict", "shutil"]
