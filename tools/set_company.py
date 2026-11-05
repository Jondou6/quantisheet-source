"""Nov 3 (Jon): save his company for the splash and proposals - only the
name and logo, and only fields that are empty now.

    python tools/set_company.py "NAME" "LOGO PATH"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import proposal                                     # noqa: E402

name, logo = [a.strip('"') for a in sys.argv[1:3]]
c = proposal.company()
if not c.get("name"):
    c["name"] = name
if not c.get("logo") and os.path.isfile(logo):
    c["logo"] = logo
proposal.save_company(c)
print("company now:", repr(proposal.company()["name"]), "| logo:",
      proposal.company()["logo"])
