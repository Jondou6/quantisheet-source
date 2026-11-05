"""BLS PPI escalation from the command line. The code lives in
app/bls_core.py (one source); this runs it:

    python tools/bls.py --help
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.bls_core import *          # noqa: E402,F401,F403
from app.bls_core import main       # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
