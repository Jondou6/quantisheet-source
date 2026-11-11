"""Safe writes of embedded files (QuantiSheet's job data).

PyMuPDF 1.28's embfile_del() removes the wrong half of the name tree when
a PDF has several embedded files: the deleted file's name stays attached
to the next file's contents, so rewriting one job file (delete + add)
silently swapped another file's data (e.g. the drawing register came back
holding the punch list). embfile_upd() crashes when given bytes.

put() rewrites an existing file's stream in place and delete() edits the
name array directly; neither goes through those calls. A name tree split
into /Kids (made by other programs) is first rewritten as one flat array.
embfile_del is used only when the PDF has a single embedded file (nothing
to swap with); with several and an unreadable list, put/delete raise.
"""
import logging
import re

log = logging.getLogger(__name__)


def _skip_ws(s, i):
    while i < len(s) and s[i] in " \t\r\n\f\x00":
        i += 1
    return i


def _literal(s, i):
    """s[i] == '(' -> (decoded text, end index)."""
    depth, out, j = 0, [], i
    esc = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}
    while j < len(s):
        c = s[j]
        if c == "\\" and j + 1 < len(s):
            n = s[j + 1]
            if n in esc:
                out.append(esc[n])
                j += 2
                continue
            m = re.match(r"[0-7]{1,3}", s[j + 1:])
            if m:
                out.append(chr(int(m.group(0), 8)))
                j += 1 + len(m.group(0))
                continue
            out.append(n)
            j += 2
            continue
        if c == "(":
            depth += 1
            if depth > 1:
                out.append(c)
        elif c == ")":
            depth -= 1
            if depth == 0:
                return "".join(out), j + 1
            out.append(c)
        else:
            out.append(c)
        j += 1
    raise ValueError("unterminated string")


def _name_token(s, i):
    if s[i] == "(":
        return _literal(s, i)
    if s[i] == "<" and not s.startswith("<<", i):
        j = s.index(">", i)
        raw = bytes.fromhex(re.sub(r"\s", "", s[i + 1:j]))
        if raw.startswith(b"\xfe\xff"):
            return raw[2:].decode("utf-16-be", "replace"), j + 1
        return raw.decode("latin-1"), j + 1
    raise ValueError(f"unexpected {s[i]!r}")


def _value_token(s, i):
    """A dictionary << ... >> or an indirect reference 'n g R'."""
    if s.startswith("<<", i):
        depth, j = 0, i
        while j < len(s):
            if s.startswith("<<", j):
                depth += 1
                j += 2
                continue
            if s.startswith(">>", j):
                depth -= 1
                j += 2
                if depth == 0:
                    return s[i:j], j
                continue
            if s[j] == "(":
                _, j = _literal(s, j)
                continue
            j += 1
        raise ValueError("unterminated dictionary")
    m = re.compile(r"\d+\s+\d+\s+R").match(s, i)
    if m:
        return m.group(0), m.end()
    raise ValueError(f"unexpected value at {i}")


def _entries(text):
    """'[(a)<<...>>(b) 12 0 R]' -> [(name, value text)]."""
    s = text.strip()
    if not (s.startswith("[") and s.endswith("]")):
        raise ValueError("not an array")
    s = s[1:-1]
    out, i = [], 0
    while True:
        i = _skip_ws(s, i)
        if i >= len(s):
            return out
        name, i = _name_token(s, i)
        i = _skip_ws(s, i)
        value, i = _value_token(s, i)
        out.append((name, value))


def _ef_dict(doc, base, prefix):
    """(xref, key prefix) of the EmbeddedFiles name tree root, or None."""
    for k in ("Names", "EmbeddedFiles"):
        t, v = doc.xref_get_key(base, prefix + k)
        if t == "xref":
            base, prefix = int(v.split()[0]), ""
        elif t == "dict":
            prefix = prefix + k + "/"
        else:
            return None
    return base, prefix


def _names_array(doc):
    """(xref, key path) of the EmbeddedFiles /Names array, or None when
    there is none, or the tree uses /Kids, or it's stored oddly."""
    root = _ef_dict(doc, doc.pdf_catalog(), "")
    if root is None:
        return None
    base, prefix = root
    t, _ = doc.xref_get_key(base, prefix + "Kids")
    if t != "null":
        return None
    t, _ = doc.xref_get_key(base, prefix + "Names")
    return (base, prefix + "Names") if t == "array" else None


_REF = re.compile(r"(\d+)\s+\d+\s+R")


