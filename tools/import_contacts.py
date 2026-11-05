"""Import a contacts workbook into the Company Directory (kept in your own
data folder, never the program folder): python tools/import_contacts.py
FILE.xlsx"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import subdir  # noqa: E402

rep = subdir.import_xlsx(sys.argv[1].strip('"'))
cs = subdir.load()
print(f"sheet {rep['sheet']}: {rep['rows']} read, {rep['added']} added, "
      f"{rep['updated']} updated, {rep['total']} in the directory")
print(f"with division: {sum(1 for c in cs if c.get('division'))}, "
      f"with email: {sum(1 for c in cs if c.get('email'))}")
print("stored in:", subdir.path())
