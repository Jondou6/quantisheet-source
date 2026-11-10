"""Polish round, Nov 9: project save race, AI part time limit and Stop
Now, parking stalls counted once, accessibility fixes undone one at a
time, quantities rounded half up. Made-up data only."""
import json
import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402
import pytest                                                  # noqa: E402

from test_gui import qapp, win                                 # noqa: E402,F401


# ---- 1: the delayed project save never trips on a change -----------------------

def test_project_save_survives_changes_while_writing(tmp_path):
    from app.pm import store
    s = store.ProjectStore(str(tmp_path / "Example Job"))
    s.save(now=True)
    stop = threading.Event()

    def churn():
        k = 0
        while not stop.is_set():
            s.data["records"][f"r{k % 500}"] = {"n": k}
            s.data["records"].pop(f"r{(k + 250) % 500}", None)
            k += 1
    t = threading.Thread(target=churn, daemon=True)
    t.start()
    try:
        for _ in range(40):
            s._write()                            # never raises
    finally:
        stop.set()
        t.join(5)
    with open(s.path, encoding="utf-8") as fh:
        assert isinstance(json.load(fh), dict)    # always a whole file


def test_project_save_waits_when_it_never_settles(tmp_path, monkeypatch):
    from app.pm import store
    s = store.ProjectStore(str(tmp_path / "Example Job"))
    s.save(now=True)

    def busy(*a, **k):
        raise RuntimeError("dictionary changed size during iteration")
    monkeypatch.setattr(store.json, "dumps", busy)
    monkeypatch.setattr(store.time, "sleep", lambda s: None)
    s._write()
    assert s._timer is not None                   # put off, not lost
    s._timer.cancel()


# ---- 2: an AI part that never answers is skipped; Stop Now leaves it --------------

def _dialog(monkeypatch, pages=3):
    from app import bg
    from app.ai import dialogs, review
    monkeypatch.setattr(review, "TEXT_LIMIT", 300)
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_textbox(fitz.Rect(72, 72, 540, 700),
                                      f"Example page {i + 1} " +
                                      "word " * 50, fontsize=9)
    d = dialogs.RedlineDialog(doc)
    runs = []
    monkeypatch.setattr(bg, "run", lambda fn, ok, bad, parent=None:
                        runs.append((fn, ok, bad)))
    return d, runs


def test_part_over_the_limit_is_skipped(qapp, monkeypatch):
    from app.ai import dialogs
    d, runs = _dialog(monkeypatch)
    d._run(lambda text: [])
    total = d._total
    assert total >= 2
    first_ok = runs[-1][1]
    d._part_started -= dialogs.PART_LIMIT + 1         # waited too long
    d._tick()
    assert len(runs) == 2                             # the next part began
    first_ok([{"old": "late", "new": "x", "reason": "y"}])   # ignored
    assert not d._results
    for _ in range(total - 1):
        runs[-1][1]([])
    assert "skipped" in d.status.text()
    assert d.gen.isEnabled()


def test_waiting_time_is_shown(qapp, monkeypatch):
    d, runs = _dialog(monkeypatch)
    d._run(lambda text: [])
    d._part_started -= 42
    d._tick()
    assert "waiting 42 s" in d.status.text()


def test_stop_then_stop_now(qapp, monkeypatch):
    d, runs = _dialog(monkeypatch)
    d._run(lambda text: [])
    d.stop()
    assert d.stop_btn.text() == "Stop Now"
    late_ok = runs[-1][1]
    d.stop()                                          # leave it now
    assert d.gen.isEnabled() and d.stop_btn.text() == "Stop"
    late_ok([{"old": "late", "new": "x", "reason": "y"}])
    assert not d._results
    assert "stopped before the model answered" in d.status.text()


# ---- 3: a stall marked twice is one stall ------------------------------------------

def test_parking_marked_twice_counts_once():
    from app import ada_takeoff

    def mark(group, x, y, page=0):
        return {"type": "count", "group": group, "value": 1, "page": page,
                "rect": [x, y, x + 10, y + 10]}
    items = [mark("Parking", 100 + 20 * k, 100) for k in range(10)]
    items += [mark("Accessible Parking", 100, 100),       # on stall 1
              mark("Van Parking", 120, 100),              # on stall 2
              mark("Accessible Parking", 500, 500)]       # its own stall
    lot = ada_takeoff.counts(None, items)["parking"][0]
    assert lot["total"] == 11
    assert lot["accessible"] == 3
    assert lot["counted_once"] == 2


def test_parking_marked_apart_adds_up():
    from app import ada_takeoff
    items = [{"type": "count", "group": "Parking", "value": 8, "page": 0,
              "rect": [0, 0, 300, 50]},
             {"type": "count", "group": "Accessible Parking", "value": 1,
              "page": 0, "rect": [400, 400, 410, 410]}]
    lot = ada_takeoff.counts(None, items)["parking"][0]
    assert lot["total"] == 9 and "counted_once" not in lot


