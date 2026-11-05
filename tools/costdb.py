#!/usr/bin/env python3
"""
costdb.py
=========
Construction cost database: schema, provenance, and helpers.

Every price is traceable to a source and a date. Nothing is overwritten.
The item table is a controlled vocabulary - one canonical string per thing -
which is what lets bid tabs, libraries, and job actuals all talk to each other.

Usage
-----
    python costdb.py init --db cost.db
    python costdb.py seed --db cost.db
    python costdb.py add-source --db cost.db --name "TX DOT 2026-03" --kind bid_tab --region TX
    python costdb.py add-item --db cost.db --canonical "Concrete sidewalk, 4 in" --unit SF --trade "03 Concrete"
    python costdb.py add-alias --db cost.db --item 1 --text "4 in conc sidewalk"
    python costdb.py add-price --db cost.db --item 1 --value 7.40 --source 1 --date 2026-03
    python costdb.py latest --db cost.db --trade "03 Concrete"
    python costdb.py stats --db cost.db
    python costdb.py sql --db cost.db "SELECT canonical FROM item LIMIT 5"
    python costdb.py export --db cost.db --out library.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    kind         TEXT,              -- bid_tab | rsmeans | vendor | quote | actual | ppi | index
    url          TEXT,
    license      TEXT,
    region       TEXT,
    retrieved_at TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS trade (
    code       TEXT PRIMARY KEY,    -- e.g. '03 Concrete'
    csi        TEXT,                -- e.g. '03 30 00'
    uniformat  TEXT,                -- e.g. 'A1030'
    rsmeans     TEXT,               -- e.g. 'A1030 120'
    parent     TEXT
);

CREATE TABLE IF NOT EXISTS item (
    id         INTEGER PRIMARY KEY,
    code       TEXT UNIQUE,         -- your internal code
    canonical  TEXT NOT NULL,       -- the one true description
    unit       TEXT NOT NULL,
    trade_code TEXT REFERENCES trade(code),
    cost_type  TEXT,                -- Labor | Material | Equipment | Sub | Other
    waste_pct  REAL DEFAULT 0,
    crew       TEXT,
    active     INTEGER DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_item_canonical ON item(canonical);
CREATE INDEX IF NOT EXISTS idx_item_trade ON item(trade_code);

CREATE TABLE IF NOT EXISTS alias (
    id        INTEGER PRIMARY KEY,
    item_id   INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    text      TEXT NOT NULL,
    source_id INTEGER REFERENCES source(id),
    norm      TEXT NOT NULL,
    hits      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alias_norm ON alias(norm);
CREATE INDEX IF NOT EXISTS idx_alias_item ON alias(item_id);

CREATE TABLE IF NOT EXISTS price (
    id         INTEGER PRIMARY KEY,
    item_id    INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    source_id  INTEGER REFERENCES source(id),
    value      REAL NOT NULL,
    unit       TEXT,
    qty_basis  REAL,
    region     TEXT,
    price_date TEXT NOT NULL,       -- YYYY-MM
    kind       TEXT,                -- unit | bare_labor | bare_material | loaded | quote | actual
    n_obs      INTEGER DEFAULT 1,
    low        REAL,
    high       REAL,
    median     REAL,
    spread_pct REAL,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_price_item_date ON price(item_id, price_date);
CREATE INDEX IF NOT EXISTS idx_price_kind ON price(kind);

CREATE TABLE IF NOT EXISTS crosswalk (
    id         INTEGER PRIMARY KEY,
    item_id    INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    system     TEXT NOT NULL,       -- csi | uniformat | rsmeans | costcode | omniclass
    code       TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    UNIQUE(item_id, system, code)
);

CREATE TABLE IF NOT EXISTS assembly (
    id        INTEGER PRIMARY KEY,
    item_id   INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    unit      TEXT,
    formula   TEXT,
    variables TEXT
);

CREATE TABLE IF NOT EXISTS assembly_component (
    id           INTEGER PRIMARY KEY,
    assembly_id  INTEGER NOT NULL REFERENCES assembly(id) ON DELETE CASCADE,
    item_id      INTEGER NOT NULL REFERENCES item(id),
    seq          INTEGER,
    calc_method  TEXT,              -- formula | factor
    calculation  TEXT,
    waste_pct    REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS job (
    id             INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    owner          TEXT,
    region         TEXT,
    contract_value REAL,
    start_date     TEXT,
    end_date       TEXT,
    status         TEXT
);

CREATE TABLE IF NOT EXISTS actual (
    id          INTEGER PRIMARY KEY,
    job_id      INTEGER NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    item_id     INTEGER REFERENCES item(id),
    description TEXT,
    qty         REAL,
    unit        TEXT,
    cost        REAL,
    cost_type   TEXT,
    period      TEXT
);
CREATE INDEX IF NOT EXISTS idx_actual_item ON actual(item_id);

CREATE TABLE IF NOT EXISTS change_log (
    id        INTEGER PRIMARY KEY,
    at        TEXT,
    entity    TEXT,
    entity_id INTEGER,
    action    TEXT,
    detail    TEXT
);

CREATE VIEW IF NOT EXISTS v_latest_price AS
SELECT * FROM (
    SELECT p.*,
           ROW_NUMBER() OVER (
               PARTITION BY p.item_id, COALESCE(p.kind, 'unit')
               ORDER BY p.price_date DESC, p.id DESC
           ) AS rn
    FROM price p
) WHERE rn = 1;

CREATE VIEW IF NOT EXISTS v_library AS
SELECT i.id AS item_id, i.code, i.canonical, i.unit, i.trade_code, i.cost_type,
       t.csi, t.uniformat, t.rsmeans,
       v.value, v.price_date, s.name AS source_name, s.kind AS source_kind, v.region
FROM item i
JOIN trade t ON t.code = i.trade_code
JOIN v_latest_price v ON v.item_id = i.id AND COALESCE(v.kind, 'unit') = 'unit'
LEFT JOIN source s ON s.id = v.source_id
WHERE i.active = 1;
"""

