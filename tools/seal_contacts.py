"""Seal this computer's Company Directory into app/data/contacts.sealed for
a tester build: python tools/seal_contacts.py PASSWORD
Prints only how many contacts were sealed."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import safeio, sealed_contacts, subdir               # noqa: E402

pw = sys.argv[1].strip('"') if len(sys.argv) > 1 else ""
contacts = subdir.load()
if not contacts:
    sys.exit("The Company Directory on this computer is empty.")
blob = sealed_contacts.seal(contacts, pw)
safeio.atomic_write(sealed_contacts.FILE, blob)
back = sealed_contacts.unseal(open(sealed_contacts.FILE, "rb").read(), pw)
assert len(back) == len(contacts)
try:
    sealed_contacts.unseal(blob, pw + "x")
    sys.exit("wrong password was accepted?!")
except sealed_contacts.WrongPassword:
    pass
print(f"sealed {len(contacts)} contacts -> app/data/contacts.sealed")