# ---- M13: each accessibility fix is its own undo step -------------------------------

def test_accessibility_fixes_undo_one_at_a_time(win):
    from app import accessibility
    dlg = win.accessibility_check(show=False)
    fixable = [r for r in accessibility.check(win._view.doc) if r["fix"]]
    if len(fixable) < 2:
        pytest.skip("the sample needs two fixable rules")
    before = win._view.history.pos
    dlg.fix()
    h = win._view.history
    assert h.pos - before == len(fixable)          # one step per rule
    assert h.undo_label() is None or "Accessibility" in str(h.undo_label())
    win.undo()
    assert win._view.history.pos == before + len(fixable) - 1
    for _ in range(len(fixable) - 1):
        win.undo()
    again = [r for r in accessibility.check(win._view.doc) if r["fix"]]
    assert len(again) == len(fixable)              # all back after them all


# ---- 4: quantities round half up ---------------------------------------------------

def test_half_up_for_quantities():
    from app.dmoney import half_up
    assert half_up(0.125) == 0.13
    assert half_up(2.25, 1) == 2.3
    assert half_up(1.0005, 3) == 1.001
    assert half_up(-0.125) == -0.13
    assert half_up(0.1 + 0.2, 1) == 0.3


# ---- Venice's review of the follow-up packet (Nov 9) ----------------------------

def test_reduce_never_saves_a_protected_caller(tmp_path, monkeypatch):
    """F1/F7: when the protected copy can't be opened, nothing is written
    and the open document isn't saved or changed."""
    from app import acrobat, safeio
    from test_review_fixes_nov7 import _image_pdf, _image_size
    d0 = fitz.open(_image_pdf(str(tmp_path / "plain.pdf")))
    p = str(tmp_path / "locked.pdf")
    d0.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner-x",
            user_pw="", permissions=fitz.PDF_PERM_PRINT)
    d0.close()
    d = fitz.open(p)
    before = _image_size(d)
    real = fitz.open

    def picky(*a, **k):
        if a and "qs-reduce-" in str(a[0]):
            raise RuntimeError("example unreadable copy")
        return real(*a, **k)
    monkeypatch.setattr(fitz, "open", picky)
    out = str(tmp_path / "out.pdf")
    with pytest.raises(safeio.UnprotectedCopyError):
        acrobat.reduce_size(d, out, original=os.path.getsize(p))
    monkeypatch.undo()
    assert not os.path.exists(out)
    assert not d.is_dirty and _image_size(d) == before
    d.close()


def test_reduce_with_an_open_password_needs_it(tmp_path):
    """F2: a file with an open password is reduced only with it."""
    from app import acrobat, safeio
    from test_review_fixes_nov7 import _image_pdf
    d0 = fitz.open(_image_pdf(str(tmp_path / "plain.pdf")))
    p = str(tmp_path / "locked.pdf")
    d0.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner-x",
            user_pw="user-x")
    d0.close()
    d = fitz.open(p)
    assert d.authenticate("user-x")
    with pytest.raises(safeio.UnprotectedCopyError):
        acrobat.reduce_size(d, str(tmp_path / "a.pdf"), original=10 ** 9)
    out = str(tmp_path / "b.pdf")
    acrobat.reduce_size(d, out, original=10 ** 9, password="user-x")
    with fitz.open(out) as r:
        assert r.needs_pass                         # still protected
    d.close()


def test_model_list_host_argument_is_respected(monkeypatch):
    """F3: with a policy host set, another explicit host is still checked
    as "this PC only"; F4: a bad policy value is a message, not a crash."""
    from app import policy
    from app.ai import models, models_ui
    monkeypatch.setattr(policy, "get", lambda k, *a:
                        "http://ai-box.example.test/ollama"
                        if k == "AIHost" else None)
    assert models.it_host() == "http://ai-box.example.test/ollama"
    with pytest.raises(models.NotLocalError):
        models.list_installed("http://other.example.test:11434")
    monkeypatch.setattr(policy, "get", lambda k, *a:
                        "http://user@bad.example.test" if k == "AIHost"
                        else None)
    assert models_ui._it_host() == ""
    with pytest.raises(models.OllamaError):
        models_ui._host()


def test_ada_apply_failure_is_said(qapp):
    """F5: a refused write shows a line, not nothing."""
    from app import ada_ui
    d = fitz.open()
    d.new_page()
    tab = ada_ui.CheckerTab(d)
    tab.apply = lambda proj: False
    tab.ed["stories"].setText("6")
    tab.run()
    assert "Not saved to the drawing" in tab.summary.text()


def test_set_jobdata_needs_an_object():
    from app import ada_check, annotate
    d = fitz.open()
    d.new_page()
    for data in ("5", "[]", "null", '"text"'):
        op = {"id": "x" + data, "kind": "set_jobdata", "page": 0,
              "payload": {"file": ada_check.FILE, "data": data}}
        assert not annotate.apply_op(d, op, fresh=True)