# CSI divisions. Extend as needed.
SEED_TRADES = [
    ("00 General Requirements", "00 00 00", None, None),
    ("01 General Requirements", "01 00 00", None, None),
    ("02 Existing Conditions", "02 00 00", None, None),
    ("03 Concrete", "03 00 00", "A10", "A10"),
    ("04 Masonry", "04 00 00", "B2010", "B2010"),
    ("05 Metals", "05 00 00", "B10", "B1010"),
    ("06 Wood", "06 00 00", "B10", "B1010"),
    ("07 Thermal & Moisture", "07 00 00", "B30", "B3010"),
    ("08 Openings", "08 00 00", "B20", "B2030"),
    ("09 Finishes", "09 00 00", "C30", "C3010"),
    ("10 Specialties", "10 00 00", "C10", "C1030"),
    ("11 Equipment", "11 00 00", "E10", "E1090"),
    ("12 Furnishings", "12 00 00", "E20", "E2020"),
    ("13 Special Construction", "13 00 00", "F10", "F1010"),
    ("14 Conveying", "14 00 00", "D10", "D1010"),
    ("21 Fire Suppression", "21 00 00", "D40", "D4010"),
    ("22 Plumbing", "22 00 00", "D20", "D2010"),
    ("23 HVAC", "23 00 00", "D30", "D3050"),
    ("25 Integrated Automation", "25 00 00", "D30", "D3060"),
    ("26 Electrical", "26 00 00", "D50", "D5020"),
    ("27 Communications", "27 00 00", "D50", "D5030"),
    ("28 Electronic Safety", "28 00 00", "D50", "D5030"),
    ("31 Earthwork", "31 00 00", "G10", "G1030"),
    ("32 Exterior Improvements", "32 00 00", "G20", "G2030"),
    ("33 Utilities", "33 00 00", "G30", "G3010"),
    ("34 Transportation", "34 00 00", "G20", "G2010"),
    ("35 Waterway & Marine", "35 00 00", "G20", "G2040"),
    ("40 Process Interconnections", "40 00 00", "D20", None),
    ("41 Material Handling", "41 00 00", "E10", None),
    ("42 Process Heating/Cooling", "42 00 00", "D30", None),
    ("43 Process Gas/Liquid", "43 00 00", "D20", None),
    ("44 Pollution & Waste Control", "44 00 00", "G30", None),
    ("45 Industry-Specific Equipment", "45 00 00", "E10", None),
    ("46 Water & Wastewater Equipment", "46 00 00", "G30", None),
    ("48 Power Generation", "48 00 00", "D50", "D5090"),
    ("Unclassified", None, None, None),
]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def log(conn: sqlite3.Connection, entity: str, entity_id: int | None, action: str,
        detail: str = "") -> None:
    conn.execute(
        "INSERT INTO change_log (at, entity, entity_id, action, detail) VALUES (?,?,?,?,?)",
        (now(), entity, entity_id, action, detail),
    )