def _flatten(doc):
    """A name tree split into /Kids (other programs make these) rewritten
    as one flat /Names array on the root, so put() and delete() can edit
    it directly instead of calling embfile_del. Returns the new
    _names_array() location, or None when the tree can't be read (then
    nothing is changed)."""
    root = _ef_dict(doc, doc.pdf_catalog(), "")
    if root is None:
        return None
    base, prefix = root
    t, kids = doc.xref_get_key(base, prefix + "Kids")
    if t != "array":
        return None
    flat, seen = [], set()

    def walk(text, depth):
        if depth > 32:
            raise ValueError("name tree too deep")
        for m in _REF.finditer(text):
            x = int(m.group(1))
            if x in seen:
                raise ValueError("name tree loops")
            seen.add(x)
            tk, sub = doc.xref_get_key(x, "Kids")
            if tk == "array":
                walk(sub, depth + 1)
                continue
            tn, names = doc.xref_get_key(x, "Names")
            if tn != "array":
                raise ValueError(f"name tree node {x} has no /Names")
            flat.extend(_entries(names))
    try:
        walk(kids, 0)
    except Exception:
        log.warning("could not read the embedded files tree", exc_info=True)
        return None
    # leaves are in key order, so concatenating them keeps the array sorted
    doc.xref_set_key(base, prefix + "Names", _array(flat))
    doc.xref_set_key(base, prefix + "Kids", "null")
    doc.xref_set_key(base, prefix + "Limits", "null")
    return _names_array(doc)


# the file's stream: /EF << /F n 0 R >>, or only /UF (some programs)
_EF_INLINE = [re.compile(r"/EF\s*<<[^>]*?/%s\s+(\d+)\s+\d+\s+R" % k)
              for k in ("F", "UF")]


def _stream_xref(doc, value):
    for rx in _EF_INLINE:
        m = rx.search(value)
        if m:
            return int(m.group(1))
    m = re.match(r"(\d+)\s+\d+\s+R", value)
    if m:
        for k in ("EF/F", "EF/UF"):
            t, v = doc.xref_get_key(int(m.group(1)), k)
            if t == "xref":
                return int(v.split()[0])
    return None


def _filenames(doc, value):
    """The filespec's /UF and /F file names (for matching an entry whose
    tree key is spelled differently from embfile_names())."""
    out = []
    m = re.match(r"(\d+)\s+\d+\s+R", value)
    if m:
        for k in ("UF", "F"):
            t, v = doc.xref_get_key(int(m.group(1)), k)
            if t == "string":
                out.append(v)
        return out
    for k in ("UF", "F"):
        for mm in re.finditer(r"/%s\s*(?=[(<][^<])" % k, value):
            try:
                out.append(_name_token(value, mm.end())[0])
            except (ValueError, IndexError):
                pass
    return out


def _find(doc, name):
    loc = _names_array(doc)
    if loc is None:
        loc = _flatten(doc)
    if loc is None:
        return None, None
    t, text = doc.xref_get_key(*loc)
    try:
        entries = _entries(text)
    except ValueError:
        log.warning("could not read the embedded files list", exc_info=True)
        return None, None
    return loc, entries


def _index(doc, entries, name):
    """Index of `name` in entries: by tree key, else by a unique /UF or
    /F file name; None when not found."""
    for i, (n, _v) in enumerate(entries):
        if n == name:
            return i
    hits = [i for i, (_n, v) in enumerate(entries)
            if name in _filenames(doc, v)]
    return hits[0] if len(hits) == 1 else None


def _unsafe_del(doc, name, what):
    """embfile_del is only safe with a single embedded file (the swap bug
    needs another file to swap with); otherwise refuse."""
    if len(doc.embfile_names()) <= 1:
        doc.embfile_del(name)
        return
    raise RuntimeError(f"can't safely {what} embedded file {name!r}: the "
                       "PDF's embedded files list can't be read")


def _array(entries):
    def lit(s):
        if all(ord(c) < 128 for c in s):
            return "(" + s.replace("\\", "\\\\").replace("(", "\\(") \
                .replace(")", "\\)") + ")"
        return "<FEFF" + s.encode("utf-16-be").hex().upper() + ">"
    return "[" + "".join(lit(n) + v for n, v in entries) + "]"


