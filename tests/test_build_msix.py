"""Store package (MSIX) settings: version rules and identity file."""
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    spec = importlib.util.spec_from_file_location(
        "build_msix", os.path.join(ROOT, "tools", "build_msix.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_store_version_is_ours_and_never_starts_with_0():
    import pytest
    m = _mod()
    assert m.store_version("1.0.0") == "1.0.0.0"
    assert m.store_version("1.2") == "1.2.0.0"
    with pytest.raises(ValueError):
        m.store_version("0.13.15")


def test_program_version_is_store_ready():
    from app import __version__
    assert int(__version__.split(".")[0]) >= 1


def test_identity_is_the_partner_center_one():
    with open(os.path.join(ROOT, "installer", "msix_identity.json"),
              encoding="utf-8") as f:
        ident = json.load(f)
    assert "PLACEHOLDER" not in ident["Name"] + ident["Publisher"]
    assert ident["Publisher"].startswith("CN=")
    m = _mod()
    xml = m.MANIFEST.format(version=m.store_version("1.0.0"), **ident)
    assert 'Version="1.0.0.0"' in xml and ident["Name"] in xml


def test_store_copy_is_marked_from_the_public_build_only(tmp_path):
    m = _mod()
    data = tmp_path / "QuantiSheet" / "_internal" / "app" / "data"
    data.mkdir(parents=True)
    (data / "build.json").write_text('{"edition": "public"}')
    p = m.mark_store(str(tmp_path), "Example.QuantiSheet")
    assert json.load(open(p)) == {"edition": "store",
                                  "package": "Example.QuantiSheet"}
    import pytest
    with pytest.raises(SystemExit):              # already not public
        m.mark_store(str(tmp_path), "Example.QuantiSheet")


def test_store_edition_only_inside_its_package():
    from app import betalicense as b
    stamp = {"edition": "store", "package": "Example.QuantiSheet"}
    full = "Example.QuantiSheet_1.0.0.0_x64__abc123"
    assert b._is_store_copy(stamp, full)
    assert not b._is_store_copy(stamp, "")                 # not packaged
    assert not b._is_store_copy(stamp, "Other.App_1.0.0.0_x64__abc")
    assert not b._is_store_copy({"edition": "public"}, full)
    assert not b._is_store_copy({"edition": "store"}, full)


def test_store_manifest_adds_no_printer():
    m = _mod()
    assert "QuantiSheetPrinter" not in m.MANIFEST
    assert "startupTask" not in m.MANIFEST


import os as _os
import pytest as _pytest


@_pytest.mark.skipif(_os.name != "nt", reason="Windows paths")
def test_store_copy_found_from_its_protected_folder(monkeypatch):
    """Backup when Windows doesn't report the package name (Chief r45 #5):
    only a program inside Program Files\\WindowsApps counts."""
    from app import betalicense as b
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    exe = (r"C:\Program Files\WindowsApps"
           r"\Example.QuantiSheet_1.0.0.0_x64__abc\QuantiSheet.exe")
    assert b._package_from_path(exe) == \
        "Example.QuantiSheet_1.0.0.0_x64__abc"
    assert b._package_from_path(
        r"D:\Elsewhere\WindowsApps\Example.QuantiSheet_1\QuantiSheet.exe") == ""
    assert b._package_from_path("") == ""


def test_store_title_bar_never_says_beta(monkeypatch):
    from app import betalicense as b
    monkeypatch.setattr(b, "is_store", lambda: True)
    monkeypatch.setattr(b, "current", lambda: {"n": "Example Tester"})
    assert b.label() == ""


def test_store_splash_replaces_the_company_one(tmp_path):
    """Jon, Oct 30: the Store copy shows QuantiSheet only."""
    import hashlib
    m = _mod()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    store = os.path.join(root, "splash_store.png")
    company = os.path.join(root, "splash.png")
    if not os.path.isfile(store):
        # the Store splash is an owner's file kept out of git
        _pytest.skip("splash_store.png isn't in this copy (not in git)")
    assert os.path.isfile(store)
    # Nov 3 (Jon): no company is built into anyone's splash any more -
    # the company saved on a computer is drawn on at start - so the two
    # files may now be the same picture; the Store copy still gets its own
    assert os.path.isfile(company)
    _ = hashlib
    inner = tmp_path / "_internal"
    inner.mkdir()
    (inner / "splash.png").write_bytes(b"company")
    done = m.store_splash(str(tmp_path))
    assert len(done) == 1
    assert (inner / "splash.png").read_bytes() == open(store, "rb").read()
