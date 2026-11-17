"""Read a set's title-block scales in a separate process (Nov 16).

MuPDF keeps Python's lock while it reads text, so reading the scales of a
big set on a thread still froze the window: on a real 100 MB, 32-sheet
set, opening it took 14 s before the window answered. This reads them in
its own process, which opens the file from disk; the window only waits
on the pipe, which lets go of the lock.

Imports nothing heavy at module level, so the process starts quickly.
"""
import logging

log = logging.getLogger("quantisheet")
TIMEOUT_S = 240.0


def _child(path, pages, conn):                       # runs in the child
    try:
        import fitz
        from . import autoscale
        d = fitz.open(path)
        try:
            rows = autoscale.detect(d, pages=pages, use_ocr=False)
        finally:
            d.close()
        conn.send(("ok", rows))
    except Exception as e:                            # noqa: BLE001
        try:
            conn.send(("err", f"{e.__class__.__name__}: {e}"))
        except Exception:                             # noqa: BLE001
            pass
    finally:
        conn.close()


def _labels_child(path, pages, conn):                # runs in the child
    try:
        import fitz
        from . import sheets
        out = {}
        with fitz.open(path) as d:
            for i in pages:
                pg = d[i]
                try:
                    lab = sheets.label_for(pg) or ""
                except Exception:                     # noqa: BLE001
                    lab = ""
                out[(pg.xref, tuple(pg.get_contents()))] = lab
        conn.send(("ok", out))
    except Exception as e:                            # noqa: BLE001
        try:
            conn.send(("err", f"{e.__class__.__name__}: {e}"))
        except Exception:                             # noqa: BLE001
            pass
    finally:
        conn.close()


def _run(target, path, pages, timeout):
    import multiprocessing
    ctx = multiprocessing.get_context("spawn")
    mine, theirs = ctx.Pipe(duplex=False)
    p = ctx.Process(target=target, args=(path, list(pages), theirs),
                    name="QuantiSheet-read", daemon=True)
    p.start()
    theirs.close()
    try:
        if not mine.poll(timeout):
            raise RuntimeError("reading the set took too long")
        kind, value = mine.recv()
    except EOFError:
        raise RuntimeError("the reader stopped") from None
    finally:
        mine.close()
        p.join(2)
        if p.is_alive():
            p.terminate()
    if kind != "ok":
        raise RuntimeError(value)
    return value


def sheet_labels(path, pages, timeout=TIMEOUT_S):
    """{(page xref, contents xrefs): 'A-101 - FLOOR PLAN'} for Ctrl+K,
    read in another process (the same keys quickaccess.palette_extras
    keeps)."""
    return _run(_labels_child, path, pages, timeout)


def scale_rows(path, pages, timeout=TIMEOUT_S):
    """autoscale.detect(...) rows for `pages` of the file at `path`, read
    in another process. Raises RuntimeError when the process fails or
    takes longer than `timeout` seconds."""
    return _run(_child, path, pages, timeout)
