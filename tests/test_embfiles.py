"""Job data files must not trample each other (PyMuPDF 1.28's
embfile_del removes the wrong entry when there are several)."""
import fitz

from app import doccontrol, embfiles, qa


def _names(d):
    return {n: d.embfile_get(n) for n in d.embfile_names()}


def test_rewrite_and_delete_keep_the_others_intact():
    d = fitz.open()
    d.new_page()
    for n in ("quantisheet_a.json", "quantisheet_b.json", "quantisheet_c.json"):
        embfiles.put(d, n, n.encode())
    for i in range(3):
        embfiles.put(d, "quantisheet_b.json", b"B%d" % i)
        embfiles.put(d, "quantisheet_a.json", b"A%d" % i)
    assert _names(d) == {"quantisheet_a.json": b"A2", "quantisheet_b.json": b"B2",
                         "quantisheet_c.json": b"quantisheet_c.json"}
    assert embfiles.delete(d, "quantisheet_b.json")
    assert not embfiles.delete(d, "quantisheet_b.json")
    assert _names(d) == {"quantisheet_a.json": b"A2",
                         "quantisheet_c.json": b"quantisheet_c.json"}
    embfiles.put(d, "quantisheet_b.json", b"B again")
    d2 = fitz.open("pdf", d.tobytes(garbage=3, deflate=True))
    assert _names(d2) == {"quantisheet_a.json": b"A2",
                          "quantisheet_b.json": b"B again",
                          "quantisheet_c.json": b"quantisheet_c.json"}
    assert d2.embfile_info("quantisheet_a.json")["size"] == 2


def test_register_survives_punch_list_edits():
    d = fitz.open()
    p = d.new_page(width=2592, height=1728)
    p.insert_text((2360, 1512), "FLOOR PLAN", fontsize=22)
    p.insert_text((2380, 1680), "A-101", fontsize=44)
    doccontrol.scan_register(d)
    pid = qa.add_punch(d, "Patch", "Room 1")
    qa.pin(d, pid, 0, (100, 100))
    qa.set_status(d, pid, "ready")
    assert [r["number"] for r in doccontrol.register(d)] == ["A-101"]
    assert qa.get_punch(d, pid)["status"] == "ready"


# --- review of tonight's changes #8: never embfile_del with several files --
# _SimPdf models just the PyMuPDF calls embfiles uses (xref_get_key /
# xref_set_key paths, update_stream, embfile_*), with embfile_del doing what
# PyMuPDF 1.28's does wrong: the next file's data ends up under the deleted
# name's neighbour. Only real PyMuPDF can confirm the key/value text it
# returns matches; the real-PDF tests below cover that where it's installed.
import re  # noqa: E402

import pytest  # noqa: E402