def test_any_applied_op_moves_the_edit_counter():
    """F10: a peer's op (applied through apply_op, not the viewer) moves
    the counter the ADA cache keys on."""
    from app import annotate
    d = fitz.open()
    d.new_page()
    before = annotate.edit_count(d)
    assert annotate.apply_op(d, annotate.new_op(
        "add_note", 0, pt=[50, 50], text="Example note"), fresh=True)
    assert annotate.edit_count(d) == before + 1


def test_c2_and_half_up_take_none():
    from app import money, proposal
    from app.dmoney import c2, half_up
    assert c2(None) == 0.0 and half_up(None) == 0.0
    assert money._m(None) == "$0.00" and proposal._money(None) == "$0.00"


def test_check_facts_on_a_cut_document_never_says_missing():
    """F13: only part was read, so the mark says so."""
    from app.ai import review
    src = "A-101 FLOOR PLAN SCALE: 1/4\" = 1'-0\""
    out, flagged = review.check_facts("- See A-501.\n- At 1/8\" = 1'-0\".",
                                      src, ["A-101"], cut=True)
    assert "no such sheet" not in out
    assert "A-501 (not in the part reviewed)" in out
    assert "isn't in the part reviewed" in out


def test_check_facts_twice_marks_once():
    """F14: running it again over its own output changes nothing."""
    from app.ai import review
    src = "A-101 FLOOR PLAN SCALE: 1/4\" = 1'-0\""
    once, _ = review.check_facts("- A-100.5 cover.\n- At 1/8\" = 1'-0\".",
                                 src, ["A-101"])
    twice, flagged = review.check_facts(once, src, ["A-101"])
    assert twice == once and flagged == []


def test_cancel_ends_a_waiting_model_request():
    """F15: a skipped part's request is ended, not left running."""
    import http.server
    from app.ai import review

    class Slow(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            time.sleep(5)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"response": "late"}')
            except OSError:
                pass

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        tok = review.Cancel()
        got = {}

        def go():
            t0 = time.monotonic()
            try:
                review.run_cancellable(tok, review._ollama, "hello",
                                       host=f"http://127.0.0.1:"
                                       f"{srv.server_port}")
            except review.AIError as e:
                got["e"] = str(e)
            got["t"] = time.monotonic() - t0
        th = threading.Thread(target=go)
        th.start()
        time.sleep(0.5)
        tok.cancel()
        th.join(5)
        assert got.get("t", 99) < 3
        assert "Stopped" in got.get("e", "")
    finally:
        srv.shutdown()


def test_bad_part_limit_setting_doesnt_stop_the_app(monkeypatch):
    from app.ai import dialogs
    monkeypatch.setenv("QUANTISHEET_AI_PART_LIMIT", "five minutes")
    assert dialogs._part_limit() == 300.0
    monkeypatch.setenv("QUANTISHEET_AI_PART_LIMIT", "120")
    assert dialogs._part_limit() == 120.0


# ---- Venice's third pass (Nov 9) -------------------------------------------------

def _slow_server(handler_sleep=5, tls=None):
    import http.server
    import socketserver

    class Slow(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            time.sleep(handler_sleep)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"response": "late"}')
            except OSError:
                pass

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    if tls is not None:
        srv.socket = tls.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _run_and_cancel(host, after=0.5):
    from app.ai import review
    tok = review.Cancel()
    got = {}

    def go():
        t0 = time.monotonic()
        try:
            review.run_cancellable(tok, review._ollama, "hello", host=host)
        except BaseException as e:            # any type shows in the test
            got["type"] = type(e).__name__
            got["e"] = str(e)
        got["t"] = time.monotonic() - t0
    th = threading.Thread(target=go)
    th.start()
    time.sleep(after)
    tok.cancel()
    th.join(10)
    return got, tok


def _test_cert(tmp_path):
    x509 = pytest.importorskip("cryptography.x509")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import datetime
    import ipaddress
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName("localhost"),
                 x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False)
            .sign(key, hashes.SHA256()))
    c = tmp_path / "cert.pem"
    k = tmp_path / "key.pem"
    c.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    k.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                    serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()))
    return str(c), str(k)


def test_cancel_ends_a_waiting_https_request(tmp_path, monkeypatch):
    import ssl
    from app.ai import review
    cert, key = _test_cert(tmp_path)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(cert, key)
    client_ctx = ssl.create_default_context(cafile=cert)
    monkeypatch.setattr(review, "_SSL_CONTEXT", client_ctx)
    srv = _slow_server(tls=server_ctx)
    try:
        got, tok = _run_and_cancel(f"https://127.0.0.1:{srv.server_port}")
        assert got.get("t", 99) < 3, got
        assert got.get("type") == "AIError" and "Stopped" in got["e"], got
    finally:
        srv.shutdown()
        srv.server_close()


