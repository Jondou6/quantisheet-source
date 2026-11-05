"""What changed between two copies of a price database? Prints, per
table, the row counts and how many rows were added, removed or changed -
never a price, name or any other value (Oct 29: tests had touched the
real prices.db).

    python tools/compare_price_db.py OLD.db NEW.db"""
import hashlib
import sqlite3
import sys


def rows(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        out = {}
        for (t,) in con.execute("select name from sqlite_master where "
                                "type='table' order by name"):
            cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
            pk = [r[1] for r in con.execute(f'pragma table_info("{t}")')
                  if r[5]]
            got = {}
            for r in con.execute(f'select * from "{t}"'):
                d = dict(zip(cols, r))
                key = tuple(d[k] for k in pk) if pk else None
                h = hashlib.sha256(repr(r).encode()).hexdigest()
                got[key if key is not None else h] = h
            out[t] = got
        return out
    finally:
        con.close()


a, b = rows(sys.argv[1]), rows(sys.argv[2])
same = True
for t in sorted(set(a) | set(b)):
    x, y = a.get(t, {}), b.get(t, {})
    added = len(set(y) - set(x))
    removed = len(set(x) - set(y))
    changed = sum(1 for k in set(x) & set(y) if x[k] != y[k])
    if added or removed or changed or t not in a or t not in b:
        same = False
    print(f"{t:32s} old {len(x):7d}  new {len(y):7d}  added {added:5d}  "
          f"removed {removed:5d}  changed {changed:5d}"
          + ("  (table only in new)" if t not in a else "")
          + ("  (table only in old)" if t not in b else ""))
print("IDENTICAL ROWS" if same else "ROWS DIFFER")
