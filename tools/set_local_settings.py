"""Put a few values into this PC's QuantiSheet settings from a JSON file
kept outside the repository (Nov 4): e.g. where the private plan sets for
tools/aiken_eval.py live. Only keys ending in _src, _drawings, _spec or
_xlsx are accepted. Prints what it set; the file's values never go in
the source.

    python tools/set_local_settings.py .run/eval_paths.json
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OK = ("_src", "_drawings", "_spec", "_xlsx")


def main(argv):
    from app import settings
    path = argv[0]
    data = json.load(open(os.path.join(ROOT, path), encoding="utf-8"))
    for k, v in data.items():
        if not k.endswith(OK) or not isinstance(v, str):
            print("skipped", k)
            continue
        settings.set(k, v)
        print("set", k)
    src = [k for k in data if k.endswith("_src")]
    for k in src:
        print(k, "folder exists:", os.path.isdir(data[k]))


if __name__ == "__main__":
    main(sys.argv[1:])
