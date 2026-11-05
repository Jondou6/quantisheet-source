"""Files saved under the program's old name, converted to QuantiSheet's
names when they are opened (Jon, Oct 30: everything is QuantiSheet now;
files saved before still open).

This is the ONE place that knows the old name. Nothing new is ever written
under it:

* job data inside a PDF (takeoffs, estimate, logs...) was stored in
  embedded files named "pdfstudio_*.json"; a PDF that still has them gets
  them renamed to "quantisheet_*.json" in memory the moment it is opened
  (install() hooks every open), so the rest of the program only knows the
  new names, and the next save writes them;
* a markup's id began "pdfstudio-op:" (annotate.tag_of reads both);
* a Project Center job kept its data in a ".pdfstudio" folder: job_dir()
  renames it to ".quantisheet" the first time the job is opened;
* a building plan file's schema was "pdfstudio.genset_plan/N";
* the starter cost book was "PDF Studio Starter <year>" in a price
  database (pricedb renames it there when the database opens);
* the sign-in remembered under HKCU\\Software\\PDFStudio\\Cache and the
  license clock under %LOCALAPPDATA%\\PDFStudio are carried over once
  (onboard / betalicense), so nobody has to sign in again;
* Back Office time cards brought in from a job were marked "pdfstudio"
  (timeentry still recognises them, so none comes in twice).
"""
import logging
import os

log = logging.getLogger(__name__)

OLD = "pdfstudio"                        # the old name, as one word
EMB_OLD = "pdfstudio_"                   # embedded job-data files
EMB_NEW = "quantisheet_"
TAG_OLD = "pdfstudio-op:"                # annotation ids
JOB_DIR_OLD = ".pdfstudio"               # a job's data folder
JOB_DIR_NEW = ".quantisheet"
GENSET_OLD = ("pdfstudio.genset_plan/1", "pdfstudio.genset_plan/2")
STARTER_OLD = "PDF Studio Starter"
STARTER = "QuantiSheet Starter"
REG_CACHE_OLD = r"Software\PDFStudio\Cache"
REG_CACHE = r"Software\QuantiSheet\Cache"
LOCAL_DIR_OLD = "PDFStudio"              # %LOCALAPPDATA%\<this>\.seen
BO_SOURCE_OLD = "pdfstudio"              # Back Office time-card source
BO_KEY_OLD = "pdfstudio:timecard:"


def new_emb_name(name):
    """"pdfstudio_x.json" -> "quantisheet_x.json"; other names unchanged."""
    if isinstance(name, str) and name.startswith(EMB_OLD):
        return EMB_NEW + name[len(EMB_OLD):]
    return name


def convert_doc(doc):
    """Rename the old-named job data in an open PDF (in memory; the next
    save keeps it). Returns the number of files renamed."""
    try:
        if not getattr(doc, "is_pdf", False) or doc.needs_pass or \
                not doc.embfile_count():
            return 0
    except Exception:                                    # noqa: BLE001
        return 0
    from . import embfiles
    names = embfiles.names(doc)
    olds = [n for n in names if n.startswith(EMB_OLD)]
    done = 0
    for old in olds:
        new = new_emb_name(old)
        try:
            data = bytes(embfiles.get(doc, old))
            if new not in names:
                embfiles.put(doc, new, data)
            embfiles.delete(doc, old)
            done += 1
        except Exception:                                # noqa: BLE001
            log.warning("could not convert %s in %s", old,
                        getattr(doc, "name", ""), exc_info=True)
    if done:
        log.info("converted %d job data file(s) in %s to QuantiSheet "
                 "names", done, getattr(doc, "name", "") or "a PDF")
    return done


def install():
    """Convert every PDF the program opens (fitz.open / fitz.Document)."""
    import fitz
    cls = fitz.Document
    if getattr(cls, "_qs_converts_old_names", False):
        return
    orig = cls.__init__

    def __init__(self, *a, **k):
        orig(self, *a, **k)
        try:
            convert_doc(self)
        except Exception:                                # noqa: BLE001
            log.warning("old-name check failed", exc_info=True)
    __init__.__wrapped__ = orig
    cls.__init__ = __init__
    cls._qs_converts_old_names = True


