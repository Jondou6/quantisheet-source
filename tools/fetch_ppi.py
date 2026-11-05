"""Fetch the BLS PPI series into the price database and use them for bid
tab escalation; prints the rates by trade."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import ppi, pricedb
got = ppi.fetch()
print("price database:", pricedb.path())
print("series with data:", sum(1 for v in got.values() if v), "of", len(ppi.series()))
start, end = "2024-01", "2026-10"
for r in ppi.table(start, end):
    if r["annual_pct"] is not None:
        print(f"{r['id']:<16} {r['title'][:44]:<44} last {r['last_month']}  {r['annual_pct']:+6.2f}%/yr  x{r['factor']:.3f}")
print()
for t, v in sorted(ppi.trade_rates(start, end).items()):
    print(f"{t:<28} {v:+6.2f}%/yr")
print("bid tabs now use:", len(ppi.apply_to_bidtabs(start, end)), "trade rates")
