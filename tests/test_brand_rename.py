"""Files saved under the program's earlier name still open, converted to
QuantiSheet's names (app/oldnames.py - Jon, Oct 30: keep old files
readable, write only the new names)."""
import json
import os
import sqlite3
import sys
import types

import fitz
import pytest

from app import embfiles, oldnames


def _old_pdf(path):
    d = fitz.open()
    d.new_page()
    d.embfile_add("pdfstudio_estimate.json", b'{"lines": [1, 2]}')
    d.embfile_add("pdfstudio_scale.json", b'{"0": 48}')
    d.embfile_add("other.txt", b"someone else's file")
    d.save(path)
    d.close()


def test_old_job_data_is_renamed_when_the_pdf_opens(tmp_path):
    p = str(tmp_path / "old.pdf")
    _old_pdf(p)
    d = fitz.open(p)                  # the hook converts on open
    names = set(embfiles.names(d))
    assert names == {"quantisheet_estimate.json", "quantisheet_scale.json",
                     "other.txt"}
    assert bytes(embfiles.get(d, "quantisheet_estimate.json")) == \
        b'{"lines": [1, 2]}'
    d.saveIncr()                      # the next save keeps the new names
    d.close()
    with open(p, "rb") as f:
        raw = f.read()
    assert b"quantisheet_scale.json" in raw
    d = fitz.open(p)
    assert not any(n.startswith("pdfstudio_") for n in embfiles.names(d))


def test_convert_keeps_a_newer_file_already_there(tmp_path):
    d = fitz.open()
    d.new_page()
    d.embfile_add("pdfstudio_qa.json", b"old")
    d.embfile_add("quantisheet_qa.json", b"new")
    assert oldnames.convert_doc(d) == 1
    assert embfiles.names(d) == ["quantisheet_qa.json"]
    assert bytes(embfiles.get(d, "quantisheet_qa.json")) == b"new"


def test_new_names_and_plain_pdfs_are_left_alone(tmp_path):
    d = fitz.open()
    d.new_page()
    assert oldnames.convert_doc(d) == 0
    d.embfile_add("quantisheet_money.json", b"{}")
    assert oldnames.convert_doc(d) == 0
    assert oldnames.new_emb_name("pdfstudio_x.json") == "quantisheet_x.json"
    assert oldnames.new_emb_name("x.json") == "x.json"


def test_markups_saved_with_the_old_id_are_still_found():
    from app import annotate
    d = fitz.open()
    pg = d.new_page()
    a = pg.add_rect_annot(fitz.Rect(10, 10, 50, 50))
    d.xref_set_key(a.xref, "NM", fitz.get_pdf_str("pdfstudio-op:abc"))
    b = pg.add_rect_annot(fitz.Rect(60, 60, 90, 90))
    annotate._tag(d, b, "def")
    tags = {annotate.tag_of(x) for x in pg.annots()}
    assert tags == {"abc", "def"}
    assert annotate.is_applied(pg, "abc") and annotate.is_applied(pg, "def")
    assert len(annotate.find_annots(pg, {"target": "abc"})) == 1
    assert (b.info or {}).get("id") == "quantisheet-op:def" or \
        any((x.info or {}).get("id") == "quantisheet-op:def"
            for x in pg.annots())


def test_old_job_folder_is_renamed_when_the_job_opens(tmp_path, monkeypatch):
    from app import settings
    from app.pm.store import ProjectStore
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    job = tmp_path / "Example Job"
    old = job / ".pdfstudio"
    (old / "attachments").mkdir(parents=True)
    (old / "project.json").write_text(json.dumps(
        {"name": "Example Job", "collections": {}}), encoding="utf-8")
    (old / "attachments" / "a.jpg").write_bytes(b"x")
    assert ProjectStore.exists(str(job))           # found under the old name
    from app import dashboard
    assert dashboard.project_file(str(job)).endswith(
        os.path.join(".pdfstudio", "project.json"))  # read only: not moved
    s = ProjectStore(str(job))
    assert s.name == "Example Job"
    assert not old.exists()
    assert (job / ".quantisheet" / "project.json").exists()
    assert (job / ".quantisheet" / "attachments" / "a.jpg").exists()
    assert ProjectStore.exists(str(job))


def test_old_plan_schema_reads_as_the_new_one():
    from app.genset import model
    p = model.from_json(json.dumps({"schema": "pdfstudio.genset_plan/2"}))
    assert p["schema"] == model.SCHEMA == "quantisheet.genset_plan/2"
    with pytest.raises(model.PlanError):
        model.from_json(json.dumps({"schema": "pdfstudio.genset_plan/9"}))