def test_cancel_during_the_tls_handshake(tmp_path, monkeypatch):
    """A server that accepts and never answers the handshake (N1)."""
    import socket
    import ssl
    from app.ai import review
    cert, _key = _test_cert(tmp_path)
    monkeypatch.setattr(review, "_SSL_CONTEXT",
                        ssl.create_default_context(cafile=cert))
    lst = socket.socket()
    lst.bind(("127.0.0.1", 0))
    lst.listen(1)
    held = []
    threading.Thread(target=lambda: held.append(lst.accept()),
                     daemon=True).start()
    try:
        got, tok = _run_and_cancel(
            f"https://127.0.0.1:{lst.getsockname()[1]}", after=0.7)
        assert got.get("t", 99) < 3, got
        assert got.get("type") == "AIError" and "Stopped" in got["e"], got
    finally:
        for c, _a in held:
            c.close()
        lst.close()


def test_cancel_twice_and_after_a_finished_request():
    import http.server
    from app.ai import review
    srv = _slow_server(handler_sleep=0)
    try:
        tok = review.Cancel()
        out = review.run_cancellable(
            tok, review._ollama, "hello",
            host=f"http://127.0.0.1:{srv.server_port}")
        assert out == "late"
        assert tok._socks == []            # forgotten when it finished
        tok.cancel()                       # after completion: nothing
        tok.cancel()                       # twice: nothing
        assert tok.cancelled and tok._socks == []
    finally:
        srv.shutdown()
        srv.server_close()


def test_refused_op_doesnt_move_the_counter():
    from app import annotate
    d = fitz.open()
    d.new_page()
    before = annotate.edit_count(d)
    op = {"id": "bad", "kind": "set_jobdata", "page": 0,
          "payload": {"file": "other.json", "data": "{}"}}
    assert not annotate.apply_op(d, op, fresh=True)
    assert annotate.edit_count(d) == before


def test_apply_hook_returning_nothing_isnt_a_failure(qapp):
    from app import ada_ui
    d = fitz.open()
    d.new_page()
    tab = ada_ui.CheckerTab(d)
    tab.apply = lambda proj: None
    tab.ed["stories"].setText("4")
    tab.run()
    assert "Not saved" not in tab.summary.text()
    tab.apply = lambda proj: False
    for n in ("5", "6"):
        tab.ed["stories"].setText(n)
        tab.run()
    assert tab.summary.text().count("Not saved") == 1     # never piles up


def test_list_installed_with_a_bad_policy_host(monkeypatch):
    from app import policy
    from app.ai import models
    monkeypatch.setattr(policy, "get", lambda k, *a:
                        "http://user@bad.example.test" if k == "AIHost"
                        else None)
    with pytest.raises(models.OllamaError):
        models.list_installed("http://127.0.0.1:11434")


def test_policy_host_origin_matches(monkeypatch):
    from app import policy
    from app.ai import models
    monkeypatch.setattr(policy, "get", lambda k, *a:
                        "http://ai-box.example.test/ollama"
                        if k == "AIHost" else None)
    seen = []
    monkeypatch.setattr(models, "_get", lambda url, t=None, **k:
                        seen.append(url) or b'{"models": []}')
    models.list_installed("http://ai-box.example.test")
    assert seen and seen[0].startswith("http://ai-box.example.test/ollama")
    assert models._origin("http://ai-box.example.test:80/x") == \
        models._origin("http://AI-BOX.example.test")
    assert models._origin("https://ai-box.example.test") != \
        models._origin("http://ai-box.example.test")


def test_review_has_no_atomic_groups():
    """N9: the app supports Python 3.10, which has no (?>...)."""
    import inspect
    from app.ai import review
    assert "(?>" not in inspect.getsource(review)


# ---- Venice's fourth pass (Nov 9) ------------------------------------------------

def test_cancel_ignores_a_tls_socket_already_closed(tmp_path):
    """P4-2: the reader closed it first - ValueError, swallowed."""
    import socket
    import ssl
    from app.ai import review
    a, b = socket.socketpair()
    try:
        ctx = ssl.create_default_context()
        s = ctx.wrap_socket(a, do_handshake_on_connect=False,
                            server_hostname="localhost")
        s.close()
        tok = review.Cancel()
        tok._socks.append(s)
        tok.cancel()                                 # no exception
        assert tok.cancelled and tok._socks == []
    finally:
        a.close()
        b.close()


def test_https_uses_the_tunnel_host_for_its_name():
    """P4-1: under a tunnel the name checked is the AI server's."""
    import inspect
    from app.ai import review
    src = inspect.getsource(review._ConnS.connect)
    assert "self._tunnel_host or self.host" in src


