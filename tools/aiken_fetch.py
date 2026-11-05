"""Copy the last Aiken scoring run's output (QuantiSheetWork\\aiken\\out)
into this folder's .work\\aiken_out so it can be read remotely. Results
only (CSV/TXT/JSON); the drawings copies are not touched."""
import os
import shutil

src = os.path.join(os.environ.get("LOCALAPPDATA", ""), "QuantiSheetWork",
                   "aiken", "out")
dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   ".work", "aiken_out")
os.makedirs(dst, exist_ok=True)
n = 0
for f in os.listdir(src):
    if f.lower().endswith((".csv", ".txt", ".json", ".xlsx")):
        shutil.copy2(os.path.join(src, f), os.path.join(dst, f))
        n += 1
print(n, "files ->", dst)