def new_book_name(name):
    """A cost book name saved before the rename -> today's ("PDF Studio
    Starter 2026" -> "QuantiSheet Starter 2026", also inside derived names
    like "RSMeans + ...")."""
    if isinstance(name, str) and STARTER_OLD in name:
        return name.replace(STARTER_OLD, STARTER)
    return name


def convert_price_db(con):
    """Rename the starter book saved under the old name in a price
    database (books, rates, items, history, jobs; the shipped-book marks),
    in the caller's transaction. A book already there under the new name
    is left alone (UPDATE OR IGNORE). Returns True when anything changed."""
    like = "%" + STARTER_OLD + "%"
    if con.execute("SELECT 1 FROM books WHERE name LIKE ? LIMIT 1",
                   (like,)).fetchone() is None:
        return False
    for table, col in (("books", "name"), ("rates", "book"),
                       ("items", "book"), ("history", "book"),
                       ("jobs", "book")):
        con.execute(f"UPDATE OR IGNORE {table} SET {col} = "
                    f"REPLACE({col}, ?, ?) WHERE {col} LIKE ?",
                    (STARTER_OLD, STARTER, like))
    row = con.execute("SELECT value FROM meta WHERE key='shipped'").fetchone()
    if row is not None:
        import json
        try:
            marks = json.loads(row[0])
            if isinstance(marks, dict):
                marks = {new_book_name(k): v for k, v in marks.items()}
                con.execute("UPDATE meta SET value=? WHERE key='shipped'",
                            (json.dumps(marks),))
        except (TypeError, ValueError):
            pass
    log.info("price database: the starter book now has its QuantiSheet "
             "name")
    return True


def reg_cache():
    """HKCU key of the remembered sign-in and license
    (Software\\QuantiSheet\\Cache). The values saved under the old key are
    copied over the first time, then the old key is removed."""
    try:
        import winreg
    except ImportError:
        return REG_CACHE
    if _reg_cache_done:
        return REG_CACHE
    _reg_cache_done.append(True)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_CACHE_OLD) as old:
            values = []
            i = 0
            while True:
                try:
                    values.append(winreg.EnumValue(old, i))
                except OSError:
                    break
                i += 1
    except OSError:
        return REG_CACHE                       # nothing saved under the old
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_CACHE) as new:
            for name, value, kind in values:
                try:
                    winreg.QueryValueEx(new, name)     # newer value wins
                except OSError:
                    winreg.SetValueEx(new, name, 0, kind, value)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_CACHE_OLD)
        parent = REG_CACHE_OLD.rsplit("\\", 1)[0]
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, parent)  # if empty
        except OSError:
            pass
        log.info("sign-in and license memory moved to %s", REG_CACHE)
    except OSError:
        log.warning("could not move %s", REG_CACHE_OLD, exc_info=True)
    return REG_CACHE


_reg_cache_done = []


def old_seen_file():
    """The license clock's file under the old folder name, or None."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), ".cache")
    p = os.path.join(base, LOCAL_DIR_OLD, ".seen")
    return p if os.path.isfile(p) else None


def job_dir(folder):
    """A job folder's data folder: <folder>\\.quantisheet, renamed from the
    old <folder>\\.pdfstudio the first time it is used."""
    new = os.path.join(folder, JOB_DIR_NEW)
    old = os.path.join(folder, JOB_DIR_OLD)
    if not os.path.exists(new) and os.path.isdir(old):
        try:
            os.rename(old, new)
            log.info("job data folder renamed to %s", new)
        except OSError:
            log.warning("could not rename %s; reading it where it is", old,
                        exc_info=True)
            return old
    return new


def job_dir_if_any(folder):
    """The job's data folder when the job exists (either name), without
    renaming anything - for scans that only read (the dashboard)."""
    for name in (JOB_DIR_NEW, JOB_DIR_OLD):
        p = os.path.join(folder, name)
        if os.path.isdir(p):
            return p
    return None
