"""Remove the recent-file entries a test run left in the REAL
settings.json (paths inside a pytest Temp folder) - nothing else. Backs the
file up first next to it. Prints counts only (Chief review Q6).
    python tools/clean_settings_test_recent.py"""
import json
import os
import shutil
import time

P = os.path.join(os.path.expanduser("~"), ".quantisheet", "settings.json")


def from_test(v):
    t = str(v).replace("/", "\\").lower()
    return "\\temp\\" in t and ("pytest-of" in t or "qs_test_home_" in t or
                                "\\tmp" in t)


with open(P, encoding="utf-8") as f:
    data = json.load(f)
rec = data.get("recent") or []
bad = [r for r in rec if from_test(r)]
print("recent entries:", len(rec), "from a test run:", len(bad))
if bad:
    bak = P + time.strftime(".bak-%Y%m%d-%H%M")
    shutil.copy2(P, bak)
    print("backup:", bak)
    data["recent"] = [r for r in rec if r not in bad]
    tmp = P + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, P)
    print("removed", len(bad), "- recent now", len(data["recent"]))
