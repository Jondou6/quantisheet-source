"""python -m quantisheet_backoffice [--snapshot FILE] [--data FOLDER]
                                    [--version] [--selftest]

Started by QuantiSheet through app/backoffice_hook.py as its own process.
--crash-for-test makes it fail on purpose (brief test 1.3): it writes a
crash note to its own data folder and exits with code 3, touching nothing
it was handed."""
import argparse
import os
import sys
import tempfile
import traceback

from . import APP_NAME, __version__

CRASH_EXIT = 3


def selftest() -> int:
    """Quick no-window check of the engine: a balanced entry posts, an
    unbalanced one is refused, the audit chain verifies."""
    from . import ledger, security
    from .office import Office
    folder = tempfile.mkdtemp(prefix="qsbo-selftest-")
    o = Office(folder)
    security.PBKDF2_ROUNDS = min(security.PBKDF2_ROUNDS, 2000)
    security.add_user(o.db, "Self Test", "selftest@local", "Admin",
                      "self test pw 1")
    o.act_as("selftest@local")
    ledger.post(o, "2026-01-02", [{"account": "1000", "debit": 100},
                                  {"account": "3000", "credit": 100}],
                "selftest", 1)
    try:
        ledger.post(o, "2026-01-02", [{"account": "1000", "debit": 101},
                                      {"account": "3000", "credit": 100}],
                    "selftest", 2)
        return 1
    except ledger.LedgerError:
        pass
    tb = ledger.trial_balance(o)
    ok = tb["debits"] == tb["credits"] == 100 and \
        security.verify_chain(o.db)["ok"]
    o.close()
    print("selftest ok" if ok else "selftest FAILED")
    return 0 if ok else 1


def crash_note(exc_text: str) -> str:
    from . import settings
    try:
        folder = settings.home()
    except Exception:                                    # noqa: BLE001
        folder = tempfile.gettempdir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "crash.log")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(exc_text + "\n")
    return path


def main(argv=None) -> int:
    ap_ = argparse.ArgumentParser(prog="QuantiSheetBackOffice",
                                  description=APP_NAME)
    ap_.add_argument("--snapshot", help="QuantiSheet snapshot JSON to import")
    ap_.add_argument("--data", help="data folder (default: per-user folder)")
    ap_.add_argument("--version", action="store_true")
    ap_.add_argument("--selftest", action="store_true")
    ap_.add_argument("--crash-for-test", action="store_true",
                     help=argparse.SUPPRESS)
    args = ap_.parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0
    if args.selftest:
        return selftest()
    if args.data:
        os.environ["QS_BACKOFFICE_HOME"] = args.data
    try:
        if args.crash_for_test:
            raise RuntimeError("Back Office crash test (on purpose)")
        return run_gui(args)
    except Exception:                                     # noqa: BLE001
        crash_note(traceback.format_exc())
        return CRASH_EXIT


def open_or_restore_key(make, ask=None):
    """Open the company. If its payroll key isn't on this Windows login
    (QS-025), say so and offer the .qskey key backup - never a new key.
    `ask(message)` -> (path, password) or None (tests pass one)."""
    from .r111 import paykeys
    while True:
        try:
            return make()
        except paykeys.PayKeyError as e:
            if ask is None:
                ask = _ask_key_backup
            got = ask(str(e))
            if not got:
                return None
            path, pw = got
            from . import settings
            try:
                paykeys.restore_file(settings.data_folder(), path, pw)
            except paykeys.PayKeyError as e2:
                if ask is _ask_key_backup:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(None, APP_NAME, str(e2))
                else:
                    raise


def _ask_key_backup(message):
    from PySide6.QtWidgets import (QFileDialog, QInputDialog, QLineEdit,
                                   QMessageBox)
    box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME, message)
    pick = box.addButton("Restore From Key Backup…",
                         QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is not pick:
        return None
    path, _ = QFileDialog.getOpenFileName(None, "Payroll key backup", "",
                                          "Payroll key backup (*.qskey)")
    if not path:
        return None
    pw, ok = QInputDialog.getText(None, "Payroll key backup",
                                  "Key backup password:",
                                  QLineEdit.EchoMode.Password)
    return (path, pw) if ok else None


def ask_key_backup(parent, office, page=None, ask=None):
    """At every start until the payroll key in use has a verified backup:
    ask for one (Admin / Settings users). Returns True when one was made."""
    from .r111 import paykeys
    try:
        if not office.user or not paykeys.needs_backup(office):
            return False
        if not office.can("settings.edit"):
            return False
    except Exception:                                     # noqa: BLE001
        return False
    if ask is None:
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME,
                          paykeys.NEEDS_BACKUP, parent=parent)
        now = box.addButton("Back Up Payroll Key…",
                            QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Remind Me Next Time", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(now)
        box.exec()
        go = box.clickedButton() is now
    else:
        go = ask(paykeys.NEEDS_BACKUP)
    if not go:
        return False
    if page is None:
        from .r111.ui import SecurityPage
        page = SecurityPage(office)
    return bool(page.backup())


def run_gui(args) -> int:
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
    from .office import Office
    from .ui.main_window import BackOfficeWindow, SignInDialog
    app = QApplication.instance() or QApplication(sys.argv[:1])
    office = open_or_restore_key(Office)
    if office is None:
        return 0
    if office.db.scalar("SELECT COUNT(*) FROM users") == 0:
        from .ui.setup import FirstRunDialog
        if FirstRunDialog(office).exec() != QDialog.DialogCode.Accepted:
            return 0
    elif SignInDialog(office).exec() != QDialog.DialogCode.Accepted:
        return 0
    win = BackOfficeWindow(office)
    QTimer_ = __import__("PySide6.QtCore", fromlist=["QTimer"]).QTimer
    QTimer_.singleShot(600, lambda: ask_key_backup(win, office))
    if office.on_share:
        QMessageBox.warning(
            win, APP_NAME, "The company file is on a network drive.\n\n"
            "Payroll and HR records are safer on this PC, with an encrypted "
            "backup (File > Back Up). Anyone with access to that drive's "
            "folder can copy the file.")
    if args.snapshot:
        try:
            import_handoff(win, args.snapshot)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(win, APP_NAME, f"Snapshot not imported: {e}")
    win.show()
    return app.exec()


def import_handoff(win, path):
    """Import QuantiSheet's snapshot, then delete it from the temp folder
    (even if the import failed: it holds job data)."""
    from . import handoff
    try:
        return win.import_snapshot(path)
    finally:
        handoff.discard(path)


if __name__ == "__main__":
    sys.exit(main())
