"""Entry script for the frozen ClaimIT program (PyInstaller).

PyInstaller runs its entry script as a top-level script, so it can't be
quantisheet_claims/__main__.py itself: that file uses relative imports and
failed with "attempted relative import with no known parent package"
(Jon, Oct 20). This script imports the package normally."""
import sys

from quantisheet_claims.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
