"""M4 plumbing: new tables appear in an older company file, money stays
int cents, and only localai.py of the Phase 3 modules can reach a network."""
import os
import re

from quantisheet_backoffice import store
from quantisheet_backoffice.office import Office

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
M4_TABLES = ("ai_log", "ai_actions", "wip_estimates", "erp_runs",
             "erp_links", "erp_records", "connectors")
M4_MODULES = ("aicat", "aiguard", "aitrail", "actions", "assistant", "wip",
              "erpsync", "connectors")


def test_m4_tables_added_to_an_m3_company_file(office):
    folder = office.folder
    vid = office.db.insert("vendors", name="Example Paint")
    for t in M4_TABLES:
        office.db.conn.execute(f"DROP TABLE {t}")
    office.close()
    o = Office(folder)
    have = {r["name"] for r in o.db.rows(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(M4_TABLES) <= have
    assert o.db.get("vendors", vid)["name"] == "Example Paint"
    o.close()


def test_money_columns_are_integer_cents():
    assert "amount INTEGER" in store.TABLES["wip_estimates"]


def test_only_localai_reaches_a_network():
    net = re.compile(r"^\s*(import|from)\s+(urllib\.request|http\.client|"
                     r"socket|requests|httpx|aiohttp)\b", re.M)
    for m in M4_MODULES:
        src = open(os.path.join(PKG, m + ".py"), encoding="utf-8").read()
        assert not net.search(src), m
        assert ("google" + "apis") not in src and "openai" not in src.lower()
    src = open(os.path.join(PKG, "localai.py"), encoding="utf-8").read()
    assert "ProxyHandler({})" in src and "check_local" in src
    assert "_NoRedirect()" in src                   # 30x never followed
    assert "openai.com" not in src and ("google" + "apis") not in src
