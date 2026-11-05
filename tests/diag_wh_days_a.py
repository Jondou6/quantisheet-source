"""Diagnostic only: calendar days NTP -> Substantial Completion for the
generated jobs the release notes quote."""
from test_productivity import cfg, _genset_job, _days     # noqa: F401


def test_diag(cfg, tmp_path):
    for f in ({"building_type": "single_family", "gross_sf": 1600},
              {"building_type": "restaurant", "gross_sf": 4500},
              {"building_type": "strip_retail", "gross_sf": 20000},
              {"building_type": "warehouse", "gross_sf": 38000}):
        d = _days(_genset_job(tmp_path, f), tmp_path, f["building_type"])
        print("\nDAYS", f, d)
