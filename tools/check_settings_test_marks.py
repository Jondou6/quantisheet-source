"""Read-only: does the REAL ~/.quantisheet/settings.json hold anything a
test run left (temp-folder paths, made-up names)? Prints key names and the
marker found - never a value (Chief review Q6).
    python tools/check_settings_test_marks.py"""
import datetime
import json
import os

P = os.path.join(os.path.expanduser("~"), ".quantisheet", "settings.json")
MARKS = ("qs_test_home_", "pytest-of", "pytest-", "\\Temp\\", "/tmp/",
         "example.invalid", "example.com", "Test PM", "Example ",
         "Sample ", "test_")


def walk(v, path=""):
    if isinstance(v, dict):
        for k, x in v.items():
            yield from walk(x, f"{path}.{k}" if path else str(k))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from walk(x, f"{path}[{i}]")
    else:
        yield path, v


st = os.stat(P)
print("settings.json modified",
      datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="minutes"),
      f"({st.st_size} bytes)")
with open(P, encoding="utf-8") as f:
    data = json.load(f)
print("top-level keys:", len(data))
hits = 0
for path, v in walk(data):
    t = str(v)
    for m in MARKS:
        if m.lower() in t.lower():
            print(f"  {path}: contains {m!r}")
            hits += 1
            break
print("test markers found:", hits)
