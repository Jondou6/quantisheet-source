"""The "QuantiSheet" printer (0.12.24;
runs as you since 0.12.26): the parts that don't need Windows' print
spooler."""
import datetime
import os
import sys

import pytest


def test_file_names_from_print_jobs(tmp_path):
    from app import printhelper as ph
    when = datetime.datetime(2026, 10, 20, 8, 15, 30)
    assert ph.file_name("Bid Form.docx - Word", when) == \
        "Bid Form 2026-10-20 081530.pdf"
    assert ph.file_name('a/b:c*?"<>|.txt', when) == \
        "a_b_c______ 2026-10-20 081530.pdf"
    assert ph.file_name("", when) == "Printed 2026-10-20 081530.pdf"
    assert ph.file_name("x" * 300, when).startswith("x" * 80 + " ")
    (tmp_path / "A.pdf").write_bytes(b"1")
    (tmp_path / "A (2).pdf").write_bytes(b"1")
    assert ph.unique(str(tmp_path), "A.pdf").endswith("A (3).pdf")


def test_whose_job_is_printing():
    from app import printhelper as ph
    jobs = [(7, "amy", "Plans", 0x8, 2), (6, "bob", "Bid", 0x10, 1)]
    assert ph.pick_job(jobs) == ("bob", "Bid")         # the printing one
    assert ph.pick_job([(9, "cy", "X", 0, 3), (8, "di", "Y", 0, 1)]) == \
        ("di", "Y")                                     # else first in line
    assert ph.pick_job([]) == (None, None)
    assert ph.looks_like_pdf(b"\n%PDF-1.7\n...") and \
        not ph.looks_like_pdf(b"\x01\x00EMF")


def test_spool_port_is_a_file_in_programdata():
    """ProgramData\\QuantiSheet\\print\\spool\\job.pdf."""
    from app import printhelper as ph
    assert ph.PORT.endswith(os.path.join("print", "spool", "job.pdf"))
    assert os.path.join("QuantiSheet", "print", "spool") in ph.PORT
    assert ph.ports() == (ph.PORT,)


def test_printer_names():
    from app import printhelper as ph
    assert ph.PRINTER == "QuantiSheet"
    assert ph.RUN_NAME == "QuantiSheet Printer"
    assert os.path.join("QuantiSheet", "print", "spool") in ph.SPOOL_DIR
    assert ph.SUBFOLDER == os.path.join("QuantiSheet", "Printed")
    assert ph.active_printer() == "QuantiSheet"


def _ps_log(monkeypatch, answers=None):
    from app import printer_setup
    cmds = []

    def fake(cmd, check=False):
        cmds.append(cmd)
        for k, v in (answers or {}).items():
            if k in cmd:
                return 0, v
        return 0, ""
    monkeypatch.setattr(printer_setup, "_ps", fake)
    monkeypatch.setattr(printer_setup, "_run", lambda a, check=False: (1, ""))
    monkeypatch.setattr(printer_setup, "_set_run", lambda h, c: None)
    monkeypatch.setattr(printer_setup, "_get_run", lambda h: None)
    monkeypatch.setattr(printer_setup, "status", lambda: {})
    return cmds


def test_remove_takes_away_the_printer(monkeypatch):
    from app import printer_setup
    cmds = _ps_log(monkeypatch)
    monkeypatch.setattr(printer_setup.os.path, "isdir", lambda p: False)
    printer_setup.remove(log=lambda *a: None)
    gone = [c for c in cmds if c.startswith("Remove-Printer ")]
    assert gone == ["Remove-Printer -Name 'QuantiSheet' -ErrorAction "
                    "SilentlyContinue"]
    ports = [c for c in cmds if c.startswith("Remove-PrinterPort ")]
    assert len(ports) == 1 and "QuantiSheet" in ports[0]


def test_install_adds_the_quantisheet_printer(monkeypatch, tmp_path):
    from app import printer_setup, printhelper as ph
    monkeypatch.setattr(ph, "SPOOL_DIR", str(tmp_path / "spool"))
    cmds = _ps_log(monkeypatch, {"Get-PrinterDriver": "ok"})
    printer_setup.install(log=lambda *a: None)
    assert any("Add-Printer -Name 'QuantiSheet'" in c for c in cmds)
    assert not any("Rename-Printer" in c for c in cmds)


def test_setups_remove_the_printer_on_uninstall():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server = open(os.path.join(root, "installer", "quantisheet_server.iss"),
                  encoding="utf-8").read()
    assert 'Parameters: "printer --remove"' in server
    assert "printer --migrate" not in server