class _SimPdf:
    def __init__(self):
        self.obj = {1: {"Type": ("name", "/Catalog")}}
        self.streams = {}
        self.del_calls = []

    def pdf_catalog(self):
        return 1

    def get_new_xref(self):
        x = max(self.obj) + 1
        self.obj[x] = {}
        return x

    def _walk(self, x, path, create=False):
        node = self.obj[x]
        keys = path.split("/")
        for k in keys[:-1]:
            v = node.get(k)
            if isinstance(v, tuple) and v[0] == "ref":
                v = self.obj[v[1]]
            if not isinstance(v, dict):
                if not create:
                    return None, keys[-1]
                v = node[k] = {}
            node = v
        return node, keys[-1]

    def xref_get_key(self, x, path):
        node, k = self._walk(x, path)
        v = None if node is None else node.get(k)
        if v is None:
            return "null", "null"
        if isinstance(v, dict):
            return "dict", "<<...>>"
        kind, val = v
        if kind == "ref":
            return "xref", f"{val} 0 R"
        return kind, val

    def xref_set_key(self, x, path, value):
        node, k = self._walk(x, path, create=True)
        if value == "null":
            node.pop(k, None)
        elif re.fullmatch(r"\d+ 0 R", value):
            node[k] = ("ref", int(value.split()[0]))
        elif value.startswith("["):
            node[k] = ("array", value)
        elif value.isdigit():
            node[k] = ("int", value)
        else:
            node[k] = ("string", value)

    def update_stream(self, x, data):
        if x not in self.streams:
            raise RuntimeError("object is no PDF dict")
        self.streams[x] = bytes(data)

    # -- the name tree, read the way MuPDF does (flat or /Kids) --
    def _root(self):
        t, v = self.xref_get_key(1, "Names/EmbeddedFiles")
        return None if t == "null" else (1, "Names/EmbeddedFiles/")

    def _leaves(self, x=None, prefix=None):
        if x is None:
            if self._root() is None:
                return []
            x, prefix = self._root()
        t, kids = self.xref_get_key(x, prefix + "Kids")
        if t == "array":
            out = []
            for m in re.finditer(r"(\d+) 0 R", kids):
                out += self._leaves(int(m.group(1)), "")
            return out
        t, names = self.xref_get_key(x, prefix + "Names")
        return embfiles._entries(names) if t == "array" else []

    def embfile_names(self):
        return [n for n, _v in self._leaves()]

    def embfile_get(self, name):
        for n, v in self._leaves():
            if n == name:
                x = embfiles._stream_xref(self, v)
                if x not in self.streams:
                    raise RuntimeError("object is not a stream")
                return self.streams[x]
        raise ValueError("no such file")

    def embfile_add(self, name, data, filename=None, desc=None):
        assert name not in self.embfile_names()
        root = self._root()
        assert root is None or self.xref_get_key(
            1, "Names/EmbeddedFiles/Kids")[0] == "null", "add on /Kids tree"
        x = self.get_new_xref()
        self.streams[x] = bytes(data)
        t, text = self.xref_get_key(1, "Names/EmbeddedFiles/Names")
        text = text if t == "array" else "[]"
        ent = f"({name})<</Type/Filespec/F({name})/UF({name})/EF<</F {x} 0 R>>>>"
        self.xref_set_key(1, "Names/EmbeddedFiles/Names", text[:-1] + ent + "]")

    def embfile_del(self, name):
        self.del_calls.append(name)
        if len(self.embfile_names()) > 1:
            raise AssertionError("embfile_del with several files swaps data")
        self.xref_set_key(1, "Names/EmbeddedFiles/Names", "[]")


def _sim(*names):
    d = _SimPdf()
    for n in names:
        embfiles.put(d, n, n.encode())
    return d


def _contents(d):
    return {n: d.embfile_get(n) for n in d.embfile_names()}


ABC = ("quantisheet_a.json", "quantisheet_b.json", "quantisheet_c.json")


def test_sim_baseline_rewrite_in_place():
    d = _sim(*ABC)
    embfiles.put(d, "quantisheet_b.json", b"B1")
    assert _contents(d) == {"quantisheet_a.json": b"quantisheet_a.json",
                            "quantisheet_b.json": b"B1",
                            "quantisheet_c.json": b"quantisheet_c.json"}
    assert d.del_calls == []


def test_sim_uf_only_inline_entry_is_rewritten_in_place():
    d = _sim(*ABC)
    t, text = d.xref_get_key(1, "Names/EmbeddedFiles/Names")
    x = embfiles._stream_xref(d, dict(embfiles._entries(text))[ABC[1]])
    d.xref_set_key(1, "Names/EmbeddedFiles/Names",
                   text.replace(f"/EF<</F {x} 0 R>>", f"/EF<</UF {x} 0 R>>"))
    embfiles.put(d, ABC[1], b"new B")
    assert d.streams[x] == b"new B"
    assert _contents(d)[ABC[0]] == ABC[0].encode()
    assert _contents(d)[ABC[2]] == ABC[2].encode()
    assert d.del_calls == []


