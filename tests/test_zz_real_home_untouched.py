"""The test run never uses the real home folder (Oct 29: a run's last
window saved its size into the real settings.json)."""
import os


def test_settings_live_in_a_throwaway_home():
    if os.environ.get("QS_TESTS_REAL_HOME") == "1":
        return
    from app import settings
    home = os.path.expanduser("~")
    assert "qs_test_home_" in home
    assert "qs_test_home_" in settings.DIR


def test_app_data_and_programdata_are_throwaway():
    """Chief review Q5: APPDATA / LOCALAPPDATA and ProgramData (policy,
    relay, print spool) point inside the test home too."""
    if os.environ.get("QS_TESTS_REAL_HOME") == "1":
        return
    from app import policy
    for k in ("APPDATA", "LOCALAPPDATA"):
        assert "qs_test_home_" in os.environ[k]
    assert "qs_test_home_" in policy.data_dir()
    assert not policy.get("PriceDatabasePath")
