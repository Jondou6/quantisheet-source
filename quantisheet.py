"""QuantiSheet launcher (also the entry point for the PyInstaller build).

    quantisheet                 open the desktop app
    quantisheet file.pdf        open the desktop app with that file
    quantisheet <command> ...   command-line tools (quantisheet --help)

Every PDF it opens that still carries job data saved under the program's
old name is converted as it opens (app/oldnames.py).
"""
import multiprocessing
import os
import sys


def _attach_windows_console():
    """The Windows build is a windowed app with no console, so command-line
    output would vanish. Borrow the console of the terminal that ran us."""
    if not (sys.platform.startswith("win") and getattr(sys, "frozen", False)):
        return
    import ctypes
    if ctypes.windll.kernel32.AttachConsole(-1):      # ATTACH_PARENT_PROCESS
        sys.stdout = open("CONOUT$", "w", buffering=1, encoding="utf-8")
        sys.stderr = open("CONOUT$", "w", buffering=1, encoding="utf-8")
        print()                       # start below the shell prompt


def _convert_old_files():
    """Files saved under the old name convert as they open (app/oldnames).
    Never stops the program."""
    try:
        from app import oldnames
        oldnames.install()
    except Exception:                                     # noqa: BLE001
        pass


def main():
    multiprocessing.freeze_support()
    _convert_old_files()
    args = [a for a in sys.argv[1:] if a != "--new-window"]   # File > New
    gui = not args or (len(args) == 1 and args[0].lower().endswith(".pdf")
                       and os.path.exists(args[0]))
    if gui:
        from app.main import run
        return run(sys.argv)
    _attach_windows_console()
    from app.cli import main as cli_main
    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
