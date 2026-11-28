"""Read-only: which Claude Code, GitHub CLI and git this PC has, and how
Claude Code was installed (for the Nov 24 newsletter setup).
    python tools/claude_code_info.py [update]
'update' runs Claude Code's own updater (claude update) and nothing else.
'install-gh' installs the GitHub CLI from winget (GitHub.cli), only when
Jon asked (Nov 24: "Install the GitHub" CLI)."""
import os
import shutil
import subprocess
import sys

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(cmd, timeout=120):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, creationflags=NOWIN,
                             stdin=subprocess.DEVNULL)
        return (out.stdout + out.stderr).strip()
    except Exception as e:                                # noqa: BLE001
        return f"({type(e).__name__}: {e})"


def main(a):
    claude = shutil.which("claude")
    print("claude on PATH:", claude)
    for c in ("claude", "gh", "git", "winget", "wsl"):
        print(f"{c}: {shutil.which(c)}")
    if claude:
        print("claude --version:", run([claude, "--version"]))
    if shutil.which("gh"):
        print("gh --version:", run(["gh", "--version"]).splitlines()[0:1])
        print("gh auth:", run(["gh", "auth", "status"])[:300])
    if shutil.which("git"):
        print("git --version:", run(["git", "--version"]))
    if shutil.which("winget"):
        print("winget:", run(["winget", "list", "--id", "Anthropic.ClaudeCode",
                              "--accept-source-agreements"], 90)[-400:])
    home = os.path.expanduser("~")
    for p in (os.path.join(home, ".local", "bin", "claude.exe"),
              os.path.join(home, ".claude", "settings.json"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "AnthropicClaude"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                           "Claude")):
        print("exists" if os.path.exists(p) else "missing", p)
    st = os.path.join(home, ".claude", "settings.json")
    if os.path.isfile(st):
        import json
        try:
            d = json.load(open(st, encoding="utf-8"))
            print("settings keys:", sorted(d.keys()))
            print("autoUpdatesChannel:", d.get("autoUpdatesChannel"))
            print("sandbox:", {k: v for k, v in (d.get("sandbox") or {}).items()
                               if k == "autoAllowBashIfSandboxed"})
        except Exception as e:                            # noqa: BLE001
            print("settings unreadable:", e)
    if a[:1] == ["update"] and claude:
        print("claude update:", run([claude, "update"], 300)[-1500:])
        print("claude --version after:", run([claude, "--version"]))


def install_gh():
    if shutil.which("gh"):
        print("gh already installed:", run(["gh", "--version"]))
        return
    print(run(["winget", "install", "--id", "GitHub.cli", "-e", "--source",
               "winget", "--silent", "--accept-package-agreements",
               "--accept-source-agreements"], 600)[-1500:])
    gh = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                      "GitHub CLI", "gh.exe")
    exe = shutil.which("gh") or (gh if os.path.isfile(gh) else None)
    print("gh after:", exe, run([exe, "--version"]) if exe else "")


if __name__ == "__main__":
    if sys.argv[1:2] == ["install-gh"]:
        install_gh()
        sys.exit()
    main(sys.argv[1:])
