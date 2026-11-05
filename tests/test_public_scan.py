"""The public build's deep scan (Venice leftover): it reads inside files."""
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import build_installer as bi  # noqa: E402


def _tree(tmp_path):
    app = tmp_path / "_internal" / "app" / "data"
    app.mkdir(parents=True)
    (app / "ada2010.json").write_text(json.dumps({"a": "see ada.gov"}))
    (app / "beta_pubkey.txt").write_text("abc")
    (tmp_path / "_internal" / "certifi").mkdir()
    (tmp_path / "_internal" / "certifi" / "cacert.pem").write_text(
        "-----BEGIN CERTIFICATE-----\nx\n")
    (tmp_path / "_internal" / "LICENSE.txt").write_text(
        "written by someone@thirdparty.org")       # outside app: allowed
    return app


def test_clean_tree_passes(tmp_path):
    _tree(tmp_path)
    assert bi.deep_scan(str(tmp_path)) == []


def test_finds_private_key_sealed_blob_and_addresses(tmp_path):
    app = _tree(tmp_path)
    (app / "k.pem").write_text("-----BEGIN PRIVATE KEY-----\nzz")
    (app / "x.json").write_text(json.dumps({"salt": "a", "token": "b"}))
    (app / "people.csv").write_text("Bob,bob@private-co.test\n")
    found = bi.deep_scan(str(tmp_path))
    text = "; ".join(found)
    assert "private key" in text and "sealed contact" in text
    assert "e-mail addresses (1 domain(s))" in text
    assert "bob@" not in text and "private-co" not in text   # never printed


def test_looks_inside_zips(tmp_path):
    app = _tree(tmp_path)
    with zipfile.ZipFile(app / "pack.zip", "w") as z:
        z.writestr("inner/list.txt", "amy@hidden.test")
    assert any("pack.zip!inner/list.txt" in f
               for f in bi.deep_scan(str(tmp_path)))
