"""Every Back Office test runs with a temp home and data folder. A guard
armed during each test refuses (and records) any open of ~/.quantisheet, any
price database, any import of QuantiSheet's app package (brief 1.2) and
any network connection to anything but this PC (P3-01 test 1.2)."""
import os
import sys
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

GUARD = {"armed": False, "violations": [], "installed": False, "net": []}


def _bad_path(p):
    try:
        p = os.fsdecode(p)
    except TypeError:
        return False
    if not isinstance(p, str) or not p:
        return False
    rp = os.path.realpath(p)
    base = os.path.basename(rp).lower()
    for name in (".quantisheet",):
        bad = os.path.realpath(os.path.join(os.path.expanduser("~"), name))
        if rp == bad or rp.startswith(bad + os.sep):
            return True
    return base.startswith("price") and base.endswith((".db", ".sqlite"))


def _local_host(host: str) -> bool:
    import ipaddress
    if host in ("localhost", "") or host.startswith("/"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def _hook(event, args):
    if not GUARD["armed"]:
        return
    if event in ("open", "sqlite3.connect", "os.open") and args:
        if _bad_path(args[0]):
            GUARD["violations"].append((event, str(args[0])))
            raise AssertionError(f"Back Office touched a forbidden path: {args[0]}")
    elif event == "socket.connect" and len(args) > 1:
        addr = args[1]
        host = addr[0] if isinstance(addr, tuple) and addr else addr
        if isinstance(host, str) and not _local_host(host):
            GUARD["net"].append(host)
            raise AssertionError(f"Back Office tried to connect to {host}; "
                                 f"only this PC (localhost) is allowed")
    elif event == "import" and args:
        name = str(args[0])
        if name == "app" or name.startswith("app."):
            GUARD["violations"].append((event, name))
            raise AssertionError(f"Back Office imported QuantiSheet's {name}")


class _NoAppFinder:
    """Also catches importlib.import_module of the host package, which
    skips the 'import' audit event."""

    @staticmethod
    def find_spec(name, path=None, target=None):
        if GUARD["armed"] and (name == "app" or name.startswith("app.")):
            GUARD["violations"].append(("import", name))
            raise AssertionError(f"Back Office imported QuantiSheet's {name}")
        return None


if not GUARD["installed"]:
    sys.addaudithook(_hook)
    sys.meta_path.insert(0, _NoAppFinder)
    GUARD["installed"] = True


@pytest.fixture(autouse=True)
def bo_home(tmp_path, monkeypatch):
    home = tmp_path / "bo_home"
    monkeypatch.setenv("QS_BACKOFFICE_HOME", str(home))
    from quantisheet_backoffice import clock, security, settings
    monkeypatch.setattr(security, "PBKDF2_ROUNDS", 2000)
    from quantisheet_backoffice import crypto
    monkeypatch.setattr(crypto, "BACKUP_ROUNDS", 2000)
    settings.reload()
    clock.set_now(datetime(2026, 10, 22, 10, 0, 0))
    GUARD["armed"] = True
    try:
        yield home
    finally:
        GUARD["armed"] = False
        clock.set_now(None)
        settings.reload()


@pytest.fixture
def office(bo_home):
    from .helpers import make_office
    o = make_office(str(bo_home / "data"))
    yield o
    o.close()


@pytest.fixture
def job(office):
    from .helpers import import_stage
    return import_stage(office, 1).job_id


@pytest.fixture
def job3(office):
    from .helpers import import_stage
    import_stage(office, 1)
    return import_stage(office, 2).job_id


@pytest.fixture
def qapp():
    """The app, and after the test every window it opened is closed and
    deleted while the office it shows is still open (Nov 5: pages left
    alive until interpreter exit crashed the run on Windows)."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    before = {id(w) for w in app.topLevelWidgets()}
    yield app
    for w in app.topLevelWidgets():
        if id(w) not in before:
            w.close()
            w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def fake_ollama(bo_home):
    """A fake local model server, chosen in Settings like a real one."""
    from quantisheet_backoffice import localai
    from .ai_fake import FakeOllama
    f = FakeOllama()
    localai.configure(url=f.url, model="llama3.2")
    yield f
    f.close()