def require(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "item" not in tables:
        raise SystemExit("database not initialised - run: costdb.py init --db <path>")


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_init(conn: sqlite3.Connection, args) -> int:
    conn.executescript(SCHEMA)
    conn.commit()
    print(f"initialised {args.db}")
    return 0


def cmd_seed(conn: sqlite3.Connection, args) -> int:
    require(conn)
    for code, csi, uniformat, rsmeans in SEED_TRADES:
        conn.execute(
            "INSERT OR IGNORE INTO trade (code, csi, uniformat, rsmeans) VALUES (?,?,?,?)",
            (code, csi, uniformat, rsmeans),
        )
    conn.commit()
    print(f"seeded {len(SEED_TRADES)} trades")
    return 0


def cmd_add_source(conn: sqlite3.Connection, args) -> int:
    require(conn)
    cur = conn.execute(
        "INSERT OR IGNORE INTO source (name, kind, url, license, region, retrieved_at, notes) "
        "VALUES (?,?,?,?,?,?,?)",
        (args.name, args.kind, args.url, args.license, args.region, now(), args.notes),
    )
    conn.commit()
    if cur.lastrowid:
        log(conn, "source", cur.lastrowid, "create", args.name)
        conn.commit()
        print(f"source {cur.lastrowid}: {args.name}")
    else:
        row = conn.execute("SELECT id FROM source WHERE name = ?", (args.name,)).fetchone()
        print(f"source {row['id']} already exists: {args.name}")
    return 0


def cmd_add_item(conn: sqlite3.Connection, args) -> int:
    require(conn)
    cur = conn.execute(
        "INSERT INTO item (code, canonical, unit, trade_code, cost_type, waste_pct, crew, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (args.code, args.canonical, args.unit, args.trade, args.cost_type,
         args.waste, args.crew, now(), now()),
    )
    item_id = cur.lastrowid
    if args.alias:
        from vocab import normalize  # local import to avoid a hard dependency
        for text in args.alias.split("|"):
            conn.execute(
                "INSERT INTO alias (item_id, text, norm) VALUES (?,?,?)",
                (item_id, text.strip(), normalize(text)),
            )
    log(conn, "item", item_id, "create", args.canonical)
    conn.commit()
    print(f"item {item_id}: {args.canonical}")
    return 0


def cmd_add_alias(conn: sqlite3.Connection, args) -> int:
    require(conn)
    from vocab import normalize
    conn.execute(
        "INSERT INTO alias (item_id, text, source_id, norm) VALUES (?,?,?,?)",
        (args.item, args.text, args.source, normalize(args.text)),
    )
    log(conn, "alias", args.item, "create", args.text)
    conn.commit()
    print(f"alias added to item {args.item}")
    return 0


def cmd_add_price(conn: sqlite3.Connection, args) -> int:
    require(conn)
    cur = conn.execute(
        "INSERT INTO price (item_id, source_id, value, unit, qty_basis, region, price_date, kind, n_obs, low, high, median, spread_pct, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (args.item, args.source, args.value, args.unit, args.qty, args.region,
         args.date, args.kind, args.n_obs, args.low, args.high, args.median,
         args.spread, now()),
    )
    log(conn, "price", args.item, "create", f"{args.value} @ {args.date} src={args.source}")
    conn.commit()
    print(f"price {cur.lastrowid} on item {args.item}")
    return 0


def cmd_latest(conn: sqlite3.Connection, args) -> int:
    require(conn)
    sql = ("SELECT canonical, unit, trade_code, value, price_date, source_name, source_kind "
           "FROM v_library")
    where, params = [], []
    if args.trade:
        where.append("trade_code = ?")
        params.append(args.trade)
    if args.like:
        where.append("canonical LIKE ?")
        params.append(f"%{args.like}%")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY trade_code, canonical"

    rows = conn.execute(sql, params).fetchall()
    if args.json:
        print(json.dumps([dict(r) for r in rows], indent=2))
        return 0
    if not rows:
        print("no priced items")
        return 0
    print(f"{'description':<44} {'unit':<5} {'value':>10} {'date':<8} source")
    print("-" * 92)
    for r in rows:
        print(f"{r['canonical'][:43]:<44} {r['unit']:<5} {r['value']:>10,.2f} "
              f"{r['price_date']:<8} {r['source_name'] or ''}")
    return 0


