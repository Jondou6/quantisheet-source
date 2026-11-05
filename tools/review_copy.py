"""Test an outside patch on a COPY of this folder, never the live one.

    python tools/review_copy.py setup PATCH.zip [ANCHOR_DIFF]
    python tools/review_copy.py test [pytest args]      # in the copy
    python tools/review_copy.py without [pytest args]   # copy minus module

`setup` copies this folder (code, tests, docs, installer, server, tools,
data - not .venv*, .run, release, private, backups or PDFs at the top) to
%LOCALAPPDATA%\\QuantiSheetReview\\copy (wiped first), unpacks the patch
zip over it (refusing absolute paths and '..'), and applies a unified diff
named host_changes.diff from the patch if there is one. `test` runs pytest
there with this folder's .venv Python; the live folder is only read.
`without` runs the same tests in a second copy with the add-on folder
removed (the host must still pass without it).
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser(
    "~"), "QuantiSheetReview")
COPY = os.path.join(BASE, "copy")
BARE = os.path.join(BASE, "copy_without")
SKIP_DIRS = {".venv", ".venv-pm2", ".run", "release", "private", "trial",
             "trial_output", "__pycache__", ".pytest_cache",
             "sample.pdf.versions", "Retard BOTS"}
KEEP_TOP_EXT = (".py", ".bat", ".spec", ".toml", ".txt", ".md", ".ico",
                ".png", ".ini", ".cfg", ".json")


def _ignore(d, names):
    out = set()
    top = os.path.abspath(d) == ROOT
    for n in names:
        p = os.path.join(d, n)
        if n in SKIP_DIRS or (n.startswith(".") and os.path.isdir(p)):
            out.add(n)
        elif top and os.path.isfile(p) and not n.lower().endswith(
                KEEP_TOP_EXT):
            out.add(n)
        elif top and n.lower().startswith(("review_", "for_claude")):
            out.add(n)
    return out


def _apply_diff(diff_path, root):
    """Apply a small unified diff: each hunk's context must match once."""
    import re
    text = open(diff_path, encoding="utf-8").read()
    files = re.split(r"^--- ", text, flags=re.M)[1:]
    for chunk in files:
        lines = chunk.splitlines()
        target = lines[1][4:].split("\t")[0]
        rel = target.split("/", 1)[1] if "/" in target else target
        path = os.path.join(root, *rel.split("/"))
        src = open(path, encoding="utf-8").read()
        hunks = re.split(r"^@@[^\n]*@@\n?", "\n".join(lines[2:]),
                         flags=re.M)[1:]
        for h in hunks:
            old = [ln[1:] for ln in h.splitlines() if ln[:1] in (" ", "-")]
            new = [ln[1:] for ln in h.splitlines() if ln[:1] in (" ", "+")]
            a, b = "\n".join(old), "\n".join(new)
            if src.count(a) != 1 and src.count(b) == 1:
                print("already applied in", rel)
                continue
            if src.count(a) != 1:
                raise SystemExit(f"diff context not found once in {rel}")
            src = src.replace(a, b)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
        print("patched", rel)


def setup(zip_path):
    zip_path = os.path.abspath(zip_path)
    for d in (COPY, BARE):
        if os.path.isdir(d):
            shutil.rmtree(d)
    shutil.copytree(ROOT, COPY, ignore=_ignore)
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.startswith(("/", "\\")) or ".." in n.replace("\\", "/") \
                    .split("/") or ":" in n:
                raise SystemExit(f"refused entry {n!r}")
        z.extractall(COPY)
    diff = os.path.join(COPY, "host_changes.diff")
    if os.path.exists(diff):
        _apply_diff(diff, COPY)
    print("copy ready:", COPY)


def _pytest(where, args):
    py = os.path.join(ROOT, ".venv", "Scripts" if os.name == "nt" else "bin",
                      "python.exe" if os.name == "nt" else "python")
    import tempfile
    home = tempfile.mkdtemp(prefix="qs-review-home-")
    # a throwaway home: nothing the patch's code does can reach the real
    # settings, ~/.quantisheet, AppData or the price database
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", HOME=home,
               USERPROFILE=home,
               APPDATA=os.path.join(home, "AppData", "Roaming"),
               LOCALAPPDATA=os.path.join(home, "AppData", "Local"),
               QS_BACKOFFICE_HOME=os.path.join(home, "bo"),
               QUANTISHEET_DRAW_PROCESS="0")
    for k in ("APPDATA", "LOCALAPPDATA"):
        os.makedirs(env[k], exist_ok=True)
    cmd = [py, "-m", "pytest", "-p", "no:cacheprovider"] + (args or ["-q"])
    print("$", " ".join(cmd), "(in", where + ", home", home + ")",
          flush=True)
    try:
        p = subprocess.run(cmd, cwd=where, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=840)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    print((p.stdout or "")[-30000:])
    print((p.stderr or "")[-4000:])
    return p.returncode


def without(args, module="quantisheet_backoffice"):
    if not os.path.isdir(BARE):
        shutil.copytree(COPY, BARE)
        shutil.rmtree(os.path.join(BARE, module), ignore_errors=True)
    return _pytest(BARE, args)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] not in ("setup", "test", "without"):
        print(__doc__)
        sys.exit(2)
    if a[0] == "setup":
        setup(a[1])
    elif a[0] == "test":
        sys.exit(_pytest(COPY, a[1:]))
    else:
        sys.exit(without(a[1:]))
