"""Tag every QuantiSheet release in the public source repository, so the
Help > About source link (github.com/<repo>/tree/v<version>) works for each
version (Nov 25 optimization list: "GitHub tag on every release").

    python tools/tag_release.py            list releases and missing tags
    python tools/tag_release.py --create   create the missing tags

It uses the GitHub CLI (gh), signed in as the repository's owner
(`gh auth login` once). Each "QuantiSheet vX corresponding source" commit
on main gets the tag vX; tags that exist are never moved or deleted.
Run it after each tester release (docs/PUBLIC_SOURCE.md step 5)."""
import json
import os
import re
import shutil
import subprocess
import sys

REPO = "Jondou6/quantisheet-source"
MSG = re.compile(r"^QuantiSheet (v\d+\.\d+\.\d+) corresponding source")


def _fresh_path():
    """PATH as Windows has it now (machine + user), not as it was when
    this program's parent started."""
    try:
        import winreg
    except ImportError:
        return None
    parts = []
    for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet"
                       r"\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(root, key) as k:
                parts.append(os.path.expandvars(
                    winreg.QueryValueEx(k, "Path")[0]))
        except OSError:
            pass
    return os.pathsep.join(parts) or None


def gh_exe():
    """gh on PATH, or where winget puts it (a program started before gh
    was installed doesn't have it on PATH yet)."""
    found = shutil.which("gh") or shutil.which("gh", path=_fresh_path())
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    for exe in (os.path.join(os.environ.get("ProgramFiles",
                                            r"C:\Program Files"),
                             "GitHub CLI", "gh.exe"),
                os.path.join(local, "Programs", "GitHub CLI", "gh.exe"),
                os.path.join(local, "Microsoft", "WinGet", "Links",
                             "gh.exe")):
        if os.path.isfile(exe):
            return exe
    raise SystemExit("The GitHub CLI (gh) isn't installed on this PC.")


def gh(*args):
    p = subprocess.run([gh_exe(), "api", *args], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW",
                                             0))
    if p.returncode:
        raise SystemExit("gh: " + (p.stderr or p.stdout).strip()[:300])
    return json.loads(p.stdout or "null")


def releases(pages=5):
    """{version: commit sha} from main, newest commit per version."""
    out = {}
    for page in range(1, pages + 1):
        rows = gh(f"repos/{REPO}/commits?sha=main&per_page=100&page={page}")
        if not rows:
            break
        for c in rows:
            m = MSG.match(c["commit"]["message"])
            if m and m.group(1) not in out:
                out[m.group(1)] = c["sha"]
    return out


def tags():
    names = set()
    for page in range(1, 6):
        rows = gh(f"repos/{REPO}/tags?per_page=100&page={page}")
        if not rows:
            break
        names |= {t["name"] for t in rows}
    return names


def missing(rel, have):
    def key(v):
        return tuple(int(x) for x in v[1:].split("."))
    return sorted((v for v in rel if v not in have), key=key)


def main(argv):
    rel, have = releases(), tags()
    todo = missing(rel, have)
    print(len(rel), "releases on main,", len(have), "tags,",
          len(todo), "missing:", " ".join(todo) or "none")
    if "--create" not in argv:
        if todo:
            print("run with --create to add them")
        return 0
    for v in todo:
        gh(f"repos/{REPO}/git/refs", "-f", f"ref=refs/tags/{v}",
           "-f", f"sha={rel[v]}")
        print("tagged", v, rel[v][:7])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
