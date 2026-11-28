"""tools/clean_release.py keeps the newest three versions of each product
and only moves the rest into release/_to_delete (made-up empty files)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import clean_release as cr                                  # noqa: E402


def _touch(p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").close()


def test_keeps_the_newest_three_and_moves_the_rest(tmp_path):
    rel = tmp_path / "release"
    for v in ("1.1.9", "1.1.10", "1.1.30", "1.1.31", "1.1.32"):
        _touch(str(rel / f"QuantiSheet-Beta-Setup-{v}.exe"))
        _touch(str(rel / f"QuantiSheet {v} - Whats New.pdf"))
        _touch(str(rel / "github" / f"QuantiSheet-Public-Beta-Setup-{v}.exe"))
        _touch(str(rel / "r2_upload" / "f0" / "team" /
                   f"QuantiSheet-Beta-Setup-{v}.exe"))
    for v in ("0.1.0", "0.2.0", "0.2.1", "0.2.2"):
        _touch(str(rel / f"ClaimIT-Setup-{v}.exe"))
    for keep in ("SHA256SUMS.txt", "READ ME FIRST.txt"):
        _touch(str(rel / "github" / keep))
    _touch(str(rel / "r2_upload" / "f0" / "team" / "version.json"))
    _touch(str(rel / "Old" / "PDF Studio 0.12.1 - Whats New.pdf"))
    moves = cr.plan(str(rel))
    names = sorted(os.path.relpath(s, rel).replace("\\", "/")
                   for s, _d, _b in moves)
    assert names == sorted([
        "ClaimIT-Setup-0.1.0.exe", "Old",
        "QuantiSheet 1.1.9 - Whats New.pdf",
        "QuantiSheet 1.1.10 - Whats New.pdf",
        "QuantiSheet-Beta-Setup-1.1.9.exe",
        "QuantiSheet-Beta-Setup-1.1.10.exe",
        "github/QuantiSheet-Public-Beta-Setup-1.1.9.exe",
        "github/QuantiSheet-Public-Beta-Setup-1.1.10.exe",
        "r2_upload/f0/team/QuantiSheet-Beta-Setup-1.1.9.exe",
        "r2_upload/f0/team/QuantiSheet-Beta-Setup-1.1.10.exe"])
    cr.move(moves)
    assert (rel / "_to_delete" / "github" /
            "QuantiSheet-Public-Beta-Setup-1.1.9.exe").exists()
    assert (rel / "_to_delete" / "Old").is_dir()
    assert (rel / "QuantiSheet-Beta-Setup-1.1.30.exe").exists()
    assert (rel / "github" / "SHA256SUMS.txt").exists()
    assert (rel / "r2_upload" / "f0" / "team" / "version.json").exists()
    assert cr.plan(str(rel)) == []                  # nothing left to move