def test_starter_book_renamed_in_a_price_database(tmp_path):
    from app import pricedb
    con = sqlite3.connect(str(tmp_path / "p.db"))
    con.row_factory = sqlite3.Row
    con.executescript(pricedb.DDL)
    old = "PDF Studio Starter 2026"
    con.execute("INSERT INTO books (name) VALUES (?)", (old,))
    con.execute("INSERT INTO books (name) VALUES (?)", ("RSMeans + " + old,))
    con.execute("INSERT INTO items (book, code) VALUES (?, 'A')", (old,))
    con.execute("INSERT INTO rates (book, region, trade) VALUES (?, 'SC', "
                "'carp')", (old,))
    con.execute("INSERT INTO meta VALUES ('shipped', ?)",
                (json.dumps({"PDF Studio Starter 2026.json": {"v": 1}}),))
    assert oldnames.convert_price_db(con) is True
    names = {r[0] for r in con.execute("SELECT name FROM books")}
    assert names == {"QuantiSheet Starter 2026",
                     "RSMeans + QuantiSheet Starter 2026"}
    assert con.execute("SELECT book FROM items").fetchone()[0] == \
        "QuantiSheet Starter 2026"
    marks = json.loads(con.execute(
        "SELECT value FROM meta WHERE key='shipped'").fetchone()[0])
    assert list(marks) == ["QuantiSheet Starter 2026.json"]
    assert oldnames.convert_price_db(con) is False     # once
    assert oldnames.new_book_name(old) == "QuantiSheet Starter 2026"


def test_the_shipped_starter_book_has_the_new_name():
    from app import costbook
    names = os.listdir(costbook.SHIPPED)
    assert names == ["QuantiSheet Starter 2026.json"]
    with open(os.path.join(costbook.SHIPPED, names[0]),
              encoding="utf-8") as f:
        assert json.load(f)["name"] == "QuantiSheet Starter 2026"
    assert costbook.display_name("PDF Studio Starter 2026") == \
        "QuantiSheet Starter 2026"


class _FakeReg:
    """A stand-in winreg with one hive (nothing real is touched)."""
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self):
        self.keys = {}

    class _K:
        def __init__(self, reg, path, create):
            if path not in reg.keys:
                if not create:
                    raise OSError(path)
                reg.keys[path] = {}
            self.v = reg.keys[path]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, hive, path):
        return self._K(self, path, False)

    def CreateKey(self, hive, path):
        return self._K(self, path, True)

    def EnumValue(self, k, i):
        items = list(k.v.items())
        if i >= len(items):
            raise OSError("no more")
        n, (v, t) = items[i]
        return n, v, t

    def QueryValueEx(self, k, name):
        if name not in k.v:
            raise OSError(name)
        return k.v[name]

    def SetValueEx(self, k, name, _r, kind, value):
        k.v[name] = (value, kind)

    def DeleteKey(self, hive, path):
        if path not in self.keys or any(
                p.startswith(path + "\\") for p in self.keys if p != path):
            raise OSError(path)
        del self.keys[path]


def test_sign_in_memory_moves_to_the_quantisheet_key(monkeypatch):
    reg = _FakeReg()
    reg.keys[oldnames.REG_CACHE_OLD] = {"t": ("signed", 1), "k": ("key", 1)}
    reg.keys[oldnames.REG_CACHE] = {"k": ("newer", 1)}
    monkeypatch.setitem(sys.modules, "winreg", types.SimpleNamespace(
        **{n: getattr(reg, n) for n in dir(reg) if not n.startswith("_")}))
    monkeypatch.setattr(oldnames, "_reg_cache_done", [])
    assert oldnames.reg_cache() == r"Software\QuantiSheet\Cache"
    assert reg.keys[oldnames.REG_CACHE] == {"k": ("newer", 1),
                                            "t": ("signed", 1)}
    assert oldnames.REG_CACHE_OLD not in reg.keys


def test_license_clock_reads_the_old_folder_too(tmp_path, monkeypatch):
    from app import betalicense
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    old = tmp_path / "PDFStudio"
    old.mkdir()
    (old / ".seen").write_text("2030-01-02")
    assert betalicense._read_seen() == "2030-01-02"
    new = tmp_path / "QuantiSheet"
    new.mkdir()
    (new / ".seen").write_text("2029-05-05")
    assert betalicense._read_seen() == "2030-01-02"     # the later day
    assert betalicense._seen_file() == str(new / ".seen")
