"""Review 0.13.9 #1, #2, #10: the files beside the installers are made for
the version being built."""
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import release_files  # noqa: E402


def _tree(tmp, version):
    gh = tmp / "release" / "github"
    gh.mkdir(parents=True)
    (tmp / "docs").mkdir()
    (gh / f"QuantiSheet-Public-Beta-Setup-{version}.exe").write_bytes(b"a")
    (gh / f"QuantiSheet-Public-Beta-{version}.msi").write_bytes(b"b")
    (gh / "SHA256SUMS.txt").write_text("deadbeef  Stale-Setup-0.12.26.exe\n")
    (gh / "RELEASE_NOTES.md").write_text("# Stale notes 0.12.26\n")
    (tmp / "release" / f"QuantiSheet-Beta-Setup-{version}.exe").write_bytes(
        b"c")
    return gh


def test_sums_cover_every_installer_and_match(tmp_path):
    gh = _tree(tmp_path, "9.9.9")
    release_files.refresh(str(tmp_path), "9.9.9")
    lines = (gh / "SHA256SUMS.txt").read_text().splitlines()
    names = {ln.split("  ", 1)[1]: ln.split("  ", 1)[0] for ln in lines}
    for p in gh.iterdir():
        if p.suffix.lower() in (".exe", ".msi"):
            assert names[p.name] == hashlib.sha256(
                p.read_bytes()).hexdigest()
    assert "Stale-Setup-0.12.26.exe" not in names


def test_release_notes_are_this_versions(tmp_path):
    gh = _tree(tmp_path, "9.9.9")
    release_files.refresh(str(tmp_path), "9.9.9")
    assert not (gh / "RELEASE_NOTES.md").exists()       # stale one gone
    (tmp_path / "docs" / "GITHUB_RELEASE_9.9.9.md").write_text(
        "# QuantiSheet 9.9.9 (beta)\n")
    release_files.refresh(str(tmp_path), "9.9.9")
    t = (gh / "RELEASE_NOTES.md").read_text()
    assert "9.9.9" in t and "QuantiSheet" in t


def test_read_me_first_is_in_the_release_folder(tmp_path):
    _tree(tmp_path, "9.9.9")
    release_files.refresh(str(tmp_path), "9.9.9")
    t = (tmp_path / "release" / "READ ME FIRST.txt").read_text()
    sha = hashlib.sha256(b"c").hexdigest().upper()
    assert sha in t and "QuantiSheet-Beta-Setup-9.9.9.exe" in t


def test_source_zip_leaves_out_the_server_secret():
    import zip_source
    assert not zip_source.wanted("server/data/secret")
    assert not zip_source.wanted("server/data/rooms.json")
    assert zip_source.wanted("server/relaycore.py")


def test_every_setup_script_stamps_its_file_version():
    for iss in ("quantisheet.iss", "quantisheet_server.iss",
                "quantisheet_claims.iss"):
        t = open(os.path.join(ROOT, "installer", iss), encoding="utf-8",
                 errors="replace").read()
        assert "VersionInfoVersion={#AppVersion}" in t, iss


def test_pyproject_version_matches_the_program():
    """Review r41 F08: pyproject.toml said 0.13.9 while the program was
    0.13.13."""
    import re
    from app import __version__
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "pyproject.toml"), encoding="utf-8") as f:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
    assert m and m.group(1) == __version__
