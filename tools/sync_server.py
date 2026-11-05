"""Copy the relay code the server folder needs from the app (one source).

app/collab/hub.py and app/collab/relaycore.py are the files to edit. The
server folder deploys on its own (Docker builds from server/), so it holds
copies; run this before deploying, and the test suite fails if a copy
drifts:

    python tools/sync_server.py           # update server/ copies
    python tools/sync_server.py --check   # exit 1 if any copy differs
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ("hub.py", "relaycore.py")


def _pairs():
    for name in FILES:
        yield (os.path.join(ROOT, "app", "collab", name),
               os.path.join(ROOT, "server", name))


def _same(a, b):
    if not os.path.exists(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() == fb.read()


def main(argv):
    check = "--check" in argv
    stale = [dst for src, dst in _pairs() if not _same(src, dst)]
    if check:
        for d in stale:
            print("out of date:", os.path.relpath(d, ROOT))
        return 1 if stale else 0
    for src, dst in _pairs():
        if dst in stale:
            shutil.copyfile(src, dst)
            print("updated", os.path.relpath(dst, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
