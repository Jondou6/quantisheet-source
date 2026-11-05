"""Build the QuantiSheet beta installer (Windows).

    python tools/build_installer.py start    build in the background
    python tools/build_installer.py status   how it's going
    python tools/build_installer.py run      build here and now
    python tools/build_installer.py setup    only redo the setup .exe
    python tools/build_installer.py trial    build the program only, in the
                                             background (no setup .exe)

Steps: checks -> PyInstaller one-folder build -> check the
built program really starts (opens a drawing, runs auto rooms) -> Inno
Setup (installed for this user if missing) -> release\\QuantiSheet-Beta-
Setup-<version>.exe. The program is dist\\QuantiSheet\\QuantiSheet.exe.

The build itself happens in %LOCALAPPDATA%\\QuantiSheetBuild so OneDrive
doesn't sync hundreds of MB of build files; only the finished setup file
lands in release\\.
"""
import glob
import re
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ship_check                                    # noqa: E402
from app import branding                             # noqa: E402
# the PyInstaller folder and program (quantisheet.spec's COLLECT / EXE name)
DIST_NAME = branding.NAME                            # dist\QuantiSheet
BUILD = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser(
    "~"), "QuantiSheetBuild")
RELEASE = os.path.join(ROOT, "release")
GITHUB = os.path.join(RELEASE, "github")        # builds for outside
LOG = os.path.join(ROOT, ".run", "build_installer.log")
STATUS = os.path.join(ROOT, ".run", "build_installer.status")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def status(s):
    with open(STATUS, "w") as f:
        f.write(s)


def sh(cmd, timeout=1800, env=None, check=True):
    log("$", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                       timeout=timeout, env=env, creationflags=NOWIN)
    out = (p.stdout or "") + (p.stderr or "")
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(out[-20000:] + "\n")
    if check and p.returncode != 0:
        raise RuntimeError(f"failed (exit {p.returncode}): {cmd[:3]}\n"
                           + out[-3000:])
    return p.returncode, out


def find_iscc():
    cands = [os.path.join(os.environ.get(v, ""), "Inno Setup 6", "ISCC.exe")
             for v in ("ProgramFiles(x86)", "ProgramFiles")]
    cands.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                              "Inno Setup 6", "ISCC.exe"))
    for c in cands:
        if os.path.isfile(c):
            return c
    return shutil.which("ISCC")



def stamp_tester(app_dir, version):
    """Sign the in-house build as a tester build (Venice review S4): the
    installed program checks this signature, so a public copy can't be
    turned into a tester one by adding or deleting files. Needs the
    license signing key (tools/beta_keys.py)."""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import beta_keys
    from app import betalicense
    if not os.path.exists(beta_keys.PRIV):
        raise RuntimeError("no license signing key (tools/beta_keys.py) - "
                           "can't sign the tester build")
    data = next(os.path.dirname(f) for f in glob.glob(
        os.path.join(app_dir, "**", "app", "data", "beta_pubkey.txt"),
        recursive=True))
    stamp = betalicense.make_tester_stamp(beta_keys._load_priv(), version)
    with open(os.path.join(data, "build.json"), "w", encoding="utf-8") as f:
        json.dump(stamp, f)
    log("   tester build signed")


