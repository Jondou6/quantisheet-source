"""tools/make_winget.py (0.12.21): manifests from SHA256SUMS.txt."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import make_winget  # noqa: E402

H1, H2 = "a" * 64, "B" * 64


def _sums(tmp_path, v="0.12.21"):
    p = tmp_path / "SHA256SUMS.txt"
    p.write_text(f"{H1}  QuantiSheet-Public-Beta-Setup-{v}.exe\n"
                 f"{H2}  QuantiSheet-Public-Beta-Server-Setup-{v}.exe\n")
    return str(p)


def test_manifests_from_the_sums(tmp_path):
    out = tmp_path / "w"
    assert make_winget.main(["--repo", "someone/quantisheet", "--version",
                             "0.12.21", "--sums", _sums(tmp_path),
                             "--out", str(out)]) == 0
    inst = (out / "QuantiSheet.QuantiSheet.installer.yaml").read_text()
    assert "InstallerType: inno" in inst and "Scope: machine" in inst
    assert H1.upper() in inst and H2 in inst
    assert "ProductCode: '{375F90B3-3B41-4FE9-B790-B29C6D30C75E}_is1'" in inst
    assert "ProductCode: '{6A0E2C4B-9F31-4D2B-8C55-3B1D2E7F9A40}_is1'" in inst
    assert ("https://github.com/someone/quantisheet/releases/download/v0.12.21/"
            "QuantiSheet-Public-Beta-Server-Setup-0.12.21.exe") in inst
    assert (out / "QuantiSheet.QuantiSheet.locale.en-US.yaml").exists()
    assert (out / "QuantiSheet.QuantiSheet.yaml").exists()
    loc = (out / "QuantiSheet.QuantiSheet.locale.en-US.yaml").read_text()
    assert "PackageName: QuantiSheet (Beta)" in loc
    assert "Publisher: QuantiSheet" in loc
    assert "PackageIdentifier: QuantiSheet.QuantiSheet" in inst


def test_bad_input_refused(tmp_path):
    sums = make_winget.read_sums(_sums(tmp_path))
    for repo in ("", "no-slash", "a/b; rm", "../x/y", "a/..", "a/."):
        with pytest.raises(ValueError):
            make_winget.manifests("0.12.21", repo, sums)
    with pytest.raises(ValueError):                  # not in the sums
        make_winget.manifests("0.12.22", "a/b", sums)
    with pytest.raises(ValueError):
        make_winget.manifests("0.12", "a/b", sums)
