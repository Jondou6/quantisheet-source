import fitz
from app import cli


def _mk(tmp_path, pages=1):
    d = fitz.open()
    for _ in range(pages):
        p = d.new_page()
        p.insert_text((40, 60), "shall fire rating")
    fp = str(tmp_path / "d.pdf")
    d.save(fp); d.close()
    return fp


def test_cli_rules_json(tmp_path, capsys):
    p = _mk(tmp_path)
    out = str(tmp_path / "o.pdf")
    rc = cli.main(["--json", "rules", p, out])
    assert rc == 0


def test_cli_verify_exit(tmp_path):
    p = _mk(tmp_path)
    rc = cli.main(["--json", "verify", p])
    assert rc in (0, 2)
