"""Follow-ups to the Oct 15 code review: the in-app relay needs a token to
be reachable from the network (H-3), and an in-place save keeps a .bak of
the file first (M-1)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_network_relay_needs_a_token():
    from app.collab import relay
    with pytest.raises(SystemExit):
        relay.start_background("0.0.0.0", 0, 0, token=None)
    h = relay.RelayHandle("0.0.0.0", 8765, 8766, "abc123")
    ws, web = h.urls()
    # v33: token after "#" (never sent to a server or logged)
    assert web.endswith("/#t=abc123") and ws.startswith("ws://")


def test_backup_before_in_place_save(tmp_path):
    from app import main_window
    p = tmp_path / "plan.pdf"
    p.write_bytes(b"%PDF-1.7 first")
    bak = main_window.backup_before_incremental(str(p))
    assert bak and open(bak, "rb").read() == b"%PDF-1.7 first"
    p.write_bytes(b"%PDF-1.7 second")
    assert main_window.backup_before_incremental(str(p)) is None  # once
    assert open(bak, "rb").read() == b"%PDF-1.7 first"
    assert main_window.backup_before_incremental(
        str(tmp_path / "missing.pdf")) is None


def test_zero_priced_item_is_flagged():
    from app import assemblies, costbook
    b = costbook.Book({"name": "B", "items": {
        "X-1": {"unit": "ls", "material": 0, "labor": 0}}})
    a = {"name": "Bond", "parts": [{"name": "Premium", "code": "X-1",
                                    "unit": "LS", "qty": "1"}]}
    _out, problems = assemblies.priced(a, b)
    assert any("$0" in p for p in problems)
