""""Open with" for PDF files (Venice M11): the standalone setup, the server
setup and the MSI each register their own ProgID, so uninstalling one
edition leaves the other's Open-with entry working."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_msi  # noqa: E402

CLASSES = "software\\classes\\"
LIST = CLASSES + ".pdf\\openwithprogids"
APP_KEY = CLASSES + "applications\\quantisheet.exe"


def iss_registry(name):
    """[Registry] entries of an .iss file as {param: value} dicts."""
    text = open(os.path.join(ROOT, "installer", name),
                encoding="utf-8").read()
    out, section = [], ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("["):
            section = s.lower()
            continue
        if section != "[registry]" or not s or s.startswith(";"):
            continue
        d = {}
        for m in re.finditer(r'(\w+):\s*("(?:[^"]|"")*"|[^;]*)', s):
            v = m.group(2).strip()
            if v.startswith('"'):
                v = v[1:-1].replace('""', '"')
            d[m.group(1).lower()] = v
        out.append(d)
    return out


def _cleanup(r):
    """An entry that only removes what an earlier version registered."""
    flags = r.get("flags", "").split()
    return "deletekey" in flags or "deletevalue" in flags


TOOLSET_KEYS = (CLASSES + ".qstools", CLASSES + "quantisheet.qstools")


def _toolset(r):
    """A key for the program's own tool set files (.qstools, Nov 2)."""
    k = r.get("subkey", "").lower()
    return any(k == t or k.startswith(t + "\\") for t in TOOLSET_KEYS)


def _verb(r):
    """A right-click action (Nov 3, shellverbs task): its own key."""
    return "tasks: shellverbs" in r.get("_line", "").lower() or \
        r.get("tasks", "").lower() == "shellverbs"


def test_right_click_actions_only_remove_their_own_keys():
    verbs = [r for r in iss_registry("quantisheet.iss") if _verb(r)]
    assert verbs
    for r in verbs:
        key = r["subkey"]
        own = [p for p in key.split("\\") if p.startswith("QuantiSheet.")]
        assert own, key                      # every key is a QuantiSheet.* verb
        if "uninsdeletekey" in r.get("flags", "").lower():
            assert key.split("\\")[-1].startswith("QuantiSheet."), key


def iss_openwith(name):
    """(progids, entries) for the .iss file's Open-with keys (not the
    clean-up of an earlier version's entries, nor the tool set file
    type)."""
    regs = [r for r in iss_registry(name)
            if r.get("subkey", "").lower().startswith(CLASSES)
            and not _cleanup(r) and not _toolset(r) and not _verb(r)]
    progs = {r["valuename"] for r in regs
             if r["subkey"].lower() == LIST}
    return progs, regs


def msi_openwith():
    rows = make_msi.openwith_rows(f"[INSTALLDIR]{make_msi.EXE}")
    progs = {r[3] for r in rows if r[2].lower() == LIST}
    return progs, rows


def test_each_edition_has_its_own_progid():
    solo, _ = iss_openwith("quantisheet.iss")
    server, _ = iss_openwith("quantisheet_server.iss")
    msi, _ = msi_openwith()
    assert solo == {"QuantiSheet.pdf"}
    assert server == {"QuantiSheet.Server.pdf"} == msi
    assert not solo & server
    assert make_msi.PROGID in msi


def test_progid_keys_open_the_program():
    for name in ("quantisheet.iss", "quantisheet_server.iss"):
        (prog,), regs = iss_openwith(name)
        keys = {r["subkey"].lower(): r for r in regs}
        top = keys[(CLASSES + prog).lower()]
        assert "uninsdeletekey" in top.get("flags", "")
        cmd = keys[(CLASSES + prog + "\\shell\\open\\command").lower()]
        assert cmd["valuedata"] == '"{app}\\QuantiSheet.exe" "%1"'
    (prog,), rows = msi_openwith()
    keys = {r[2].lower(): r for r in rows}
    assert keys[(CLASSES + prog + "\\shell\\open\\command").lower()][4] \
        == '"[INSTALLDIR]QuantiSheet.exe" "%1"'


def test_uninstall_only_removes_its_own_keys():
    """Every key or value an edition deletes on uninstall is its own: its
    ProgID's key, its own OpenWithProgids value - and only the standalone
    setup owns Applications\\QuantiSheet.exe."""
    for name, owns_app in (("quantisheet.iss", True),
                           ("quantisheet_server.iss", False)):
        (prog,), regs = iss_openwith(name)
        mine = (CLASSES + prog).lower()
        for r in regs:
            key, flags = r["subkey"].lower(), r.get("flags", "")
            if key == APP_KEY + "\\shell\\open\\command":
                assert owns_app, f"{name} writes {r['subkey']}"
                continue
            if key == LIST:
                assert r["valuename"] == prog
                assert "uninsdeletevalue" in flags
                assert "uninsdeletekey" not in flags
                continue
            assert key == mine or key.startswith(mine + "\\"), \
                f"{name}: {r['subkey']} is not under {prog}"
    _, rows = msi_openwith()
    for r in rows:
        key = r[2].lower()
        assert not key.startswith(APP_KEY)
        assert key == LIST or key.startswith(
            (CLASSES + make_msi.PROGID).lower())


def test_msi_component_keypath_is_an_openwith_row():
    rows = make_msi.openwith_rows("X")
    assert "OwProg" in {r[0] for r in rows}
    assert {r[5] for r in rows} == {"OpenWith"}


def test_upgrade_removes_only_the_earlier_open_with_entry():
    """The clean-up lines of the standalone setup remove the "Open with"
    entry 0.13.14 and earlier registered - that ProgID and nothing else."""
    regs = [r for r in iss_registry("quantisheet.iss") if _cleanup(r)]
    assert len(regs) == 2
    assert {r["subkey"].lower() for r in regs} == {
        CLASSES + "pdfstudio.pdf", LIST}
    assert [r["valuename"] for r in regs if r["subkey"].lower() == LIST] \
        == ["PDFStudio.pdf"]


def test_tool_set_files_open_in_quantisheet():
    """Double-clicking a .qstools file (Tool Chest > Save Sets as a File)
    opens QuantiSheet, which adds the sets; uninstall removes the program's
    own file type."""
    regs = [r for r in iss_registry("quantisheet.iss") if _toolset(r)]
    keys = {r["subkey"].lower(): r for r in regs}
    assert keys[CLASSES + ".qstools"]["valuedata"] == "QuantiSheet.qstools"
    assert "uninsdeletevalue" in keys[CLASSES + ".qstools"]["flags"]
    assert "uninsdeletekey" in keys[CLASSES + "quantisheet.qstools"]["flags"]
    cmd = keys[CLASSES + "quantisheet.qstools\\shell\\open\\command"]
    assert cmd["valuedata"] == '"{app}\\QuantiSheet.exe" "%1"'
    import build_msix
    src = open(build_msix.__file__, encoding="utf-8").read()
    assert '<uap:FileType>.qstools</uap:FileType>' in src
