"""python -m quantisheet_claims [--takeoff snap.json] [x.claim.json]

Started by QuantiSheet as a separate process (app/claims_hook.py) or on
its own. A crash here can't take QuantiSheet down.
"""
from __future__ import annotations

import argparse
import sys


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="quantisheet_claims",
                                 description="ClaimIT insurance claim estimating")
    ap.add_argument("--takeoff", help="takeoff snapshot JSON from QuantiSheet")
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--selftest", action="store_true",
                    help="load every module the window needs, then exit")
    ap.add_argument("claim", nargs="?", help="a .claim.json file to open")
    return ap.parse_args(argv)


def build_window(args):
    from .interface import SnapshotError, load_snapshot
    from .ui.workspace import ClaimsWindow
    snap, err = None, ""
    if args.takeoff:
        try:
            snap = load_snapshot(args.takeoff)
        except (OSError, SnapshotError) as e:
            err = f"Takeoff not loaded: {e}"
    win = ClaimsWindow(snapshot=snap)
    if args.claim:
        win.open_path(args.claim)
    # no claim given: the start page (ClaimIT 0.2) - new, open, recent,
    # practice, or start from the takeoff QuantiSheet sent
    if err:
        win.error(err)
    elif snap is not None:
        win.statusBar().showMessage(
            f"Takeoff from {snap.source_file}: {len(snap.items)} item(s), "
            f"{len(snap.rejected)} rejected")
    return win


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.version:
        from . import __version__
        print(__version__)
        return 0
    if args.selftest:              # the build runs this on the frozen exe
        from . import interface                          # noqa: F401
        from .ui import workspace                        # noqa: F401
        return 0
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("ClaimIT")
    win = build_window(args)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
