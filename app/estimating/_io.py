"""Small shared helpers for the estimating tools: safe CSV / Excel
writing (no live formulas from typed text), atomic JSON files at a path
the user picked, and a guard that keeps those files out of the program's
own folders (bundled data) and away from database files.

v2 step 5 (safety): every write goes to a temporary name first and is
put in place in one step (the old file stays as it was if anything
fails); files the tools save on their own only go inside the data folder
(data_file), never while another window is moving it; a file you pick
may not go in a system folder or over QuantiSheet's own settings; a bad
or cut-off CSV / Excel file gives a clear TableError naming the file;
backup_file() keeps a copy before a file is replaced."""
import csv
import io
import json
import os
from decimal import Decimal

from .. import safecell, safeio

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PathError(ValueError):
    pass


class TableError(PathError):
    """A CSV or Excel file that can't be read (nothing was written)."""


# QuantiSheet's own files in the data folder: never a save target
RESERVED_NAMES = ("settings.json",)
RESERVED_EXTS = (".log", ".lock", ".migrating")
POSIX_SYSTEM = ("/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/boot",
                "/sys", "/proc", "/dev", "/System", "/Library",
                "/Applications")
WINDOWS_SYSTEM_ENV = ("SystemRoot", "windir", "ProgramFiles",
                      "ProgramFiles(x86)", "ProgramW6432", "ProgramData")


def _real(p):
    return os.path.normcase(os.path.realpath(p))


def _inside(p, folder):
    try:
        f = _real(folder)
        return os.path.commonpath([_real(p), f]) == f
    except ValueError:                        # another drive (Windows)
        return False


def system_folders():
    out = [os.environ.get(k) for k in WINDOWS_SYSTEM_ENV]
    if os.name != "nt":
        out += list(POSIX_SYSTEM)
    return [f for f in out if f]


def _data_dir():
    from .. import settings
    return settings.DIR


def data_file(*parts):
    """A path inside the data folder (settings.DIR) for a file the tools
    save on their own; PathError if it would land anywhere else (a ..,
    an absolute part or a link out of the folder)."""
    base = _data_dir()
    p = os.path.abspath(os.path.join(base, *[str(x) for x in parts]))
    if not _inside(p, base) or _real(p) == _real(base):
        raise PathError("QuantiSheet only saves its own files inside your "
                        f"data folder ({base}).")
    return p


def backup_file(path, why="replaced"):
    """A copy of `path` in <data folder>/backups before it is replaced;
    the copy's path, or None when there's nothing to keep."""
    import datetime
    import re
    import shutil
    if not os.path.isfile(path):
        return None
    stem, ext = os.path.splitext(os.path.basename(path))
    stem = re.sub(r"[^A-Za-z0-9 ._-]+", "_", stem)[:60] or "file"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = data_file("backups", f"{stem}-before-{why}-{stamp}{ext}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    try:
        shutil.copyfile(path, tmp)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return dest


def _plain(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def check_user_path(path, exts=(".json",)):
    """The absolute path, or PathError: it must end in one of `exts`, must
    not be inside QuantiSheet's own program folder (its bundled data) and
    must not be a database file."""
    if not path or not str(path).strip():
        raise PathError("Pick a file name.")
    p = os.path.abspath(os.path.expanduser(str(path)))
    low = p.lower()
    if low.endswith((".db", ".sqlite", ".sqlite3")) or \
            os.path.basename(low) == "prices.db":
        raise PathError("That is a database file; pick a new file name.")
    if exts and not low.endswith(tuple(e.lower() for e in exts)):
        raise PathError("The file name must end in " + " or ".join(exts))
    if _inside(p, APP_DIR):
        raise PathError("Save your own files outside QuantiSheet's program "
                        "folder.")
    for f in system_folders() if not _inside(p, _data_dir()) else ():
        if _inside(p, f):
            raise PathError(f"{f} is a system folder; save in your own "
                            "folders (Documents, or QuantiSheet's data "
                            "folder).")
    base = os.path.basename(low)
    if base in RESERVED_NAMES or base.endswith(RESERVED_EXTS):
        if _inside(p, _data_dir()):
            raise PathError("That is one of QuantiSheet's own files; pick "
                            "a new file name.")
    return p


def write_json(path, data, exts=(".json",)):
    p = check_user_path(path, exts)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    safeio.atomic_write(p, json.dumps(data, indent=1, default=str))
    return p


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_table(path, header, rows, sheet="Sheet1"):
    """CSV or Excel (.xlsx) by the file name; risky text is kept as text."""
    p = check_user_path(path, (".csv", ".xlsx"))
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    rows = [[_plain(v) for v in r] for r in rows]
    if p.lower().endswith(".xlsx"):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = str(sheet)[:30] or "Sheet1"
        safecell.append_row(ws, list(header))
        for r in rows:
            safecell.append_row(ws, r)
        tmp = p + ".part"
        try:
            wb.save(tmp)
            os.replace(tmp, p)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        return p
    buf = io.StringIO()
    w = safecell.writer(buf)
    w.writerow(list(header))
    w.writerows(rows)
    safeio.atomic_write(p, buf.getvalue())
    return p


def _check_csv(path, name):
    """TableError for a CSV that isn't text, has NUL characters or a
    quote that never closes (a cut-off file)."""
    from ..textio import open_csv
    with open(path, "rb") as f:
        head = f.read(65536)
    if b"\x00" in head:
        raise TableError(f"{name} isn't a plain CSV text file (it has "
                         "binary data). Save it from Excel as CSV, or pick "
                         "the .xlsx workbook.")
    try:
        with open_csv(path) as f:
            for _row in csv.reader(f, strict=True):
                pass
    except csv.Error as e:
        raise TableError(f"{name} looks cut off or damaged ({e}); nothing "
                         "was imported. Save it again from Excel and retry."
                         ) from e


def read_table(path):
    """(header, rows) of a CSV or Excel file, every cell as text; a file
    that can't be read gives TableError naming it (and saying why)."""
    from .. import costbook
    low = str(path).lower()
    name = os.path.basename(str(path))
    if not low.endswith((".csv", ".txt", ".tsv", ".xlsx", ".xlsm")):
        raise PathError("Pick an Excel workbook (.xlsx) or a CSV file.")
    try:
        if not low.endswith((".xlsx", ".xlsm")):
            _check_csv(path, name)
        return costbook.read_sheet(path)
    except TableError:
        raise
    except FileNotFoundError as e:
        raise TableError(f"{name} isn't there any more.") from e
    except (OSError, ValueError, KeyError, IndexError, UnicodeError,
            csv.Error, Exception) as e:              # noqa: BLE001
        raise TableError(f"Can't read {name}: it isn't a readable "
                         f"{'Excel workbook' if low.endswith(('.xlsx', '.xlsm')) else 'CSV file'}"
                         f" ({type(e).__name__}). Nothing was imported."
                         ) from e


def norm(s):
    return " ".join(str(s or "").lower().split())


_ = csv                                   # csv dialect names used by callers