def test_sim_uf_only_filespec_object_is_rewritten_in_place():
    d = _sim(*ABC)
    t, text = d.xref_get_key(1, "Names/EmbeddedFiles/Names")
    ents = embfiles._entries(text)
    x = embfiles._stream_xref(d, ents[1][1])
    fs = d.get_new_xref()
    d.obj[fs] = {"Type": ("name", "/Filespec"),
                 "UF": ("string", ABC[1]), "EF": {"UF": ("ref", x)}}
    ents[1] = (ABC[1], f"{fs} 0 R")
    d.xref_set_key(1, "Names/EmbeddedFiles/Names", embfiles._array(ents))
    embfiles.put(d, ABC[1], b"new B")
    assert d.streams[x] == b"new B"
    assert len(_contents(d)) == 3 and d.del_calls == []


def test_sim_entry_without_a_stream_is_replaced_not_embfile_del():
    d = _sim(*ABC)
    t, text = d.xref_get_key(1, "Names/EmbeddedFiles/Names")
    ents = embfiles._entries(text)
    ents[1] = (ABC[1], "<</Type/Filespec/F(quantisheet_b.json)>>")   # no /EF
    d.xref_set_key(1, "Names/EmbeddedFiles/Names", embfiles._array(ents))
    embfiles.put(d, ABC[1], b"fresh B")
    assert _contents(d) == {ABC[0]: ABC[0].encode(), ABC[1]: b"fresh B",
                            ABC[2]: ABC[2].encode()}
    assert d.embfile_names().count(ABC[1]) == 1
    assert d.del_calls == []


def test_sim_damaged_stream_is_replaced_not_embfile_del():
    d = _sim(*ABC)
    t, text = d.xref_get_key(1, "Names/EmbeddedFiles/Names")
    x = embfiles._stream_xref(d, dict(embfiles._entries(text))[ABC[0]])
    del d.streams[x]                              # update_stream fails
    embfiles.put(d, ABC[0], b"fresh A")
    assert _contents(d) == {ABC[0]: b"fresh A", ABC[1]: ABC[1].encode(),
                            ABC[2]: ABC[2].encode()}
    assert d.del_calls == []


def _split_into_kids(d):
    t, text = d.xref_get_key(1, "Names/EmbeddedFiles/Names")
    ents = embfiles._entries(text)
    k1, k2 = d.get_new_xref(), d.get_new_xref()
    d.obj[k1] = {"Names": ("array", embfiles._array(ents[:1]))}
    d.obj[k2] = {"Names": ("array", embfiles._array(ents[1:]))}
    d.xref_set_key(1, "Names/EmbeddedFiles/Names", "null")
    d.xref_set_key(1, "Names/EmbeddedFiles/Kids", f"[{k1} 0 R {k2} 0 R]")
    assert embfiles._names_array(d) is None


def test_sim_kids_tree_is_flattened_then_edited():
    d = _sim(*ABC)
    _split_into_kids(d)
    embfiles.put(d, ABC[2], b"C1")
    assert embfiles._names_array(d) is not None          # flat now
    assert _contents(d) == {ABC[0]: ABC[0].encode(), ABC[1]: ABC[1].encode(),
                            ABC[2]: b"C1"}
    d = _sim(*ABC)
    _split_into_kids(d)
    assert embfiles.delete(d, ABC[0])
    assert _contents(d) == {ABC[1]: ABC[1].encode(), ABC[2]: ABC[2].encode()}
    embfiles.put(d, "quantisheet_new.json", b"N")
    assert _contents(d)["quantisheet_new.json"] == b"N"
    assert d.del_calls == []


