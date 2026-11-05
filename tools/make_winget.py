"""winget manifests for a GitHub release (0.12.21).

    python tools/make_winget.py --repo OWNER/REPO [--version 0.12.21]
                                [--out release/github/winget]

Reads release/github/SHA256SUMS.txt (written by tools/zip_release.py) and
writes the three manifest files winget-pkgs expects for the public
setups - the version, installer and default-locale files - with the
installer URLs the GitHub release will have
(https://github.com/OWNER/REPO/releases/download/vX.Y.Z/<file>).

Nothing is uploaded. An IT department can also point a private winget
source (or `winget install --manifest <folder>`) at these files.
"""
import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# the winget package id (winget upgrades a package by its id)
PACKAGE = "QuantiSheet.QuantiSheet"
SCHEMA = "1.6.0"
# the Inno Setup uninstall key names, so winget tells the two apart
STANDALONE_ID = "{375F90B3-3B41-4FE9-B790-B29C6D30C75E}_is1"
SERVER_ID = "{6A0E2C4B-9F31-4D2B-8C55-3B1D2E7F9A40}_is1"
_REPO = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


def read_sums(path):
    """{file name: SHA-256} from a SHA256SUMS.txt ("<hash>  <name>")."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([0-9A-Fa-f]{64})\s+\*?(.+?)\s*$", line)
            if m:
                out[m.group(2)] = m.group(1).upper()
    return out


def manifests(version, repo, sums):
    """{file name: YAML text} for the three manifest files."""
    if not _REPO.match(repo or "") or \
            (repo or "").split("/")[1] in (".", ".."):
        raise ValueError("--repo must look like OWNER/REPO")
    if not re.match(r"^\d+\.\d+\.\d+$", version or ""):
        raise ValueError("version must look like 0.12.21")
    user = f"QuantiSheet-Public-Beta-Setup-{version}.exe"
    server = f"QuantiSheet-Public-Beta-Server-Setup-{version}.exe"
    missing = [n for n in (user, server) if n not in sums]
    if missing:
        raise ValueError("not in SHA256SUMS.txt: " + ", ".join(missing))
    base = f"https://github.com/{repo}/releases/download/v{version}/"
    head = (f"# yaml-language-server: $schema=https://aka.ms/winget-manifest"
            f".{{kind}}.{SCHEMA}.schema.json\n")
    common = (f"PackageIdentifier: {PACKAGE}\nPackageVersion: {version}\n")
    inst = (head.format(kind="installer") + common +
            "InstallerType: inno\n"
            "MinimumOSVersion: 10.0.14393.0\n"
            "Installers:\n"
            "  - Architecture: x64\n"
            "    Scope: user\n"
            f"    ProductCode: '{STANDALONE_ID}'\n"
            f"    InstallerUrl: {base}{user}\n"
            f"    InstallerSha256: {sums[user]}\n"
            "  - Architecture: x64\n"
            "    Scope: machine\n"
            f"    ProductCode: '{SERVER_ID}'\n"
            f"    InstallerUrl: {base}{server}\n"
            f"    InstallerSha256: {sums[server]}\n"
            "ManifestType: installer\n"
            f"ManifestVersion: {SCHEMA}\n")
    loc = (head.format(kind="defaultLocale") + common +
           "PackageLocale: en-US\n"
           "Publisher: QuantiSheet\n"
           "PackageName: QuantiSheet (Beta)\n"
           "License: Proprietary\n"
           "ShortDescription: PDF program for construction - drawing sets, "
           "markups, takeoff, estimating and a starter-set generator.\n"
           f"PackageUrl: https://github.com/{repo}\n"
           f"ReleaseNotesUrl: https://github.com/{repo}/releases/tag/"
           f"v{version}\n"
           "ManifestType: defaultLocale\n"
           f"ManifestVersion: {SCHEMA}\n")
    ver = (head.format(kind="version") + common +
           "DefaultLocale: en-US\n"
           "ManifestType: version\n"
           f"ManifestVersion: {SCHEMA}\n")
    return {f"{PACKAGE}.installer.yaml": inst,
            f"{PACKAGE}.locale.en-US.yaml": loc,
            f"{PACKAGE}.yaml": ver}


def main(argv=None):
    from app import __version__
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, help="OWNER/REPO on GitHub")
    ap.add_argument("--version", default=__version__)
    ap.add_argument("--sums", default=os.path.join(ROOT, "release", "github",
                                                   "SHA256SUMS.txt"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    out = a.out or os.path.join(ROOT, "release", "github", "winget",
                                a.version)
    files = manifests(a.version, a.repo, read_sums(a.sums))
    os.makedirs(out, exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(out, name), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(text)
    print("winget manifests:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
