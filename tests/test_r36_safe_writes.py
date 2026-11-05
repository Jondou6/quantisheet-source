"""r36 v2 step 5 (safety): the files the estimating tools write.

  * every file is written to a temporary name and then put in place in
    one step (a crash or a full disk never leaves half a file, and the
    old file stays as it was);
  * a backup copy is made before a supplier price list is replaced;
  * a bad or cut-off CSV / Excel file gives a clear message naming the
    file, and nothing is written;
  * files the tools save on their own (templates, starter templates,
    service records, backups) go only inside your data folder; a file
    you pick may not go in a system folder, QuantiSheet's program folder,
    a database file or QuantiSheet's own settings;
  * every file window opens in your data folder.
Made-up data only."""
import glob
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, settings     # noqa: E402
from app.estimating import (_io, bid_items, bidday, quotes, service,  # noqa: E402,E501
                            starters, supplier_prices, templates)
from estimate_helpers import blank_doc                          # noqa: E402

GOOD = "SKU,Description,Unit,Price\nT1,Test pipe,LF,3.50\nT2,Test tee,EA,9\n"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    os.makedirs(settings.DIR, exist_ok=True)


def _leftovers(folder):
    return [f for f in os.listdir(folder)
            if f.endswith((".part", ".tmp")) or ".tmp" in f]


# ---- atomic writes ----------------------------------------------------------

@pytest.mark.parametrize("kind", ["json", "csv", "xlsx", "pdf"])
def test_a_failed_write_leaves_the_old_file_and_no_temp_file(
        tmp_path, monkeypatch, kind):
    p = tmp_path / f"keep.{kind}"
    p.write_bytes(b"old contents")
    real = os.replace

    def fail(a, b):
        raise OSError("disk full (test)")
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        if kind == "json":
            _io.write_json(str(p), {"a": 1})
        elif kind in ("csv", "xlsx"):
            _io.write_table(str(p), ["A"], [["1"]])
        else:
            d = blank_doc()
            EL.add(d, [EL.new_line("Test", 1, "ea", mat=5)])
            quotes.save_pdf(d, str(p), quotes.blank(), comp={"name": "T"},
                            data={"project": "T"})
    monkeypatch.setattr(os, "replace", real)
    assert p.read_bytes() == b"old contents"
    assert _leftovers(str(tmp_path)) == []


# ---- backups ---------------------------------------------------------------

def test_replacing_a_supplier_price_list_backs_up_the_old_one(tmp_path):
    src = tmp_path / "list.csv"
    src.write_text(GOOD, encoding="utf-8")
    out = tmp_path / "Test supply.json"
    supplier_prices.import_file(str(src), "Test Supply", str(out))
    old = out.read_bytes()
    src.write_text(GOOD.replace("3.50", "4.25"), encoding="utf-8")
    with pytest.raises(supplier_prices.PriceListError):
        supplier_prices.import_file(str(src), "Test Supply", str(out))
    assert out.read_bytes() == old
    r = supplier_prices.import_file(str(src), "Test Supply", str(out),
                                    overwrite=True)
    assert out.read_bytes() != old
    baks = glob.glob(os.path.join(settings.DIR, "backups", "*.json"))
    assert len(baks) == 1 and open(baks[0], "rb").read() == old
    assert r.get("backup") == baks[0]


# ---- bad or partial CSV / Excel -------------------------------------------

BAD = {"binary.csv": b"\x00\xff\xfe\x00PK\x03\x04" * 50,
       "nul.csv": b"SKU,Description,Unit,Price\nT1,Te\x00st,LF,3\n",
       "broken.xlsx": b"not really a workbook",
       "unclosed.csv": b'SKU,Description,Unit,Price\n"T1,Test pipe,LF,3\n',
       "empty.csv": b"",
       "header_only.csv": b"SKU,Description,Unit,Price\n"}


@pytest.mark.parametrize("name", sorted(BAD))
def test_bad_or_partial_price_file_clear_message_nothing_written(
        tmp_path, name):
    src = tmp_path / name
    src.write_bytes(BAD[name])
    out = tmp_path / "new list.json"
    with pytest.raises(ValueError) as e:
        supplier_prices.import_file(str(src), "Test Supply", str(out))
    msg = str(e.value)
    assert msg and len(msg) < 300
    assert not out.exists()
    keep = tmp_path / "kept.json"
    keep.write_bytes(b"{}")
    with pytest.raises(ValueError):
        supplier_prices.import_file(str(src), "Test Supply", str(keep),
                                    overwrite=True)
    assert keep.read_bytes() == b"{}"
    assert _leftovers(str(tmp_path)) == []