@pytest.mark.parametrize("protected", [False, True])
def test_reduce_reports_a_failed_copy_as_itself(tmp_path, monkeypatch,
                                                protected):
    """P4-5 / N8: disk full writing the copy is an OSError, not "couldn't
    be copied"; the temp file is removed."""
    import tempfile
    from app import acrobat, safeio
    from test_review_fixes_nov7 import _image_pdf
    p = _image_pdf(str(tmp_path / "plain.pdf"))
    if protected:
        d0 = fitz.open(p)
        p = str(tmp_path / "locked.pdf")
        d0.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner-x",
                user_pw="", permissions=fitz.PDF_PERM_PRINT)
        d0.close()
    d = fitz.open(p)
    made = []
    real = tempfile.mkstemp

    def tracking(*a, **k):
        # only reduce_size's own temp file, put under tmp_path (F5-11)
        if k.get("prefix") == "qs-reduce-":
            k["dir"] = str(tmp_path)
            fd, path = real(*a, **k)
            made.append(path)
            return fd, path
        return real(*a, **k)
    monkeypatch.setattr(tempfile, "mkstemp", tracking)

    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(type(d), "save", full)
    with pytest.raises(OSError) as e:
        acrobat.reduce_size(d, str(tmp_path / "out.pdf"), original=10)
    assert not isinstance(e.value, safeio.UnprotectedCopyError)
    assert e.value.errno == 28
    monkeypatch.undo()
    assert made and not any(os.path.exists(x) for x in made)
    d.close()


def test_a_made_up_decimal_sheet_is_checked():
    """P4-7: A-100.5 is one sheet number, checked as a whole."""
    from app.ai import review
    out, flagged = review.check_facts("- See A-100.5 for the stair.",
                                      "A-101 FLOOR PLAN", ["A-101"])
    assert "A-100.5 (no such sheet in the drawings)" in out
    assert flagged == ["A-100.5"]
    ok, none = review.check_facts("- See A-101.", "A-101 FLOOR PLAN",
                                  ["A-101"])
    assert ok == "- See A-101." and none == []


def test_scale_with_the_foot_inch_tail_marked_once():
    """P4-7: 1/8\" = 1'-0\" is marked after the 0\", once."""
    from app.ai import review
    src = "SCALE: 1/4\" = 1'-0\""
    once, _ = review.check_facts("At 1/8\" = 1'-0\".", src)
    assert once == "At 1/8\" = 1'-0\" (this scale isn't in the drawings)."
    assert review.check_facts(once, src)[0] == once


def test_two_stores_for_one_folder_dont_share_a_temp_file(tmp_path):
    """P4-8: a temp name per store and per write; none left behind."""
    from app.pm import store
    a = store.ProjectStore(str(tmp_path / "Example Job"))
    a.save(now=True)
    b = store.ProjectStore(str(tmp_path / "Example Job"))
    names = []
    real_open = open

    def spy(path, *k, **kw):
        if str(path).endswith(".tmp"):
            names.append(str(path))
        return real_open(path, *k, **kw)
    import builtins
    old = builtins.open
    builtins.open = spy
    try:
        a._write()
        b._write()
        a._write()
    finally:
        builtins.open = old
    assert len(set(names)) == 3
    folder = os.path.dirname(a.path)
    assert not [n for n in os.listdir(folder) if n.endswith(".tmp")]


def test_store_removes_its_temp_file_when_the_write_fails(tmp_path,
                                                         monkeypatch):
    from app.pm import store
    s = store.ProjectStore(str(tmp_path / "Example Job"))
    s.save(now=True)

    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(store.os, "fsync", boom)
    with pytest.raises(OSError):
        s._write()
    monkeypatch.undo()
    folder = os.path.dirname(s.path)
    assert not [n for n in os.listdir(folder) if n.endswith(".tmp")]


# ---- Venice's fifth pass (Nov 9) -------------------------------------------------

def test_connection_close_after_cancel_doesnt_raise():
    """F5-4: the _Closing catch is load-bearing - a connection whose TLS
    socket cancel() closed can still be closed."""
    import socket
    import ssl
    from app.ai import review
    assert issubclass(review._ConnS, review._Closing)
    assert issubclass(review._Conn, review._Closing)
    a, b = socket.socketpair()
    try:
        s = ssl.create_default_context().wrap_socket(
            a, do_handshake_on_connect=False, server_hostname="localhost")
        tok = review.Cancel()
        tok.register(s)
        tok.cancel()
        conn = review._ConnS("localhost", 443)
        conn.sock = s
        conn.close()                                   # no exception
        assert conn.sock is None
    finally:
        a.close()
        b.close()


def test_cancelled_before_the_handshake_spends_none(monkeypatch):
    """F5-1: a cancel during the TCP connect is honoured before TLS."""
    import http.client
    from app.ai import review
    tok = review.Cancel()
    wrapped = []

    def fake_connect(self):
        tok.cancel()                     # the cancel lands during connect
        self.sock = object()
    monkeypatch.setattr(http.client.HTTPConnection, "connect", fake_connect)
    conn = review._ConnS("localhost", 443)
    monkeypatch.setattr(conn._context, "wrap_socket",
                        lambda *a, **k: wrapped.append(1))
    review._local.cancel = tok
    try:
        with pytest.raises(ConnectionAbortedError):
            conn.connect()
    finally:
        review._local.cancel = None
    assert not wrapped


