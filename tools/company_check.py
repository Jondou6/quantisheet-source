"""Nov 3: is a company saved on this computer for the splash (name, and
whether a logo file is set and exists)? Read only."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import main                                         # noqa: E402

name, logo = main.splash_company()
from app import settings                                     # noqa: E402
raw = (settings.get("company") or {}).get("logo", "")
print("company name:", repr(name))
print("logo set:", bool(raw), "| exists:", bool(logo), "|", raw)
