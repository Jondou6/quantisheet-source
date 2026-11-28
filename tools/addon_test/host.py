"""QuantiSheet's side of the add-on's direct line, for tools/addon_test:
app/browserhost.py itself, saving into the test's folder and noting what
it would have opened instead of starting the program."""
import importlib.util
import json
import os
import sys

ROOT = os.environ["QS_ROOT"]
WORK = os.environ["QS_WORK"]
GOT = os.path.join(WORK, "got")

# browserhost on its own: the rest of the program (and its PDF library)
# is not needed to receive a file
app = type(sys)("app")
app.__version__ = "test"
app.__path__ = []
sys.modules["app"] = app
spec = importlib.util.spec_from_file_location(
    "app.browserhost", os.path.join(ROOT, "app", "browserhost.py"))
bh = importlib.util.module_from_spec(spec)
bh.__package__ = "app"
spec.loader.exec_module(bh)


def opened(path):
    with open(os.path.join(GOT, "opened.txt"), "a") as f:
        f.write(path + "\n")


rx = bh.Receiver(where=GOT, opener=opened)
_handle = rx.handle


def handle(msg):
    if isinstance(msg, dict) and msg.get("type") == "end" and \
            msg.get("marks"):
        with open(os.path.join(GOT, "marks.json"), "w") as f:
            json.dump(msg["marks"], f)
    return _handle(msg)


rx.handle = handle
if os.path.exists(os.path.join(WORK, "OFF")):       # as if IT turned it off
    rx.handle = lambda msg: {"ok": False, "off": True,
                             "error": "turned off by your IT department"}
sys.exit(bh.serve(sys.stdin.buffer, sys.stdout.buffer, rx))