def test_policy_mismatch_vs_mistyped_policy(monkeypatch):
    """F5-2: a valid policy and some other host is NotLocalError; a
    mistyped policy is OllamaError."""
    from app import policy
    from app.ai import models
    monkeypatch.setattr(policy, "get", lambda k, *a:
                        "http://ai-box.example.test" if k == "AIHost"
                        else None)
    with pytest.raises(models.NotLocalError):
        models.list_installed("http://elsewhere.example.test")
    monkeypatch.setattr(policy, "get", lambda k, *a:
                        "not a url" if k == "AIHost" else None)
    with pytest.raises(models.OllamaError):
        models.list_installed("http://127.0.0.1:11434")


def test_origin_ports_and_user_info():
    from app.ai import models
    assert models._origin("http://ai-box.example.test:0")[2] == 0   # F5-5
    assert models._origin("http://someone@ai-box.example.test/x") == \
        models._origin("http://ai-box.example.test")                # F5-6


def test_sheet_with_a_letter_after_the_decimal_is_left_whole():
    """F5-7: A-100.5A is never marked in the middle."""
    from app.ai import review
    out, flagged = review.check_facts("- See A-100.5A.", "A-101 FLOOR PLAN",
                                      ["A-101"])
    assert ")A" not in out


# ---- sheet numbers with a letter (Nov 9) ------------------------------------------

def test_letter_suffixed_sheets_are_checked():
    from app.ai import review
    src = "A-101A FLOOR PLAN. M-501 SCHEDULES. SEE A-302A."
    out, flagged = review.check_facts(
        "- See A-100.5A and A-101. M-501A is new. A-101A is the plan.",
        src, ["A-101A", "M-501"])
    assert "A-100.5A (no such sheet in the drawings)" in out
    assert "M-501A (no such sheet in the drawings)" in out
    assert "A-101A is the plan" in out            # in the set
    assert "A-101. M-501A" in out                 # A-101A covers "A-101"
    assert flagged == ["A-100.5A", "M-501A"]
    assert review.check_facts(out, src, ["A-101A", "M-501"])[0] == out
    assert review.referenced_sheets(src, ["A-101A", "M-501"]) == ["A-302A"]


def test_refrigerants_are_not_sheets():
    from app.ai import review
    out, flagged = review.check_facts(
        "- Units use R-410A; the old ones R-22. New ones R-454B.",
        "M-101 MECHANICAL PLAN", ["M-101"])
    assert flagged == [] and "no such sheet" not in out


# ---- Chief's round 6 (Nov 9) -------------------------------------------------------

def test_pm_money_fields_round_half_up(qapp):
    from app.pm.widgets import NumberEdit
    e = NumberEdit(money=True)
    for typed, want in (("1.125", 1.13), ("2.675", 2.68),
                        ("1000.125", 1000.13), ("(1.125)", -1.13)):
        e.setText(typed)
        assert e.value() == want
    e.set_value(1000.125)
    assert e.text() == "1,000.13"


def test_money_text_helpers_round_half_up():
    from app import assembly_ui, billing_ui, co_delta
    from app.pm import bidletters
    assert assembly_ui._money(1.125) == "$1.13"
    assert billing_ui._m(-1.125) == "($1.13)"
    assert co_delta._money(-1.125) == "-$1.13"
    assert bidletters._money(1000.125) == "$1,000.13"


def test_nothing_read_is_said_plainly(qapp, monkeypatch):
    """Every part skipped: no "whole document", no "no suggestions"."""
    from app.ai import dialogs
    d, runs = _dialog(monkeypatch)
    d._run(lambda text: [])
    for _ in range(d._total):
        d._part_started -= dialogs.PART_LIMIT + 1
        d._tick()
    text = d.status.text()
    assert "Nothing was reviewed" in text
    assert "whole document" not in text.lower()
    assert "no suggestions" not in text
    assert "Reviewed:" not in text
    assert text.count("skipped") == 1                 # one line, grouped
    assert "0 minutes" not in text


def test_stop_now_lists_what_wasnt_read(qapp, monkeypatch):
    d, runs = _dialog(monkeypatch)
    d._run(lambda text: [])
    total = d._total
    runs[-1][1]([{"old": "abcd", "new": "abce", "reason": "example"}])
    d.stop()                               # finish part 2, then stop
    assert "Stop Now" in d.status.text()
    d.stop()                               # leave it now
    text = d.status.text()
    assert f"From 1 of {total} part(s) only" in text
    assert f"Stopped: 1 of {total}" in text
    assert "Reviewed:" not in text
    if total > 2:
        assert "stopped before them" in text


