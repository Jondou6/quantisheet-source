"""Open the trial build for screenshots without touching the real
settings (Nov 6): a throwaway home folder with the theme preset.

    python tools/show_build.py [dark|light]

The program opens on the desktop and keeps running after this returns;
close it when done. Nothing in ~/.quantisheet is read or written."""
import glob
import json
import os
import subprocess
import sys
import tempfile


def main(theme="dark"):
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                        "QuantiSheetBuild", "dist")
    exes = [p for p in glob.glob(os.path.join(base, "*", "*.exe"))
            if os.path.basename(p).lower().startswith("quantisheet")]
    if not exes:
        print("no trial build found in", base)
        return 1
    exe = sorted(exes, key=os.path.getmtime)[-1]
    home = tempfile.mkdtemp(prefix="qs_shots_")
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    for k in ("USERPROFILE", "HOME"):
        env[k] = home
    for k in ("APPDATA", "LOCALAPPDATA"):
        env[k] = os.path.join(home, k.lower())
        os.makedirs(env[k], exist_ok=True)
    qs = os.path.join(home, ".quantisheet")
    os.makedirs(qs, exist_ok=True)
    with open(os.path.join(qs, "settings.json"), "w") as fh:
        json.dump({"theme": theme}, fh)
    subprocess.Popen([exe], env=env, cwd=os.path.dirname(exe),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    print("started", exe, "home", home)
    return 0


if __name__ == "__main__":
    sys.exit(main(*(sys.argv[1:2] or ["dark"])))
