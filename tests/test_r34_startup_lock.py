"""r34 (H1, H6) guarded the old data-folder move at start-up. The move is
gone (Oct 30: nothing uses the old folder), so start-up takes no lock and
the estimating tools and price database never refuse to save for it."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_start_up_takes_no_lock():
    from app import settings
    for gone in ("_take_lock", "LOCK_SUFFIX", "SAFE_MODE",
                 "migrate_data_dir"):
        assert not hasattr(settings, gone), gone
    with open(os.path.join(ROOT, "quantisheet.py"), encoding="utf-8") as f:
        assert "migrate_data_dir" not in f.read()


def test_tools_save_without_a_lock_check(tmp_path, monkeypatch):
    from app import settings
    from app.estimating import _io, safedb
    monkeypatch.setattr(settings, "DIR", str(tmp_path))
    p = _io.data_file("estimating", "x.json")
    assert p.startswith(str(tmp_path))
    assert not hasattr(_io, "migration_lock_held")
    assert not hasattr(safedb, "check_can_write")