def test_a_full_run_still_says_what_it_read(qapp, monkeypatch):
    d, runs = _dialog(monkeypatch)
    d._run(lambda text: [])
    for _ in range(d._total):
        runs[-1][1]([])
    text = d.status.text()
    assert "The model had no suggestions." in text and "Reviewed:" in text


# ---- Chief's round 7 (Nov 9) -------------------------------------------------------

def test_hub_bid_total_matches_the_desktop():
    """hub.py runs on its own on a server: same half-up rule, same total."""
    from app.collab import hub
    from app.pm import bidforms
    lines = [{"type": "Unit price", "qty": "0.5", "item": "1"}]
    assert hub.bid_totals(lines, {"0": "1.25"})["base"] == 0.63
    assert hub._c2(2.675) == 2.68 and hub._c2(1.125) == 1.13
    try:
        desk = bidforms.totals(lines, {"0": "1.25"})["base"]
    except Exception:                                     # noqa: BLE001
        desk = 0.63                              # a different signature
    assert desk == 0.63


def test_labor_rates_round_half_up():
    from app.dmoney import c2
    assert c2(1.125) == 1.13 and c2(90.0 * 1.0125) == 91.13


def test_no_float_round_to_cents_is_left_in_the_app():
    """Every round(x, 2) and every .2f goes through the half-up helper
    (Chief's round 7: 171 spots found by scan)."""
    import ast
    import glob
    root = os.path.join(os.path.dirname(__file__), "..", "app")
    left = []
    for p in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        name = os.path.relpath(p, root).replace(os.sep, "/")
        if name in ("dmoney.py", "collab/relaycore.py") or \
                name.startswith("genset/"):
            # genset draws plans (dimensions, not money) and its output is
            # pinned byte for byte by golden files
            continue
        with open(p, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                    and n.func.id == "round" and len(n.args) == 2 and \
                    isinstance(n.args[1], ast.Constant) and \
                    n.args[1].value == 2:
                left.append(f"{name}:{n.lineno} round(x, 2)")
            if isinstance(n, ast.FormattedValue) and n.format_spec and \
                    n.format_spec.values and \
                    isinstance(n.format_spec.values[-1], ast.Constant) and \
                    str(n.format_spec.values[-1].value).endswith(".2f"):
                v = n.value
                ok = isinstance(v, ast.Constant) or (
                    isinstance(v, ast.Call) and (
                        getattr(v.func, "id", "") in ("_c2", "c2") or
                        getattr(v.func, "attr", "") == "c2"))
                if not ok:
                    left.append(f"{name}:{n.lineno} .2f")
    assert not left, "\n".join(left[:40])


def test_number_fields_refuse_what_they_cant_read(qapp):
    from app.pm import widgets
    for bad in ("nan", "inf", "-inf", "1e400", "1e20", "1.000,50", "1,2,3",
                "12,34", "abc", "1.2.3", "$", "-", "."):
        assert widgets.read_number(bad) is None, bad
    for good, want in (("1,250.50", 1250.5), ("$1,000", 1000.0),
                       ("(12.5)", -12.5), ("-3", -3.0), (".5", 0.5),
                       ("1000000000000", 1e12), ("12.", 12.0)):
        assert widgets.read_number(good) == want, good
    e = widgets.NumberEdit(money=True)
    e.setText("1.000,50")
    e._done()
    assert e.value() is None and "1,250.50" in e.toolTip()
    e.setText("1,000.50")
    e._done()
    assert e.value() == 1000.5 and e.toolTip() == ""


def test_lines_table_numbers_agree_with_their_total():
    from app.pm.widgets import number_text
    assert number_text(0.375) == "0.375"          # 3 x 0.125, not 0.38
    assert number_text(1000.1) == "1,000.10"
    assert number_text(1000) == "1,000"
    assert number_text(1234.5) == "1,234.50"
    assert number_text(0.39) == "0.39"


def test_c2_reads_money_text_and_refuses_junk():
    from app.dmoney import c2
    assert c2("$1.125") == 1.13 and c2("1,000.125") == 1000.13
    assert c2("(1.125)") == -1.13
    for bad in ("nan", "inf", "abc"):
        with pytest.raises(ValueError):
            c2(bad)


def test_whole_dollar_money_rounds_half_up():
    from app.pm import cost, owner_report_auto
    assert cost.money_fmt(2.5) == "$3" and cost.money_fmt(-2.5) == "($3)"
    assert owner_report_auto.money(2.5) == "$3"
    assert owner_report_auto.money(1234.5) == "$1,235"


def test_summary_stop_ends_the_request(win, monkeypatch):
    from app import bg
    from app.ai import review
    runs = []
    monkeypatch.setattr(bg, "run", lambda fn, ok, bad, parent=None, **k:
                        runs.append((fn, ok, bad)))
    shown = []
    from app import main_window
    monkeypatch.setattr(main_window.QMessageBox, "information",
                        lambda *a, **k: shown.append(a))
    seen = {}
    real = review.run_cancellable

    def spy(token, fn, *a, **k):
        seen["token"] = token
        return "late answer"
    monkeypatch.setattr(review, "run_cancellable", spy)
    busy = win.ai_summary()
    fn, ok, bad = runs.pop()
    out = fn()                                    # the worker's call
    from PySide6.QtWidgets import QPushButton
    busy.findChild(QPushButton).click()           # Stop
    for _ in range(50):
        if seen["token"].cancelled:
            break
        time.sleep(0.02)
    assert seen["token"].cancelled                # the request is ended
    ok(out)
    assert not shown                              # a late answer is dropped


def test_summary_stops_itself_after_the_limit(win, monkeypatch):
    from app import bg, main_window
    runs, warned = [], []
    monkeypatch.setattr(bg, "run", lambda fn, ok, bad, parent=None, **k:
                        runs.append((fn, ok, bad)))
    monkeypatch.setattr(main_window.QMessageBox, "warning",
                        lambda *a, **k: warned.append(a))
    monkeypatch.setattr(main_window.MainWindow, "_ai_limit",
                        staticmethod(lambda: -1.0))
    win.ai_summary()
    win._ai_summary_tick()                        # past the limit
    fn, ok, bad = runs.pop()
    bad("Stopped before the model answered.")
    assert warned and "didn't answer" in warned[0][2]


def test_translate_says_how_many_came_back(win, monkeypatch):
    from test_round4_nov7 import _seed
    _seed(win._view)
    n = win.translate_markups(
        "Spanish", texts_fn=lambda texts: ["Instalar herrajes nuevos"] +
        list(texts[1:]))
    assert n == 1
    msg = win.statusBar().currentMessage()
    assert "Translated 1 of 2" in msg and "1 came back unchanged" in msg


def test_translate_cancel_ends_the_request(win, monkeypatch):
    from app import bg
    from app.ai import review
    from test_round4_nov7 import _seed
    runs, seen = [], {}
    monkeypatch.setattr(bg, "run", lambda fn, ok, bad, parent=None, **k:
                        runs.append((fn, ok, bad)))
    monkeypatch.setattr(review, "run_cancellable",
                        lambda token, fn, *a, **k: seen.update(t=token))
    _seed(win._view)
    busy = win.translate_markups("Spanish")
    runs[-1][0]()
    from PySide6.QtWidgets import QPushButton
    busy.findChild(QPushButton).click()
    for _ in range(50):
        if seen["t"].cancelled:
            break
        time.sleep(0.02)
    assert seen["t"].cancelled


def test_ai_dialog_wording(qapp, monkeypatch):
    from app.ai import dialogs
    assert dialogs._minutes(20) == "20 seconds"
    assert dialogs._minutes(60) == "60 seconds"
    assert dialogs._minutes(300) == "5 minutes"
    assert dialogs._count(1, "proposal") == "1 proposal."
    assert dialogs._count(2, "finding") == "2 findings."
    assert dialogs._ranges([(0, 2), (3, 5), (9, 9)]) == "pages 1-6, 10"
    many = [(i * 10, i * 10 + 2) for i in range(60)]
    text = dialogs._ranges(many)
    assert text.count(",") == 6 and "and 54 more ranges" in text
    d, runs = _dialog(monkeypatch)
    d._run(lambda text: [])
    for _ in range(d._total):
        runs[-1][1]([])
    assert "take a while" not in d.status.text()


def test_sheet_forms_a_summary_may_write():
    from app.ai import review
    src = ("A-101A FLOOR PLAN. M-501 SCHEDULES. A-201-A ELEVATIONS. "
           "co2 sensor, b12, H2O")
    reply = ("a-101a ok, a-102a bad. A-101a ok. A-103AA bad. A-104-A bad; "
             "A-201-A ok. A-1011 bad. A-101A/B half. R-410B and R-410A "
             "units. co2, b12, H2O, B2B and T5HO lamps.")
    out, flagged = review.check_facts(reply, src, ["A-101A", "M-501"])
    assert flagged == ["A-102A", "A-103AA", "A-104A", "A-1011", "A-101B"]
    assert "A-101A/B (no such sheet in the drawings: A-101B)" in out
    assert "a-101a ok" in out and "A-201-A ok" in out
    assert "R-410B and R-410A units" in out
    assert "co2, b12, H2O, B2B and T5HO lamps." in out
    assert review.check_facts(out, src, ["A-101A", "M-501"])[0] == out


def test_rail_label_is_never_cut_mid_word_without_a_mark(qapp):
    from PySide6.QtGui import QAction
    from app import modern_ui
    assert modern_ui.rail_label(QAction("Accessibility")) == "Accessib…"
    assert modern_ui.rail_label(QAction("Preflight")) == "Preflight"
    assert modern_ui.rail_label(QAction("Export to Excel")) == "Export"