def cmd_stats(conn: sqlite3.Connection, args) -> int:
    require(conn)
    for table in ("source", "item", "alias", "price", "crosswalk", "job", "actual"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:<12} {count:>7,}")

    unpriced = conn.execute(
        "SELECT COUNT(*) FROM item i WHERE NOT EXISTS (SELECT 1 FROM price p WHERE p.item_id = i.id)"
    ).fetchone()[0]
    unaliased = conn.execute(
        "SELECT COUNT(*) FROM item i WHERE NOT EXISTS (SELECT 1 FROM alias a WHERE a.item_id = i.id)"
    ).fetchone()[0]
    uncrossed = conn.execute(
        "SELECT COUNT(*) FROM item i WHERE NOT EXISTS (SELECT 1 FROM crosswalk c WHERE c.item_id = i.id)"
    ).fetchone()[0]
    print(f"\nitems with no price       {unpriced:,}")
    print(f"items with no alias       {unaliased:,}")
    print(f"items with no crosswalk   {uncrossed:,}")
    return 0


def cmd_export(conn: sqlite3.Connection, args) -> int:
    require(conn)
    rows = conn.execute(
        "SELECT code, canonical, unit, trade_code, csi, uniformat, rsmeans, value, "
        "price_date, source_name, source_kind FROM v_library ORDER BY trade_code, canonical"
    ).fetchall()
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["code", "description", "unit", "trade", "csi", "uniformat",
                         "rsmeans", "unit_cost", "price_date", "source", "source_kind"])
        for r in rows:
            writer.writerow(list(r))
    print(f"wrote {len(rows)} rows -> {args.out}")
    return 0


def cmd_sql(conn: sqlite3.Connection, args) -> int:
    require(conn)
    rows = conn.execute(args.query).fetchall()
    if not rows:
        print("(no rows)")
        return 0
    keys = rows[0].keys()
    print(" | ".join(keys))
    print("-" * 70)
    for r in rows:
        print(" | ".join("" if v is None else str(v) for v in r))
    return 0


# --------------------------------------------------------------------------

def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Construction cost database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--db", type=Path, default=Path("cost.db"))
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)
    sub.add_parser("seed").set_defaults(func=cmd_seed)

    s = sub.add_parser("add-source")
    s.add_argument("--name", required=True)
    s.add_argument("--kind", default="bid_tab")
    s.add_argument("--url"); s.add_argument("--license"); s.add_argument("--region"); s.add_argument("--notes")
    s.set_defaults(func=cmd_add_source)

    s = sub.add_parser("add-item")
    s.add_argument("--canonical", required=True)
    s.add_argument("--unit", required=True)
    s.add_argument("--trade", default="Unclassified")
    s.add_argument("--code"); s.add_argument("--cost-type"); s.add_argument("--crew")
    s.add_argument("--waste", type=float, default=0.0)
    s.add_argument("--alias", help="pipe separated variants: 'a|b|c'")
    s.set_defaults(func=cmd_add_item)

    s = sub.add_parser("add-alias")
    s.add_argument("--item", type=int, required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--source", type=int)
    s.set_defaults(func=cmd_add_alias)

    s = sub.add_parser("add-price")
    s.add_argument("--item", type=int, required=True)
    s.add_argument("--value", type=float, required=True)
    s.add_argument("--source", type=int)
    s.add_argument("--date", required=True, metavar="YYYY-MM")
    s.add_argument("--kind", default="unit")
    s.add_argument("--unit"); s.add_argument("--qty", type=float); s.add_argument("--region")
    s.add_argument("--n-obs", type=int, default=1)
    s.add_argument("--low", type=float); s.add_argument("--high", type=float)
    s.add_argument("--median", type=float); s.add_argument("--spread", type=float)
    s.set_defaults(func=cmd_add_price)

    s = sub.add_parser("latest")
    s.add_argument("--trade"); s.add_argument("--like"); s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_latest)

    sub.add_parser("stats").set_defaults(func=cmd_stats)

    s = sub.add_parser("export")
    s.add_argument("--out", type=Path, required=True)
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("sql")
    s.add_argument("query")
    s.set_defaults(func=cmd_sql)

    args = p.parse_args(argv)
    conn = connect(args.db)
    try:
        return args.func(conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())