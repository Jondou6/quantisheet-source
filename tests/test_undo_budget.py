"""M2: undo memory budget per document, sized to free RAM (~10%, at least
64 MB), oldest full snapshots evicted by bytes; 200-step cap kept."""
import fitz
import pytest

from app import history
from app.history import History

MB = 1024 * 1024


def test_budget_is_tenth_of_available_ram_with_floor(monkeypatch):
    monkeypatch.setattr(history, "_available_ram", lambda: 16 * 1024 * MB)
    assert history.default_budget() == int(16 * 1024 * MB * 0.10)
    monkeypatch.setattr(history, "_available_ram", lambda: 200 * MB)
    assert history.default_budget() == 64 * MB
    monkeypatch.setattr(history, "_available_ram", lambda: None)
    assert history.default_budget() == 64 * MB


def test_available_ram_reads_something_sane():
    n = history._available_ram()
    assert n is None or n > 16 * MB


def test_new_history_uses_ram_budget_and_keeps_step_cap(monkeypatch):
    monkeypatch.setattr(history, "_available_ram", lambda: 8 * 1024 * MB)
    h = History(b"x")
    assert h.max_bytes == int(8 * 1024 * MB * 0.10)
    assert h.limit == 200
    assert History(b"x", max_bytes=123).max_bytes == 123


def test_evicts_oldest_full_snapshots_by_bytes():
    h = History(b"0" * 100, max_bytes=1000)
    for i in range(1, 30):
        h.snapshot(bytes([65 + i % 26]) * 100 + str(i).encode())
    total = sum(e[3] for e in h.stack)
    assert total <= 1000
    # the newest steps are kept, one by one (not half the stack at once)
    assert len(h.stack) >= 9
    assert h.stack[-1][1].endswith(b"29")
    # undo walks back step by step through what's left
    seen = []
    while h.can_undo():
        seen.append(h.undo())
    assert seen[0].endswith(b"28") and seen[1].endswith(b"27")


def test_redo_survives_eviction():
    h = History(b"a" * 100, max_bytes=450)
    for i in range(6):
        h.snapshot(b"%d" % i * 100)
    h.undo()
    h.undo()
    assert h.can_redo()
    assert sum(e[3] for e in h.stack) <= 450 or h.pos < 1


def test_current_state_never_evicted():
    h = History(b"a" * 10, max_bytes=50)
    h.snapshot(b"b" * 500)                 # one step bigger than the budget
    assert h.stack[h.pos][1] == b"b" * 500
    assert h.can_undo() is False or h.undo() == b"a" * 10


def test_markup_steps_still_rebase_correctly():
    d = fitz.open()
    d.new_page()
    h = History(lambda: d.tobytes(), max_bytes=10 * MB)
    for i in range(5):
        before = h.begin_pages(d, [0])
        d[0].add_text_annot((20 + i * 10, 20), f"n{i}")
        h.commit_pages(d, before)
    h.limit = 4
    before = h.begin_pages(d, [0])
    d[0].add_text_annot((200, 20), "n5")
    h.commit_pages(d, before)
    assert len(h.stack) <= 4 or h.stack[0][0] == "full"
    assert h.stack[0][0] == "full"
    while h.can_undo():
        h.undo(d)
    assert len(list(d[0].annots())) >= 1