def put(doc, name, data, desc="QuantiSheet job data"):
    """Create or replace embedded file `name` without disturbing others,
    then read it back: when it doesn't come back as written (PyMuPDF 2.0
    was seen leaving a file object that is not a stream), the entry is
    dropped from the name array and the file added afresh."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    data = bytes(data)
    _put(doc, name, data, desc)
    if _readback(doc, name) == data:
        return
    log.warning("embedded file %s did not read back after writing; "
                "adding it afresh", name)
    try:
        _readd(doc, name, data, desc)
    except Exception:                                # noqa: BLE001
        log.error("could not re-add embedded file %s", name, exc_info=True)
        return
    if _readback(doc, name) != data:
        log.error("embedded file %s still does not read back", name)


def _readback(doc, name):
    try:
        return bytes(get(doc, name))
    except Exception:                                # noqa: BLE001
        log.debug("read back of %s failed", name, exc_info=True)
        return None


def _readd(doc, name, data, desc):
    """Drop `name` from the name array (never embfile_del while other
    files exist) and embed it again."""
    if name in names(doc):
        loc, entries = _find(doc, name)
        i = _index(doc, entries, name) if loc is not None else None
        if i is None:
            _unsafe_del(doc, name, "re-add")
        else:
            del entries[i]
            doc.xref_set_key(loc[0], loc[1], _array(entries))
    doc.embfile_add(name, data, filename=name, desc=desc)


def _put(doc, name, data, desc):
    """Create or replace embedded file `name` without disturbing others.
    An entry whose file object isn't a stream (a damaged PDF; PyMuPDF says
    'object is no PDF dict'), or whose stream can't be found, is removed
    from the name array and the file is added afresh. embfile_del is never
    used while other embedded files exist (review of tonight's changes #8)."""
    _flat_first(doc)
    if name in doc.embfile_names():
        loc, entries = _find(doc, name)
        if loc is None:
            _unsafe_del(doc, name, "rewrite")
            doc.embfile_add(name, data, filename=name, desc=desc)
            return
        i = _index(doc, entries, name)
        x = _stream_xref(doc, entries[i][1]) if i is not None else None
        if x and _is_stream(doc, x) is False:
            # PyMuPDF 2.0: update_stream / embfile_get on a non-stream
            # object raise "object is not a stream"; rewrite the entry
            log.warning("embedded file %s: object %d is not a stream; "
                        "rewriting it", name, x)
            del entries[i]
            doc.xref_set_key(loc[0], loc[1], _array(entries))
            doc.embfile_add(name, data, filename=name, desc=desc)
            return
        if x:
            try:
                _write_stream(doc, x, data)
            except Exception:
                log.warning("embedded file %s is damaged; rewriting it",
                            name, exc_info=True)
            else:
                doc.xref_set_key(x, "DL", str(len(data)))
                doc.xref_set_key(x, "Params/Size", str(len(data)))
                fixed = _add_f(doc, entries[i][1], x)
                if fixed is not None:
                    entries[i] = (entries[i][0], fixed)
                    doc.xref_set_key(loc[0], loc[1], _array(entries))
                return
        elif i is None:
            _unsafe_del(doc, name, "rewrite")
            doc.embfile_add(name, data, filename=name, desc=desc)
            return
        # damaged or stream not found: drop the entry from the array
        del entries[i]
        doc.xref_set_key(loc[0], loc[1], _array(entries))
    doc.embfile_add(name, data, filename=name, desc=desc)


FAST_ABOVE = 128 * 1024        # bytes: bigger job data is compressed fast


def _write_stream(doc, x, data):
    """Replace stream `x` with `data`, compressed. PDF code compresses at
    its slowest setting: 100 ms for every save of a half-megabyte billing
    record, on every entry (torture test, Nov 10). Big data is compressed
    here at a fast setting and stored already compressed; put() reads it
    back and compares, so a mistake can't pass silently."""
    if len(data) < FAST_ABOVE:
        doc.update_stream(x, data)
        return
    import zlib
    doc.update_stream(x, zlib.compress(data, 1), compress=False)
    doc.xref_set_key(x, "Filter", "/FlateDecode")
    if doc.xref_get_key(x, "DecodeParms")[0] != "null":
        doc.xref_set_key(x, "DecodeParms", "null")


def _flat_first(doc):
    """PyMuPDF lists only a flat /Names array: a tree split into /Kids
    (other programs write these) is flattened first so its files are seen
    and edited in place."""
    try:
        if _names_array(doc) is None:
            _flatten(doc)
    except Exception:                                # noqa: BLE001
        log.warning("could not flatten the embedded files tree",
                    exc_info=True)


def _add_f(doc, value, x):
    """An entry naming its stream only by /EF /UF: add /EF /F too, so
    PyMuPDF (which reads /F) can open it."""
    m = re.match(r"(\d+)\s+\d+\s+R", value)
    if not m:
        # inline filespec: return the value with /F added beside /UF
        if _EF_INLINE[0].search(value) or not _EF_INLINE[1].search(value):
            return None
        return re.sub(r"/EF\s*<<", "/EF<</F %d 0 R" % x, value, count=1)
    fs = int(m.group(1))
    try:
        if doc.xref_get_key(fs, "EF/F")[0] != "xref":
            doc.xref_set_key(fs, "EF/F", f"{x} 0 R")
    except Exception:                                # noqa: BLE001
        log.warning("could not add /EF /F", exc_info=True)


def delete(doc, name):
    """Remove embedded file `name`, leaving the others intact."""
    _flat_first(doc)
    if name not in doc.embfile_names():
        return False
    loc, entries = _find(doc, name)
    i = _index(doc, entries, name) if loc is not None else None
    if i is None:
        _unsafe_del(doc, name, "delete")
        return True
    del entries[i]
    doc.xref_set_key(loc[0], loc[1], _array(entries))
    return True


# ---- reading, robust on PyMuPDF 1.28 and 2.x ------------------------------

def _is_stream(doc, x):
    """True / False, or None when it can't be told (no xref_is_stream)."""
    f = getattr(doc, "xref_is_stream", None)
    if f is None:
        return None
    try:
        return bool(f(x))
    except Exception:                                # noqa: BLE001
        return False


def _stream_candidates(doc, value):
    """Every /EF /F and /EF /UF stream xref the filespec names."""
    out = []
    for rx in _EF_INLINE:
        m = rx.search(value)
        if m:
            out.append(int(m.group(1)))
    m = re.match(r"(\d+)\s+\d+\s+R", value)
    if m:
        for k in ("EF/F", "EF/UF"):
            try:
                t, v = doc.xref_get_key(int(m.group(1)), k)
            except Exception:                        # noqa: BLE001
                continue
            if t == "xref":
                out.append(int(v.split()[0]))
    seen = []
    for x in out:
        if x not in seen:
            seen.append(x)
    return seen


def names(doc):
    """doc.embfile_names(), or the names in the flat name array when
    PyMuPDF can't list them."""
    try:
        return list(doc.embfile_names())
    except Exception:                                # noqa: BLE001
        log.warning("embfile_names failed; reading the name array",
                    exc_info=True)
    try:
        loc = _names_array(doc)
        if loc is None:
            return []
        return [n for n, _v in _entries(doc.xref_get_key(*loc)[1])]
    except Exception:                                # noqa: BLE001
        log.warning("could not read the embedded files list", exc_info=True)
        return []


def _raw_get(doc, name):
    """The file's bytes read straight from its stream object (only an
    object that really is a stream), or None."""
    if not hasattr(doc, "xref_stream"):
        return None
    try:
        loc = _names_array(doc)
        if loc is None:
            return None
        entries = _entries(doc.xref_get_key(*loc)[1])
        i = _index(doc, entries, name)
        if i is None:
            return None
        for x in _stream_candidates(doc, entries[i][1]):
            if _is_stream(doc, x):
                data = doc.xref_stream(x)
                if data is not None:
                    return bytes(data)
    except Exception:                                # noqa: BLE001
        log.debug("direct read of %s failed", name, exc_info=True)
    return None


def get(doc, name):
    """Embedded file `name`'s bytes: doc.embfile_get(), falling back to
    reading its stream object directly (checked with xref_is_stream
    first). Raises what embfile_get raised when neither works."""
    try:
        return doc.embfile_get(name)
    except Exception as ex:                          # noqa: BLE001
        err = ex
    data = _raw_get(doc, name)
    if data is None:
        raise err
    log.warning("embedded file %s read from its stream directly "
                "(embfile_get: %s)", name, err)
    return data


def snapshot(doc, prefix="quantisheet_"):
    """{name: bytes} of QuantiSheet's job data files, for checking a save
    (an encrypted file is not checked: {})."""
    try:
        if doc.needs_pass or doc.is_encrypted:
            return {}
    except Exception:                                # noqa: BLE001
        return {}
    out = {}
    for n in names(doc):
        if n.startswith(prefix):
            try:
                out[n] = bytes(get(doc, n))
            except Exception:                        # noqa: BLE001
                log.debug("not checked: %s", n, exc_info=True)
    return out


def saved_mismatches(path, snap):
    """Names in `snap` that the PDF saved at `path` lacks or holds
    different data for (opened afresh, so it is what is on disk)."""
    if not snap:
        return []
    import fitz
    try:
        d = fitz.open(path)
    except Exception:                                # noqa: BLE001
        log.warning("could not reopen %s to check it", path, exc_info=True)
        return sorted(snap)
    try:
        if d.needs_pass:
            return []
        have = set(names(d))
        bad = []
        for n, data in snap.items():
            try:
                ok = n in have and bytes(get(d, n)) == data
            except Exception:                        # noqa: BLE001
                ok = False
            if not ok:
                bad.append(n)
        return sorted(bad)
    finally:
        d.close()
