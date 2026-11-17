"""Run the Store update check's PowerShell outside the package and print
what it says (read-only; checks the script itself runs):
python tools/diag_store_ps.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import storeupdate  # noqa: E402

out = storeupdate._run_ps(storeupdate.PS_SCRIPT)
print(repr(out))
print("signature:", storeupdate.signature(out) or "(none)")
print("parse:", storeupdate.parse(out))
