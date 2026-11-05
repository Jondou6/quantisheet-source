import os, shutil, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import formlib
src = os.path.join(ROOT, ".run", "forms_in", "Action Item List.pdf")
if "Action Item List" not in {e["name"] for e in formlib.entries()}:
    e = formlib.add(src, "Project Management", "Action Item List",
                    "Converted from 2026.05.15_Blank Action Item List.xlsx")
    keep = os.path.join(formlib.folder(), "Project Management", "originals")
    os.makedirs(keep, exist_ok=True)
    shutil.copyfile(os.path.join(ROOT, ".run", "forms_in", "Action Item List.xlsx"),
                    os.path.join(keep, "Action Item List.xlsx"))
    print("added", e)
for e in formlib.entries():
    print(e["category"], "|", e["name"], "|", e["pages"], "pp |", e["fields"], "fields |", e["filled"], "filled")