def test_collect_leaves_someone_elses_file_alone(tmp_path, monkeypatch):
    """The helper runs as one person: another person's job file is never
    read, moved or removed (their own helper collects it)."""
    from app import printhelper as ph
    port = tmp_path / "job.pdf"
    port.write_bytes(b"%PDF-1.7 fake")
    monkeypatch.setattr(ph, "PORT", str(port))
    monkeypatch.setattr(ph, "file_owner", lambda p: "mallory")
    opened = []
    monkeypatch.setattr(ph, "open_in_app", lambda p: opened.append(p))
    monkeypatch.setattr(ph, "documents", lambda: str(tmp_path / "docs"))
    assert ph.collect("Plans", user="amy") is None
    assert port.exists() and not opened                 # untouched
    monkeypatch.setattr(ph, "file_owner", lambda p: "amy")
    got = ph.collect("Plans.docx - Word", user="amy")
    assert got and os.path.basename(got).startswith("Plans ")
    assert open(got, "rb").read() == b"%PDF-1.7 fake"
    assert not port.exists() and opened == [got]
    port.write_bytes(b"not a pdf")                      # removed, not opened
    assert ph.collect("X", user="amy") is None and not port.exists()


def test_step_only_looks_at_my_jobs(tmp_path, monkeypatch):
    from app import printhelper as ph
    monkeypatch.setattr(ph, "PORT", str(tmp_path / "job.pdf"))
    q = [(5, "CORP\\bob", "Bob's", 0x10, 1), (6, "CORP\\Amy", "Mine", 0x10, 2),
         (7, "amy", "Next", 0, 3)]
    monkeypatch.setattr(ph, "jobs", lambda: list(q))
    paused = []
    monkeypatch.setattr(ph, "set_job", lambda j, c: paused.append((j, c))
                        or True)
    st = {"current": None, "paused": set()}
    ph.step(st, user="amy")
    assert st["current"] == (6, "Mine")                 # not bob's job
    assert paused == [(7, 1)]                           # my next job waits
    got = []
    monkeypatch.setattr(ph, "collect",
                        lambda d, u, port=None: got.append((d, u, port)))
    (tmp_path / "job.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(ph, "_stable", lambda p, wait=0: True)
    q[:] = [q[0], q[2]]                                 # mine has finished
    ph.step(st, user="amy")
    assert got == [("Mine", "amy", str(tmp_path / "job.pdf"))] and \
        (7, 2) in paused


def test_nothing_runs_as_system():
    """0.12.24-0.12.25's SYSTEM helper was taken for malware by Defender
    (Bearfoos.A!ml): the helper and setup must not come back to it."""
    import inspect
    from app import printer_setup, printhelper
    src = inspect.getsource(printhelper) + inspect.getsource(printer_setup)
    for bad in ("CreateProcessAsUser", "WTSQueryUserToken",
                "ImpersonateLoggedOnUser", "/RU", "ONSTART", "robocopy"):
        assert bad not in src, bad
    assert "print-helper" in printhelper.helper_command(
        "C:\\x\\QuantiSheet.exe")


def test_msi_and_server_setup_leave_the_printer_off():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    msi = open(os.path.join(root, "tools", "make_msi.py"),
               encoding="utf-8").read()
    assert '("PRINTER", "0")' in msi and "--all-users" in msi
    iss = open(os.path.join(root, "installer", "quantisheet_server.iss"),
               encoding="utf-8").read()
    line = next(ln for ln in iss.splitlines()
                if ln.startswith('Name: "printer"'))
    assert "unchecked" in line


def test_printer_commands_need_no_pdf_libraries(monkeypatch):
    """`printer --status` dispatches before the PDF commands (an IT script
    on a server shouldn't load the PDF engine to check a printer)."""
    from app import cli, printer_setup
    seen = {}
    monkeypatch.setattr(printer_setup, "status",
                        lambda: seen.setdefault("rows", {"printer": "x"}))
    assert cli.main(["printer", "--status"]) == 0
    assert seen


def test_single_instance_name_is_per_user_and_session(monkeypatch):
    from app import singleinstance
    monkeypatch.setenv("SESSIONNAME", "RDP-Tcp#3")
    n = singleinstance.name()
    assert n.startswith("QuantiSheet-") and " " not in n and "#" not in n


@pytest.mark.skipif(not sys.platform.startswith("win"),
                    reason="Windows print spooler")
def test_printer_status_runs_without_admin():
    from app import printer_setup
    rows = printer_setup.status()
    assert set(rows) >= {"printer", "driver", "helper (you)",
                         "helper (all users)", "helper log"}
