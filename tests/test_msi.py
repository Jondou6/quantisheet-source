"""The MSI package for IT (0.12.24): tools/make_msi.py."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import make_msi  # noqa: E402


def test_msi_version():
    assert make_msi.msi_version("0.12.24") == "0.12.24"
    assert make_msi.msi_version("1.2") == "1.2.0"
    with pytest.raises(ValueError):
        make_msi.msi_version("300.1.1")


def test_policy_values_match_the_server_setup():
    """The MSI's properties write the same policy values as the server
    setup's switches - IT can switch packages without new GPO docs."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    iss = open(os.path.join(root, "installer", "quantisheet_server.iss"),
               encoding="utf-8").read()
    for prop, name, _v in make_msi.POLICY_VALUES:
        assert f'ValueName: "{name}"' in iss
        assert f"HasParam('{prop}')" in iss
        assert prop in make_msi.PUBLIC


def _msilib():
    try:
        import warnings
        warnings.simplefilter("ignore", DeprecationWarning)
        import msilib  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _msilib(), reason="msilib is Windows Python 3.12")
def test_build_a_small_msi(tmp_path):
    app = tmp_path / "app"
    (app / "lib" / "sub").mkdir(parents=True)
    (app / make_msi.EXE).write_bytes(b"MZ fake program")
    assert make_msi.EXE == "QuantiSheet.exe"
    (app / "lib" / "a.dll").write_bytes(b"dll")
    (app / "lib" / "sub" / "b.txt").write_text("text")
    out = tmp_path / "t.msi"
    path, code, n = make_msi.build(str(app), str(out), "0.12.24", "Test")
    assert n == 3 + 4                    # the program + the IT extras
    info = make_msi.check(path)
    assert info["version"] == "0.12.24" and info["allusers"] == "1"
    assert info["upgrade_code"] == make_msi.UPGRADE_CODE
    assert info["files"] == n + 2        # + the two GPO template copies
    # a second build in the same process gets fresh ids (no "...1" names)
    path2, code2, _n = make_msi.build(str(app), str(tmp_path / "u.msi"),
                                      "0.12.24", "Test")
    assert code2 != code and make_msi.check(path2)["files"] == n + 2
