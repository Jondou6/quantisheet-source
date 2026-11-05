"""First-start sign-in: only the company's addresses, nothing hinted,
five tries then a 15-minute lock (unlock code from Jon). The tests use a stand-in domain so
the real one never appears in the source."""
import hashlib
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                  # noqa: E402

from app import onboard, settings                              # noqa: E402

FAKE = "example-builders.test"


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DIR", str(tmp_path))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings, "_cache", {})
    reg = {"t": "", "s": ""}
    monkeypatch.setattr(onboard, "_reg_read",
                        lambda name="t": reg.get(name, ""))
    monkeypatch.setattr(onboard, "_reg_write",
                        lambda text, name="t": reg.__setitem__(name, text))
    h = hashlib.sha256((onboard._S + "|" + FAKE).encode()).hexdigest()
    monkeypatch.setattr(onboard, "_A", h[:32])
    monkeypatch.setattr(onboard, "_B", h[32:])
    monkeypatch.setattr(onboard, "_machine", lambda: "TEST-PC")
    return reg


def test_only_the_company_domain_passes():
    assert onboard.accepted(f"jon@{FAKE}")
    assert onboard.accepted(f"  Pat.Morgan@{FAKE.upper()} ")
    for bad in ("jon@gmail.com", f"jon@{FAKE}x", f"jon@sub.{FAKE}", FAKE,
                f"@{FAKE}", "", "not an email"):
        assert not onboard.accepted(bad), bad


def test_no_readable_domain_in_the_code():
    import re
    src = open(onboard.__file__, encoding="utf-8").read().lower()
    assert not re.search(r"[a-z0-9-]+\.(com|net|org|us|co)\b", src)


def test_five_wrong_then_locked_for_fifteen_minutes():
    """Jon, Oct 19 (Grok M8): 5 tries, then a 15-minute lock."""
    t = 1_000_000.0
    for i in range(4):
        assert onboard.attempt(f"x{i}@gmail.com", t + i) == "invalid"
    assert onboard.attempt("e@gmail.com", t + 4) == "locked"
    # even the right address is refused while locked
    assert onboard.attempt(f"jon@{FAKE}", t + 60) == "locked"
    assert onboard.locked_until(t + 60) == pytest.approx(t + 4 + 15 * 60)
    assert not onboard.signed_in()
    later = t + 4 + 15 * 60 + 1          # after 15 minutes: the right one
    assert onboard.attempt(f"jon@{FAKE}", later) == "ok"
    assert onboard.signed_in()


def test_the_lock_survives_deleting_settings(fresh):
    t = 2_000_000.0
    for i in range(5):
        onboard.attempt(f"x{i}@nope.com", t)
    settings._cache.clear()                     # settings wiped
    assert onboard.locked_until(t + 10)         # the registry copy holds


def test_turning_the_clock_back_keeps_a_lock():
    t = 3_000_000.0
    for i in range(5):
        onboard.attempt(f"x{i}@nope.com", t)
    back = t - 24 * 3600                        # clock set a day back
    assert onboard.attempt(f"jon@{FAKE}", back) == "locked"


def test_a_clock_fix_after_one_typo_is_not_a_lock():
    """Grok M8: one typo, then the clock corrected 10 minutes back."""
    t = 4_000_000.0
    assert onboard.attempt("typo@gmail.com", t) == "invalid"
    assert onboard.attempt(f"jon@{FAKE}", t - 600) == "ok"


def test_common_slips_are_forgiven():
    for e in (f"jon@{FAKE}.", f" jon@{FAKE}, ", f"<jon@{FAKE}>",
              f"mailto:jon@{FAKE}"):
        assert onboard.accepted(e), e


def test_unlock_code_from_jon_clears_the_lock():
    t = time.time()
    for i in range(5):
        onboard.attempt(f"x{i}@nope.com", t)
    assert onboard.locked_until(t + 1)
    assert not onboard.unlock("WRONG123", t + 2)
    code = onboard.unlock_code(onboard.pc_code())
    assert onboard.unlock(code.lower(), t + 2)
    assert not onboard.locked_until(t + 3)
    assert onboard.attempt(f"jon@{FAKE}", t + 4) == "ok"
    other = onboard.unlock_code("ZZZ-999")
    assert other != code                       # tied to this PC


def test_signed_in_is_per_computer(monkeypatch):
    assert onboard.attempt(f"jon@{FAKE}") == "ok"
    assert onboard.signed_in()
    monkeypatch.setattr(onboard, "_machine", lambda: "OTHER-PC")
    assert not onboard.signed_in()              # copied settings don't count


def test_dialog_says_only_invalid(qapp=None):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    d = onboard.SignInDialog()
    d.email.setText("someone@gmail.com")
    d._try()
    assert d.msg.text() == "Invalid email."
    d.email.setText("someone@else.com")
    d._try()
    for i in range(3):
        d.email.setText(f"more{i}@else.com")
        d._try()
    assert d.msg.text().startswith("Too many attempts")
    assert onboard.pc_code() in d.msg.text()
    assert not d.email.isEnabled() and d.code.isVisibleTo(d)
    d.code.setText(onboard.unlock_code(onboard.pc_code()))
    d._unlock()
    assert d.email.isEnabled() and d.msg.text().startswith("Unlocked")
    d.close()


def test_asked_once_never_again(fresh):
    """Jon, Oct 19: sign in once per PC - a reinstall or a cleared
    settings file doesn't ask again."""
    assert onboard.attempt(f"jon@{FAKE}") == "ok"
    settings._cache.clear()                    # settings file wiped
    assert onboard.signed_in()                 # the registry copy holds
    assert settings.get("ui_cache_id") == onboard._token()   # restored
    fresh["s"] = ""                            # registry cleared instead
    assert onboard.signed_in()
    assert fresh["s"] == onboard._token()


def test_store_copy_never_asks_for_a_company_email(monkeypatch):
    """The Microsoft Store copy is for anyone (Oct 30); every other copy
    still asks once for a company email address."""
    from app import betalicense
    monkeypatch.setattr(betalicense, "is_store", lambda: False)
    assert not onboard.signed_in()
    monkeypatch.setattr(betalicense, "is_store", lambda: True)
    assert onboard.signed_in()
