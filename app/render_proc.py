"""The drawing process (Stage 4, Oct 19).

MuPDF keeps Python's lock while it draws, so a drawing thread still froze
the window (0.85 s gaps on the plant set). This runs in its own process:
it opens the same file from disk and draws the sheet itself - no markups;
the window adds those from the open document, so they are always current.

Imports nothing but fitz and the standard library, so the process starts
quickly. Talks over a multiprocessing Pipe:

  -> ("render", rid, path, page, zoom, clip, thin, sig)
       clip: None for the whole page, or (x0, y0, x1, y1) in page points
  <- ("img", rid, sig, x, y, w, h, stride, bytes)   sig: of the page on disk
  <- ("err", rid, message)
  -> ("segments", rid, path, page, sig)       lines of the drawing, for snap
  <- ("segs", rid, sig, count, bytes)         array('d'): x0 y0 x1 y1 ...
  -> ("count", rid, path)                     page count of a file
  <- ("count", rid, "12" | "?")
  -> ("stop",)
"""
import os
from collections import OrderedDict, deque


def page_sig(doc, pno):
    """What the sheet's drawing is made of. The window compares this with
    its own document: unsaved changes to the drawing (not markups) make
    them differ, and then it draws the page itself."""
    pg = doc[pno]
    parts = []
    for x in pg.get_contents():
        parts.append((x, len(doc.xref_stream_raw(x) or b"")))
    r = pg.rect
    return (pg.xref, pg.rotation, round(r.width, 2), round(r.height, 2),
            tuple(parts))


def _serve(conn):                                   # runs in the child
    import fitz
    docs = OrderedDict()          # path -> (doc, (mtime_ns, size))
    lists = OrderedDict()         # (path, stamp, page) -> display list

    def open_doc(path):
        st = os.stat(path)
        stamp = (st.st_mtime_ns, st.st_size)
        hit = docs.get(path)
        if hit is not None and hit[1] == stamp:
            docs.move_to_end(path)
            return hit[0], stamp
        if hit is not None:                    # saved since: open it again
            hit[0].close()
            for k in [k for k in lists if k[0] == path]:
                del lists[k]
        doc = fitz.open(path)
        docs[path] = (doc, stamp)
        while len(docs) > 4:
            _, (old, _) = docs.popitem(last=False)
            old.close()
        return doc, stamp

    inbox = deque()
    cancelled = set()

    def drain():
        """Read what has already arrived, so a cancel that came in behind
        a render is seen before that render starts."""
        while conn.poll():
            m = conn.recv()
            if m and m[0] == "cancel":
                cancelled.update(m[1])
                if len(cancelled) > 5000:      # ids already answered
                    cancelled.clear()
            else:
                inbox.append(m)

    while True:
        try:
            drain()
            msg = inbox.popleft() if inbox else conn.recv()
        except (EOFError, OSError):
            return
        if msg and msg[0] == "cancel":
            cancelled.update(msg[1])
            if len(cancelled) > 5000:          # ids already answered
                cancelled.clear()
            continue
        if msg and len(msg) > 1 and msg[1] in cancelled:
            cancelled.discard(msg[1])          # nobody wants it: skip it
            continue
        if not msg or msg[0] == "stop":
            return
        if msg[0] == "count":
            _, rid, path = msg
            try:
                with fitz.open(path) as d:
                    n = str(d.page_count)
            except Exception:                           # noqa: BLE001
                n = "?"
            try:
                conn.send(("count", rid, n))
            except Exception:                           # noqa: BLE001
                return
            continue
        if msg[0] == "segments":
            _, rid, path, pno, want = msg
            try:
                from array import array
                from app import snap
                doc, stamp = open_doc(path)
                sig = page_sig(doc, pno)
                if want is not None and tuple(want) != sig:
                    conn.send(("segs", rid, sig, 0, b""))
                    continue
                flat = array("d")
                n = 0
                for a, b in snap.page_segments(doc[pno]):
                    flat.extend((a[0], a[1], b[0], b[1]))
                    n += 1
                conn.send(("segs", rid, sig, n, flat.tobytes()))
            except Exception as e:                      # noqa: BLE001
                try:
                    conn.send(("err", rid, f"{type(e).__name__}: {e}"))
                except Exception:                       # noqa: BLE001
                    return
            continue
        if msg[0] != "render":
            continue
        _, rid, path, pno, zoom, clip, thin, want = msg
        try:
            doc, stamp = open_doc(path)
            sig = page_sig(doc, pno)
            if want is not None and tuple(want) != sig:
                conn.send(("img", rid, sig, 0, 0, 0, 0, 0, b""))
                continue
            key = (path, stamp, pno)
            dl = lists.get(key)
            if dl is None:
                dl = doc[pno].get_displaylist(annots=False)
                lists[key] = dl
                while len(lists) > 6:
                    lists.popitem(last=False)
            else:
                lists.move_to_end(key)
            fitz.TOOLS.set_graphics_min_line_width(1.0 if thin else 0.0)
            kw = {"matrix": fitz.Matrix(zoom, zoom), "alpha": False}
            if clip is not None:
                kw["clip"] = fitz.Rect(clip)
            pix = dl.get_pixmap(**kw)
            conn.send(("img", rid, sig, pix.x, pix.y, pix.width, pix.height,
                       pix.stride, bytes(pix.samples)))
        except Exception as e:                          # noqa: BLE001
            try:
                conn.send(("err", rid, f"{type(e).__name__}: {e}"))
            except Exception:                           # noqa: BLE001
                return