def public_copy(app_dir):
    """The program for outside the company (GitHub): the same build, minus
    the sealed company contact list, marked 'public' so it always needs a
    license key (docs/RELEASE_CHECKLIST.md). Checked, not trusted."""
    pub = app_dir.rstrip("\\/") + "-public"
    if os.path.isdir(pub):
        shutil.rmtree(pub)
    shutil.copytree(app_dir, pub)
    data = None
    for f in glob.glob(os.path.join(pub, "**", "contacts.sealed"),
                       recursive=True):
        data = os.path.dirname(f)
        os.remove(f)
    for name in ("company_sender.json", "company_dropbox.json"):
        for f in glob.glob(os.path.join(pub, "**", name), recursive=True):
            os.remove(f)                # the company's own mailbox / app
    if data is None:
        found = glob.glob(os.path.join(pub, "**", "app", "data",
                                       "beta_pubkey.txt"), recursive=True)
        if not found:                     # Venice review M4: say so
            shutil.rmtree(pub, ignore_errors=True)
            raise RuntimeError("the public copy has no app\\data folder - "
                               "can't mark it public")
        data = os.path.dirname(found[0])
    with open(os.path.join(data, "build.json"), "w", encoding="utf-8") as f:
        json.dump({"edition": "public"}, f)
    bad = [f for f in glob.glob(os.path.join(pub, "**", "*"), recursive=True)
           if os.path.isfile(f) and (
               os.path.basename(f).lower() in ("contacts.sealed",
                                               "unlock_code.py",
                                               "company_sender.json",
                                               "company_dropbox.json") or
               re.search(r"company_directory|\.vcf$|\.pst$", f.lower()))]
    if bad:
        raise RuntimeError("public build still has private files: " +
                           ", ".join(bad[:5]))
    ship_check.require_clean(pub, "the public build")    # review #21
    ship_check.require_no_local_only(pub, "the public build")
    found = deep_scan(pub)                # Venice: look inside the files too
    if found:
        raise RuntimeError("public build failed the deep scan: " +
                           "; ".join(found[:8]))
    # the windowed exe has no console here, so it answers in a file
    ans = os.path.join(BUILD, "public_version.json")
    if os.path.exists(ans):
        os.remove(ans)
    rc, out = sh([os.path.join(pub, branding.EXE), "version", "--out",
                  ans], timeout=120, check=False)
    try:
        with open(ans, encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        info = {}
    if rc != 0 or info.get("edition") != "public" or \
            info.get("key_required") is not True:
        raise RuntimeError("the public build doesn't report itself as a "
                           f"public build that needs a key: {info} "
                           f"(exit {rc})\n" + out[-800:])
    log(f"   public copy made and checked ({pub}): public, key required")
    return pub


# addresses that may appear in the program's own data (public sites,
# placeholders); anything else in app data stops a public build
EMAIL_OK = ("example.com", "example.org", "example.net", "ada.gov",
            "access-board.gov", "energycodes.gov", "pnnl.gov", "iccsafe.org",
            "github.com", "noreply.github.com", "python.org", "qt.io")
_EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
_TEXT = (".json", ".txt", ".csv", ".md", ".html", ".htm", ".xml", ".ini",
         ".cfg", ".yaml", ".yml", ".py", ".tsv", ".pem", ".key", ".env")


def _scan_bytes(name, b, in_app):
    out = []
    if b"PRIVATE KEY-----" in b:
        out.append(f"{name}: a private key")
    if b'"salt"' in b and b'"token"' in b and name.lower().endswith(".json"):
        out.append(f"{name}: looks like a sealed contact list")
    if in_app:
        doms = {m.group(1).decode("ascii", "replace").lower()
                for m in _EMAIL.finditer(b)}
        doms = {d for d in doms if not any(
            d == ok or d.endswith("." + ok) for ok in EMAIL_OK)}
        if doms:
            # never print the addresses themselves, only how many domains
            out.append(f"{name}: e-mail addresses ({len(doms)} domain(s))")
    return out


def deep_scan(root):
    """Problems found by reading inside the public copy's files: private
    keys, sealed contact blobs, and e-mail addresses in the program's own
    data (zip members included). Returns [] when clean. Prints no
    addresses or contents."""
    import zipfile
    out = []
    for f in glob.glob(os.path.join(root, "**", "*"), recursive=True):
        if not os.path.isfile(f):
            continue
        rel = os.path.relpath(f, root)
        parts = [x.lower() for x in rel.replace("\\", "/").split("/")]
        in_app = "app" in parts[:-1]
        low = f.lower()
        try:
            if os.path.getsize(f) > 60e6:
                continue
            if low.endswith(".zip"):
                with zipfile.ZipFile(f) as z:
                    for n in z.namelist():
                        if n.lower().endswith(_TEXT):
                            out += _scan_bytes(f"{rel}!{n}", z.read(n),
                                               in_app)
                continue
            if low.endswith(_TEXT) or in_app and not low.endswith(
                    (".pyc", ".pdf", ".png", ".ico", ".bmp", ".jpg",
                     ".ttf", ".otf", ".dll", ".pyd")):
                with open(f, "rb") as fh:
                    out += _scan_bytes(rel, fh.read(), in_app)
        except (OSError, zipfile.BadZipFile) as e:
            out.append(f"{rel}: couldn't read ({e.__class__.__name__})")
    return out


def packaged_sources():
    """Paths (relative to ROOT) of the source files the spec and the Inno
    scripts package: the app package (code and data), the top-level assets
    and the extra installer files."""
    out = []
    for d in ("app", "quantisheet_claims"):
        for base, dirs, files in os.walk(os.path.join(ROOT, d)):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            out += [os.path.relpath(os.path.join(base, f), ROOT)
                    for f in files]
    out += [f for f in ("quantisheet.py", "icon.png", "icon.ico",
                        "splash.png") if os.path.exists(os.path.join(ROOT, f))]
    out += ["extras/install_deps.ps1",
            "docs/IT_DEPLOYMENT.md", "docs/Detect-QuantiSheet.ps1"]
    return out


def check_branding():
    """Inno wizard BMPs + splash must be present (v34 Canva branding)."""
    needed = [
        os.path.join(ROOT, "installer", "wizard-side.bmp"),
        os.path.join(ROOT, "installer", "wizard-small.bmp"),
        os.path.join(ROOT, "splash.png"),
    ]
    missing = [p for p in needed if not os.path.isfile(p)]
    if missing:
        raise RuntimeError(
            "branding assets missing (installer\\wizard-*.bmp, splash.png): "
            + ", ".join(os.path.relpath(p, ROOT) for p in missing))
    for p in needed:
        log("  branding:", os.path.relpath(p, ROOT),
            f"({os.path.getsize(p)} bytes)")


def install_inno():
    log("Inno Setup not found - installing it for this user")
    if shutil.which("winget"):
        sh(["winget", "install", "--id", "JRSoftware.InnoSetup", "-e",
            "--silent", "--scope", "user", "--accept-package-agreements",
            "--accept-source-agreements"], check=False)
        if find_iscc():
            return find_iscc()
    import urllib.request
    exe = os.path.join(BUILD, "innosetup.exe")
    urllib.request.urlretrieve("https://jrsoftware.org/download.php/is.exe",
                               exe)
    sh([exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/CURRENTUSER", "/SP-"], check=False)
    return find_iscc()


def smoke(exe):
    out = os.path.join(BUILD, "smoke.json")
    for platform in ("offscreen", None):
        if os.path.exists(out):
            os.remove(out)
        env = dict(os.environ, QUANTISHEET_SMOKE=out)
        env.pop("QT_QPA_PLATFORM", None)
        if platform:
            env["QT_QPA_PLATFORM"] = platform
        sh([exe], timeout=300, env=env, check=False)
        if os.path.exists(out):
            break
    if not os.path.exists(out):
        raise RuntimeError("the built program didn't start (no smoke "
                           "result). See %USERPROFILE%\\.quantisheet\\"
                           "quantisheet.log")
    with open(out) as fh:
        res = json.load(fh)
    for name, c in res["checks"].items():
        log(f"  {'ok ' if c['ok'] else 'BAD'} {name}: "
            f"{c.get('value', c.get('error', ''))}")
    if not res["ok"]:
        raise RuntimeError("the built program started but a check failed")
    return res


def claims_version():
    import re as _re
    with open(os.path.join(ROOT, "quantisheet_claims", "__init__.py"),
              encoding="utf-8") as fh:
        m = _re.search(r'__version__\s*=\s*"([^"]+)"', fh.read())
    return m.group(1) if m else "0.1.0"


def build_claims(iscc, dist, work, pub, skip_program=False):
    """Build ClaimIT.exe (ClaimIT) and ClaimIT-Setup-<v>.exe into
    the release folder (testers only). Returns the setup path, or None."""
    spec = os.path.join(ROOT, "quantisheet_claims.spec")
    iss = os.path.join(ROOT, "installer", "quantisheet_claims.iss")
    if not (os.path.exists(spec) and os.path.exists(iss)):
        log("claims: no spec or installer script - skipped")
        return None
    try:
        v = claims_version()
        src = os.path.join(dist, "ClaimIT")
        if not skip_program or not os.path.exists(src):
            sh([sys.executable, "-m", "PyInstaller", "--clean",
                "--noconfirm", "--distpath", dist, "--workpath",
                os.path.join(work, "claims"), spec], timeout=3600)
        exe = os.path.join(src, "ClaimIT.exe")
        if not os.path.exists(exe):
            raise RuntimeError("ClaimIT.exe was not built")
        ship_check.require_clean(src, "the ClaimIT build")   # review #21
        # the frozen program must start: load every module, then exit
        rc, out = sh([exe, "--selftest"], timeout=120, check=False)
        if rc != 0:
            raise RuntimeError(f"ClaimIT.exe --selftest failed "
                               f"(exit {rc}): {out[-400:]}")
        log("claims: the built program starts (--selftest)")
        try:
            import codesign
            codesign.sign([exe], log)
        except ImportError:
            pass
        base = f"ClaimIT-Setup-{v}"
        sh([iscc, "/Q", f"/DAppVersion={v}", f"/DSourceDir={src}",
            f"/DOutputDir={RELEASE}", iss], timeout=3600)
        out = os.path.join(RELEASE, base + ".exe")
        if not os.path.exists(out):
            raise RuntimeError(f"{base}.exe was not written")
        log(f"claims: {base}.exe built")
        return out
    except Exception as e:                       # noqa: BLE001
        log("claims: BUILD FAILED (QuantiSheet itself is fine):", e)
        return None


def version_stamp_matches(version):
    """Stop the build when installer/version_info.txt (the version Windows
    shows on QuantiSheet.exe) doesn't match app.__version__."""
    p = os.path.join(ROOT, "installer", "version_info.txt")
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    parts = [int(x) for x in version.split(".")[:3]]
    parts += [0] * (4 - len(parts))
    tup = "(" + ", ".join(str(x) for x in parts) + ")"
    want = [f"filevers={tup}", f"prodvers={tup}",
            f"'FileVersion', '{version}'", f"'ProductVersion', '{version}'"]
    bad = [w for w in want if w not in text]
    if bad:
        raise RuntimeError("installer/version_info.txt doesn't match version "
                         f"{version}: {', '.join(bad)} - update it first")


LICENSE_DECISIONS = os.path.join(ROOT, "docs", "LICENSE_DECISIONS.json")


def license_gate(result=None):
    """Reviews 1 + 2 (Nov 4): every release build runs the parts list
    (tools/sbom.py) and stops on an AGPL / GPL / unknown license that
    isn't written down in docs/LICENSE_DECISIONS.json with who decided
    and for which distribution. The SBOM is saved beside the setups."""
    import sbom
    if result is None:
        result = sbom.build(ROOT)
        try:
            sbom.write(os.path.join(ROOT, "release"), result)
        except Exception as e:                            # noqa: BLE001
            log("   SBOM not written:", e)
    try:
        with open(LICENSE_DECISIONS, encoding="utf-8") as fh:
            ok = json.load(fh).get("accepted", {})
    except (OSError, ValueError):
        ok = {}
    blocked = []
    for flag, name, version, lic in result["loud"]:
        d = ok.get(sbom.norm(name))
        if d and d.get("flag") == flag:
            log(f"   license: {name} {version} is {flag} - accepted for "
                f"{d.get('for', '?')} ({d.get('note', '')})")
        else:
            blocked.append(f"{name} {version} ({lic})")
    if blocked:
        raise RuntimeError("License check: " + "; ".join(blocked) +
                           " - not in docs/LICENSE_DECISIONS.json. Decide "
                           "how it may ship and record it there first.")
    return True


def run(skip_program=False, program_only=False):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, "w").close()
    status("running")
    t0 = time.time()
    try:
        from app import __version__
        log("QuantiSheet", __version__, "- building the beta installer")
        version_stamp_matches(__version__)
        os.makedirs(BUILD, exist_ok=True)
        private = [f for f in glob.glob(os.path.join(ROOT, "app", "**", "*"),
                                        recursive=True)
                   if os.path.isfile(f) and (
                       f.lower().endswith((".xlsx", ".xls", ".vcf",
                                           ".pst")) or
                       re.search(r"contact|company_directory|subcontractor",
                                 os.path.basename(f).lower()))]
        # the password-sealed contact list may ship (Jon, Oct 16) - but
        # only if it really is sealed, never a readable copy
        def sealed_ok(f):
            b = os.path.basename(f).lower()
            if b.startswith("sealed_contacts") and \
                    b.endswith((".py", ".pyc")):
                return True
            if b == "contacts.sealed":
                try:
                    with open(f, encoding="utf-8") as fh:
                        d = json.load(fh)
                    return set(d) >= {"salt", "token"} and \
                        "contacts" not in d
                except Exception:
                    return False
            return False
        private = [f for f in private if not sealed_ok(f)]
        if private:
            raise RuntimeError("Private files are in the program folder - "
                               "they would ship in the installer: " +
                               ", ".join(os.path.relpath(f, ROOT)
                                         for f in private[:5]))
        # research briefs, reviews, notes for Claude, private/ and any
        # Xactimate / SageSure / EagleView material never ship (review
        # 0.12.35 #21): check what the spec packages before building...
        ship_check.require_clean(packaged_sources(), "the program folder")
        ship_check.require_no_local_only(os.path.join(ROOT, "app", "data"),
                                         "app/data")
        license_gate()
        if not os.path.exists(os.path.join(ROOT, "app", "data",
                                           "beta_pubkey.txt")):
            raise RuntimeError("no license public key: run "
                               "tools/beta_keys.py init first")
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from app import legal            # the publisher name, below
        log("1/5 checks done (no agreement since 1.0.0)")

        dist, work = os.path.join(BUILD, "dist"), os.path.join(BUILD, "work")
        if not skip_program:
            sh([sys.executable, "-m", "pip", "install", "-q",
                "pyinstaller>=6.3,<7"])
            log("2/5 PyInstaller ready")
            sh([sys.executable, "-m", "PyInstaller", "--clean",
                "--noconfirm", "--distpath", dist, "--workpath", work,
                os.path.join(ROOT, "quantisheet.spec")], timeout=3600)
        app_dir = os.path.join(dist, DIST_NAME)
        exe = os.path.join(app_dir, branding.EXE)
        if not os.path.isfile(exe):
            raise RuntimeError(f"{exe} was not built (quantisheet.spec "
                               f"names the program {branding.EXE})")
        size = sum(os.path.getsize(p) for p in glob.glob(
            os.path.join(app_dir, "**", "*"), recursive=True)
            if os.path.isfile(p))
        log(f"3/5 program built: {exe} ({size / 1e6:.0f} MB)")
        # ...and the built folder itself, before anything is packaged
        ship_check.require_clean(app_dir, "the built program")
        ship_check.require_no_local_only(app_dir, "the built program")

        stamp_tester(app_dir, __version__)
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import codesign                  # Nov 4: off until a cert is set up
        log("   " + codesign.status())
        codesign.sign([exe], log)
        smoke(exe)
        log("4/5 built program starts, opens drawings and finds rooms")
        if program_only:          # a trial build: no setup .exe written
            log(f"trial build done in {(time.time() - t0) / 60:.1f} min")
            status("done (trial, no installer) " + exe)
            return

        iscc = find_iscc() or install_inno()
        if not iscc:
            raise RuntimeError("couldn't install Inno Setup - install it "
                               "from https://jrsoftware.org/isdl.php")
        check_branding()
        os.makedirs(RELEASE, exist_ok=True)
        pub = legal._pub().get("name") or "QuantiSheet"
        made = []
        for src, out_dir, edition in ((app_dir, RELEASE, "tester"),
                                      (public_copy(app_dir), GITHUB,
                                       "public")):
            os.makedirs(out_dir, exist_ok=True)
            for iss, base in (("quantisheet.iss", "QuantiSheet-Beta-Setup"),
                              ("quantisheet_server.iss",
                               "QuantiSheet-Beta-Server-Setup")):
                if edition == "public":
                    base = base.replace("QuantiSheet-Beta", "QuantiSheet-"
                                        "Public-Beta")
                base += f"-{__version__}"
                sh([iscc, "/Q", f"/DAppVersion={__version__}",
                    f"/DAppPublisher={pub}", f"/DSourceDir={src}",
                    f"/DOutputDir={out_dir}", f"/DOutputBase={base}",
                    os.path.join(ROOT, "installer", iss)], timeout=3600)
                made.append(os.path.join(out_dir, base + ".exe"))
        # the MSI packages for IT (0.12.24): the same programs
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import make_msi
        for src, out_dir, base in (
                (app_dir, RELEASE, "QuantiSheet-Beta"),
                (app_dir + "-public", GITHUB, "QuantiSheet-Public-Beta")):
            msi = os.path.join(out_dir, f"{base}-{__version__}.msi")
            make_msi.build(src, msi, __version__, pub)
            info = make_msi.check(msi)
            if info["version"] != make_msi.msi_version(__version__) or \
                    info["files"] < 100:
                raise RuntimeError(f"the MSI looks wrong: {info}")
            made.append(msi)
        # ClaimIT: its own program and its own setup (0.12.29). A ClaimIT
        # failure is logged, never fails QuantiSheet's build.
        claims = build_claims(iscc, dist, work, pub, skip_program)
        if claims:
            made.append(claims)
        codesign.sign(made, log)         # setups and MSIs (no-op unsigned)
        for m in made:
            log(f"   {os.path.relpath(m, ROOT)} "
                f"({os.path.getsize(m) / 1e6:.0f} MB)")
        setup = made[0]
        log(f"5/5 installers: {len(made)} (tester, server and MSI, the "
            "public copies in release\\github, and ClaimIT)")
        # the files beside the installers: SHA256SUMS.txt, the release
        # notes and READ ME FIRST.txt for this version (review 0.13.9)
        import release_files
        rf = release_files.refresh(ROOT, __version__)
        log(f"   release files: {len(rf['sums'])} hash line(s), notes "
            f"{'copied' if rf['notes'] else 'none'}, READ ME FIRST "
            f"{'written' if rf['readme'] else 'not written'}")
        log(f"done in {(time.time() - t0) / 60:.1f} min")
        # the Store package follows every build, so it's never left at an
        # older version (review 2, Nov 4). Prepared only: never signed or
        # submitted here.
        try:
            r = subprocess.run([sys.executable, os.path.join(
                ROOT, "tools", "build_msix.py")], capture_output=True,
                text=True, timeout=1800)
            msix = os.path.join(ROOT, "release", "msix",
                                f"QuantiSheet-{__version__}.msix")
            log("   Store package (prepared, not submitted): " +
                (msix if os.path.isfile(msix) else
                 "NOT made - " + (r.stdout + r.stderr)[-300:]))
        except Exception as e:                            # noqa: BLE001
            log("   Store package not made:", e)
        status("done " + setup)
    except Exception as e:
        log("BUILD FAILED:", e)
        status("failed " + str(e)[:500])
        raise


def start(mode="run"):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    status("starting")
    flags = NOWIN | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([sys.executable, os.path.abspath(__file__), mode],
                     cwd=ROOT, creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, close_fds=True)
    print("build started; check with: build_installer status")


def show_status():
    if os.path.exists(STATUS):
        with open(STATUS) as fh:
            print(fh.read())
    else:
        print("not started")
    if os.path.exists(LOG):
        with open(LOG, encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        print("".join(l for l in lines if l[:2].isdigit())[-4000:])


def claims_only():
    """Rebuild just ClaimIT (its program and setup)."""
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, "w").close()
    status("running (claims)")
    try:
        from app import legal
        iscc = find_iscc() or install_inno()
        out = build_claims(iscc, os.path.join(BUILD, "dist"),
                           os.path.join(BUILD, "work"),
                           legal._pub().get("name") or "QuantiSheet")
        status(("done " + out) if out else "failed (claims) - see the log")
    except Exception as e:                              # noqa: BLE001
        log("CLAIMS BUILD FAILED:", e)
        status("failed " + str(e)[:500])
        raise


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"start": start, "run": run, "status": show_status,
     "setup": lambda: run(skip_program=True),
     # trial: build and check the program only (release\ untouched)
     "trial": lambda: start("trial-run"),
     "trial-run": lambda: run(program_only=True),
     "claims": lambda: start("claims-run"), "claims-run": claims_only}[cmd]()