def test_sim_unreadable_list_refuses_instead_of_swapping():
    d = _sim(*ABC)
    _split_into_kids(d)
    kids = d.xref_get_key(1, "Names/EmbeddedFiles/Kids")[1]
    k1 = int(re.findall(r"(\d+) 0 R", kids)[0])
    d.obj[k1] = {}                       # a node with neither Kids nor Names
    with pytest.raises(RuntimeError):
        embfiles.put(d, ABC[2], b"C1")
    with pytest.raises(RuntimeError):
        embfiles.delete(d, ABC[2])
    assert d.del_calls == []
    assert _contents(d) == {ABC[1]: ABC[1].encode(), ABC[2]: ABC[2].encode()}


def test_sim_single_file_may_still_use_embfile_del():
    d = _sim(ABC[0])
    d.xref_set_key(1, "Names/EmbeddedFiles/Names", "[garbage")
    d.embfile_names = lambda: [ABC[0]]                  # MuPDF can read it
    embfiles.delete(d, ABC[0])
    assert d.del_calls == [ABC[0]]


def test_entry_found_by_its_uf_file_name():
    d = _SimPdf()
    ents = [("quantisheet_a.json", "<</Type/Filespec/UF(quantisheet_a.json)>>"),
            ("odd key", "<</Type/Filespec/UF<FEFF00620062>/F(x)>>")]
    assert embfiles._index(d, ents, "quantisheet_a.json") == 0
    assert embfiles._index(d, ents, "bb") == 1
    assert embfiles._index(d, ents, "x") == 1
    assert embfiles._index(d, ents, "nope") is None


def _real_pdf_with(names):
    d = fitz.open()
    d.new_page()
    for n in names:
        embfiles.put(d, n, n.encode())
    return d


def test_real_uf_only_entry_is_rewritten_in_place():
    """Same as the simulated test, on a real PyMuPDF document."""
    d = _real_pdf_with(ABC)
    loc = embfiles._names_array(d)
    _, text = d.xref_get_key(*loc)
    value = dict(embfiles._entries(text))[ABC[1]]
    x = embfiles._stream_xref(d, value)
    m = re.match(r"(\d+)\s+\d+\s+R", value)
    if m:
        fs = int(m.group(1))
        d.xref_set_key(fs, "EF/UF", f"{x} 0 R")
        d.xref_set_key(fs, "EF/F", "null")
    else:
        d.xref_set_key(loc[0], loc[1], re.sub(
            r"(/EF\s*<<[^>]*?)/F(\s+%d\s+0\s+R)" % x, r"\1/UF\2", text))
    assert embfiles._stream_xref(d, dict(embfiles._entries(
        d.xref_get_key(*loc)[1]))[ABC[1]]) == x
    embfiles.put(d, ABC[1], b"new B")
    assert _names(d)[ABC[0]] == ABC[0].encode()
    assert _names(d)[ABC[2]] == ABC[2].encode()
    assert d.xref_stream(x) == b"new B"


def test_real_kids_tree_is_flattened():
    d = _real_pdf_with(ABC)
    loc = embfiles._names_array(d)
    _, text = d.xref_get_key(*loc)
    ents = embfiles._entries(text)
    k1, k2 = d.get_new_xref(), d.get_new_xref()
    d.update_object(k1, "<</Names %s/Limits[(%s)(%s)]>>" % (
        embfiles._array(ents[:1]), ents[0][0], ents[0][0]))
    d.update_object(k2, "<</Names %s/Limits[(%s)(%s)]>>" % (
        embfiles._array(ents[1:]), ents[1][0], ents[-1][0]))
    d.xref_set_key(loc[0], loc[1], "null")
    d.xref_set_key(loc[0], loc[1][:-len("Names")] + "Kids",
                   f"[{k1} 0 R {k2} 0 R]")
    assert embfiles._names_array(d) is None
    # PyMuPDF itself lists only a flat array; put() flattens first
    embfiles.put(d, ABC[2], b"C1")
    assert sorted(d.embfile_names()) == sorted(ABC)
    assert embfiles.delete(d, ABC[0])
    d2 = fitz.open("pdf", d.tobytes(garbage=3))
    assert _names(d2) == {ABC[1]: ABC[1].encode(), ABC[2]: b"C1"}
