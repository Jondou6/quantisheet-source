"""v4: sign/verify on corrupt or non-PDF input must print a one-line
error and exit nonzero, not dump a traceback."""
import pytest

from app import cli

GOOD = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"


def _bad_files(tmp_path):
    files = {
        "zero.pdf": b"",
        "notpdf.pdf": b"hello this is not a pdf" * 100,
        "trunc_head.pdf": GOOD,  # header but no xref / EOF
    }
    out = []
    for name, data in files.items():
        p = tmp_path / name
        p.write_bytes(data)
        out.append(str(p))
    return out


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_verify_bad_pdf_clean_error(tmp_path, capsys, idx):
    src = _bad_files(tmp_path)[idx]
    rc = cli.main(["verify", src])
    err = capsys.readouterr().err
    assert rc == 1
    assert err.startswith("error: ")
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1


@pytest.mark.parametrize("idx", [0, 1, 2])
def test_sign_bad_pdf_clean_error(tmp_path, capsys, monkeypatch, idx):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    src = _bad_files(tmp_path)[idx]
    out = tmp_path / "signed.pdf"
    rc = cli.main(["sign", src, str(out)])
    err = capsys.readouterr().err
    assert rc == 1
    assert err.startswith("error: ")
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1
    assert not out.exists()