@pytest.mark.parametrize("name", ["binary.csv", "nul.csv", "broken.xlsx",
                                  "unclosed.csv"])
def test_bad_file_names_the_file_and_says_what_is_wrong(tmp_path, name):
    src = tmp_path / name
    src.write_bytes(BAD[name])
    for fn in (supplier_prices.read, bid_items.import_items,
               lambda p: bidday.read_csv(p, "Test")):
        with pytest.raises(_io.TableError) as e:
            fn(str(src))
        assert name in str(e.value)


def test_good_cp1252_csv_still_reads(tmp_path):
    src = tmp_path / "excel.csv"
    src.write_bytes("SKU,Description,Unit,Price\nT1,Caf\xe9 pipe,LF,3\n"
                    .encode("cp1252"))
    head, rows = supplier_prices.read(str(src))
    assert rows == [["T1", "Caf\xe9 pipe", "LF", "3"]]


def test_bid_day_bad_csv_leaves_the_drawing_unchanged(tmp_path):
    d = blank_doc()
    before = d.embfile_names()
    src = tmp_path / "unclosed.csv"
    src.write_bytes(BAD["unclosed.csv"])
    with pytest.raises(ValueError):
        bidday.save(d, bidday.read_csv(str(src), "Test"))
    assert d.embfile_names() == before
    assert bidday.load(d, "Test") is None


# ---- where files go -------------------------------------------------------

def test_automatic_files_stay_inside_the_data_folder():
    with pytest.raises(_io.PathError):
        _io.data_file("..", "outside.json")
    with pytest.raises(_io.PathError):
        _io.data_file(os.path.abspath(os.sep), "outside.json")
    p = _io.data_file("estimate_templates", "x.json")
    assert p.startswith(os.path.realpath(settings.DIR) + os.sep)
    t = templates.from_pay_items({"pay_items": []}, "../../../evil")
    saved = templates.save(t)
    assert os.path.realpath(saved).startswith(
        os.path.realpath(settings.DIR) + os.sep)
    for f in starters.install()["written"]:
        assert os.path.realpath(f).startswith(
            os.path.realpath(templates.folder()) + os.sep)
    assert os.path.realpath(service.default_path()).startswith(
        os.path.realpath(settings.DIR) + os.sep)


def test_a_link_out_of_the_data_folder_is_refused(tmp_path):
    away = tmp_path / "elsewhere"
    away.mkdir()
    try:
        os.symlink(str(away), os.path.join(settings.DIR, "estimate_templates"),
                   target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this PC can't make links (Windows needs Developer Mode)")
    t = templates.from_pay_items({"pay_items": []}, "Test")
    with pytest.raises(_io.PathError):
        templates.save(t)
    assert os.listdir(str(away)) == []


def test_picked_files_refused_in_system_and_program_folders(
        tmp_path, monkeypatch):
    pf = tmp_path / "Program Files"
    pf.mkdir()
    monkeypatch.setenv("ProgramFiles", str(pf))
    for bad in (str(pf / "x.json"), os.path.join(_io.APP_DIR, "x.json"),
                str(tmp_path / "prices.db"),
                os.path.join(settings.DIR, "settings.json")):
        with pytest.raises(_io.PathError):
            _io.write_json(bad, {"a": 1})
        assert not os.path.exists(bad) or bad.endswith("settings.json")
    if os.name != "nt":
        with pytest.raises(_io.PathError):
            _io.check_user_path("/etc/quantisheet_test.json")
    ok = _io.write_json(str(tmp_path / "mine.json"), {"a": 1})
    assert os.path.isfile(ok)


# ---- file windows start in the data folder -------------------------------

def test_file_windows_open_in_the_data_folder(monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog
    from app.estimating import ui
    QApplication.instance() or QApplication([])
    seen = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(
        lambda *a, **k: seen.append(("save", a[2])) or ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(
        lambda *a, **k: seen.append(("open", a[2])) or ("", "")))
    ui._save_name(None, "T", "Estimate check.csv", "CSV (*.csv)")
    ui._open_name(None, "T", "CSV (*.csv)")
    assert seen == [("save", os.path.join(settings.DIR, "Estimate check.csv")),
                    ("open", settings.DIR)]
    src = open(ui.__file__, encoding="utf-8").read()
    assert src.count("QFileDialog.get") == 2          # only those two
