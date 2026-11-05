"""Update check for the TEAM copy only (in-house tester builds).

The Microsoft Store copy NEVER checks for updates itself: the Store
updates it (Store policy). The public build doesn't check either. Only an
installed (frozen) tester build, outside any MSIX package, does - see
eligible().

What it does, at most once a day (and when the person picks Help > Check
for Updates Now):
  1. One plain HTTPS GET of a small JSON manifest (MANIFEST_URL). No query
     string, no cookies, no IDs, no version number, no user data; the
     User-Agent is just "QuantiSheet". (The server still sees the PC's IP
     address, as with any web request - the privacy page says so.)
  2. The manifest must carry a valid Ed25519 signature from the build PC
     (app/data/update_pubkey.txt). No key, or a bad signature: nothing is
     offered (fails closed).
  3. If its version is newer than this copy and not skipped, the window
     shows a notice: Update now / Later / Skip this version.
  4. Update now: the installer is downloaded (only from DOWNLOAD_HOSTS,
     HTTPS only), its size and SHA-256 are checked, and a mismatch
     deletes it. QuantiSheet closes (unsaved work is asked about), the
     hash is checked AGAIN, and the setup installs with a progress bar and
     no questions, then starts QuantiSheet again (QUIET_SWITCHES). It
     never runs without the person clicking Update now.

Turn it off: Help > "Check for Updates Automatically" (setting
"update_check_enabled"), or IT: policy DisableUpdateCheck or OfflineMode.
Offline / server down / bad manifest: nothing is shown (logged at debug).

Nothing here imports Qt; the window part is updatecheck_ui.py."""
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# ---- where -----------------------------------------------------------------
# Hosting: Cloudflare R2 (Pages caps files at 25 MiB; the installer is
# ~121 MB). ONE value: the public R2 base URL plus an unguessable folder.
# The signed version.json and the installer both live under it.
# Bucket quantisheet-updates (set up Nov 1 2026, public r2.dev address).
UPDATE_BASE = "https://pub-1121abaa7290424187564108985e68a0.r2.dev/1ff3f159332530fe277b9b0f"
UPDATE_HOST = urlparse(UPDATE_BASE).hostname
MANIFEST_URL = UPDATE_BASE.rstrip("/") + "/team/version.json"
MANIFEST_HOSTS = frozenset({UPDATE_HOST})
DOWNLOAD_HOSTS = frozenset({UPDATE_HOST})

CHANNEL = "team"
SIG_CONTEXT = b"quantisheet-update-manifest|v1|"
PUBKEY_FILE = "update_pubkey.txt"
USER_AGENT = "QuantiSheet"
INTERVAL = 24 * 3600                  # at most one automatic check a day
TIMEOUT = 10                          # seconds, manifest
DOWNLOAD_TIMEOUT = 60                 # seconds per read, installer
MAX_MANIFEST = 64 * 1024              # bytes
MAX_INSTALLER = 1024 * 1024 * 1024    # bytes
MAX_NOTES = 4000                      # characters

# settings.json keys
S_ENABLED = "update_check_enabled"    # default True (team copy only)
S_LAST = "update_last_check"          # epoch seconds of the last attempt
S_SKIP = "update_skip_version"        # "1.0.3": don't offer this one
S_WAITING = "update_waiting"          # {"version", "notes"} offered, not in
S_SEEN = "update_seen_version"        # the version that last ran


class UpdateError(Exception):
    """Anything wrong with the manifest or the download."""


class HashMismatch(UpdateError):
    """The downloaded file isn't the one the manifest names."""


# ---- versions ---------------------------------------------------------------
_VER = re.compile(r"^\d{1,6}(\.\d{1,6}){0,3}$")


def parse_version(text):
    """"1.0.12" -> (1, 0, 12, 0). Anything else (letters, "1..2", "",
    None, five parts) -> None, and None is never newer."""
    if not isinstance(text, str) or not _VER.match(text.strip()):
        return None
    parts = [int(p) for p in text.strip().split(".")]
    return tuple(parts + [0] * (4 - len(parts)))


def is_newer(remote, local):
    r, l_ = parse_version(remote), parse_version(local)
    return r is not None and l_ is not None and r > l_


def current_version():
    from . import __version__
    return __version__


# ---- who checks -------------------------------------------------------------
def _frozen():
    return bool(getattr(sys, "frozen", False))


def _in_package():
    """True when Windows says this process runs from an MSIX package (the
    Store copy), by either check this program already has."""
    try:
        from . import packaged
        if packaged.is_packaged():
            return True
    except Exception:                                     # noqa: BLE001
        return True                                       # unsure: no check
    try:
        from . import betalicense
        if betalicense.store_package_name():
            return True
        if betalicense._package_from_path(sys.executable):
            return True
    except Exception:                                     # noqa: BLE001
        return True
    return False


def team_build():
    """The installed team (tester) copy, and nothing else: frozen, edition
    "tester" (signed build stamp + sealed company list), and NOT inside an
    MSIX package. A source run, the public build and the Store copy are
    all False. Any doubt -> False."""
    try:
        from . import betalicense
        if not _frozen():
            return False
        if _in_package():
            return False
        if betalicense.is_store():
            return False
        return betalicense.edition() == "tester"
    except Exception:                                     # noqa: BLE001
        return False


def allowed_by_it():
    try:
        from . import policy
        return policy.allowed("update")
    except Exception:                                     # noqa: BLE001
        return False


def enabled():
    from . import settings
    return settings.get(S_ENABLED, True) is not False


def set_enabled(on):
    from . import settings
    settings.set(S_ENABLED, bool(on))


def eligible(manual=False):
    """(ok, reason). manual=True is Help > Check for Updates Now: the
    person's own setting doesn't stop it, the build and IT still do."""
    if not team_build():
        return False, "not the team copy"
    if not allowed_by_it():
        return False, "turned off by IT"
    if not manual and not enabled():
        return False, "turned off in settings"
    return True, ""


def due(now=None):
    from . import settings
    now = time.time() if now is None else now
    try:
        last = float(settings.get(S_LAST) or 0)
    except (TypeError, ValueError):
        last = 0.0
    # a clock set back (last in the future) counts as due
    return last <= 0 or last > now or now - last >= INTERVAL


# ---- network ----------------------------------------------------------------
def _host_ok(url, hosts):
    try:
        u = urlparse(url)
    except ValueError:
        return False
    return (u.scheme == "https" and (u.hostname or "").lower() in hosts
            and u.username is None and u.password is None
            and u.port in (None, 443))


class _SafeRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to HTTPS on an allowed host."""

    def __init__(self, hosts):
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _host_ok(newurl, self.hosts):
            raise UpdateError(f"redirect to a host not allowed: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, hosts, timeout):
    if not _host_ok(url, hosts):
        raise UpdateError(f"not an allowed HTTPS address: {url}")
    from . import policy
    policy.check("update", url)
    # only these headers: nothing about the PC, the person or the copy
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "*/*",
        "Cache-Control": "no-cache"})
    opener = urllib.request.build_opener(_SafeRedirects(hosts))
    return opener.open(req, timeout=timeout)


def fetch_manifest(url=None):
    """The manifest's bytes. Raises OSError/URLError offline, UpdateError
    on anything odd."""
    with _open(url or MANIFEST_URL, MANIFEST_HOSTS, TIMEOUT) as r:
        data = r.read(MAX_MANIFEST + 1)
    if len(data) > MAX_MANIFEST:
        raise UpdateError("manifest too large")
    return data


# ---- manifest ---------------------------------------------------------------
def _pubkey_text():
    from . import betalicense
    try:
        with open(os.path.join(betalicense._data_dir(), PUBKEY_FILE),
                  encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def signed_bytes(manifest):
    """Exactly what the build PC signs (tools/make_update_manifest.py)."""
    return SIG_CONTEXT + json.dumps(
        manifest, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True).encode("ascii")


def parse_manifest(data, pubkey_text=None):
    """The checked manifest dict, or raises UpdateError. Fails closed:
    no public key in this copy -> nothing is ever offered."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PublicKey
    from .betalicense import _b64d
    pub = _pubkey_text() if pubkey_text is None else pubkey_text
    if not pub:
        raise UpdateError("no update key in this copy")
    try:
        outer = json.loads(data.decode("utf-8"))
        m, sig = outer["manifest"], outer["sig"]
        if not isinstance(m, dict) or not isinstance(sig, str):
            raise ValueError
    except Exception:                                     # noqa: BLE001
        raise UpdateError("manifest is not valid JSON") from None
    try:
        Ed25519PublicKey.from_public_bytes(_b64d(pub)).verify(
            _b64d(sig), signed_bytes(m))
    except InvalidSignature:
        raise UpdateError("manifest signature is wrong") from None
    except Exception:                                     # noqa: BLE001
        raise UpdateError("manifest signature unreadable") from None
    if m.get("channel") != CHANNEL:
        raise UpdateError("manifest is for another channel")
    if parse_version(m.get("version")) is None:
        raise UpdateError("manifest version unreadable")
    if not isinstance(m.get("url"), str) or \
            not _host_ok(m["url"], DOWNLOAD_HOSTS):
        raise UpdateError("download address not allowed")
    sha = m.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
        raise UpdateError("sha256 missing or malformed")
    size = m.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or \
            not 0 < size <= MAX_INSTALLER:
        raise UpdateError("size missing or out of range")
    notes = m.get("notes", "")
    if not isinstance(notes, str):
        raise UpdateError("notes must be text")
    signer = m.get("signer", "")              # code-signing thumbprint
    if not isinstance(signer, str) or (signer and not re.fullmatch(
            r"[0-9A-Fa-f]{40}", signer)):
        raise UpdateError("signer thumbprint malformed")
    return {"version": m["version"].strip(), "url": m["url"],
            "sha256": sha.lower(), "size": size,
            "notes": notes[:MAX_NOTES], "published": str(
                m.get("published", ""))[:40], "signer": signer.upper()}


# ---- the check --------------------------------------------------------------
def check(manual=False, now=None, fetch=None, pubkey_text=None,
          local_version=None):
    """Never raises. Returns (status, info):
        "ineligible"  not the team copy / IT / setting (info: reason)
        "not_due"     checked within the last day
        "offline"     no connection, timeout, server error (silent)
        "error"       a manifest that fails a check (silent; logged)
        "current"     nothing newer
        "skipped"     newer, but the person chose Skip this version
        "available"   info = the manifest dict
    manual=True: ignores the once-a-day limit and Skip this version."""
    from . import settings
    try:
        ok, why = eligible(manual)
        if not ok:
            return "ineligible", why
        now = time.time() if now is None else now
        if not manual and not due(now):
            return "not_due", None
        settings.set(S_LAST, now)           # once a day, success or not
        try:
            raw = (fetch or fetch_manifest)()
        except UpdateError as e:
            log.info("update check: %s", e)
            return "error", str(e)
        except (OSError, urllib.error.URLError, ValueError) as e:
            log.debug("update check offline: %s", e)
            return "offline", None
        try:
            m = parse_manifest(raw, pubkey_text)
        except UpdateError as e:
            log.info("update check: %s", e)
            return "error", str(e)
        local = local_version or current_version()
        if not is_newer(m["version"], local):
            return "current", m
        if not manual and settings.get(S_SKIP) == m["version"]:
            return "skipped", m
        return "available", m
    except Exception as e:                                # noqa: BLE001
        log.debug("update check failed", exc_info=True)
        return "error", str(e)


def skip(version):
    from . import settings
    settings.set(S_SKIP, str(version))
    w = settings.get(S_WAITING)
    if isinstance(w, dict) and w.get("version") == str(version):
        settings.set(S_WAITING, None)


# ---- reminders and What's New (Nov 2) ----------------------------------------
def remember(info):
    """A newer version was offered: kept so the status bar and the Start
    page can say so until it is installed (or skipped), and so its notes
    can be shown once after the update. Only the version and the notes
    are kept - the download itself always comes from a fresh, signed
    check."""
    from . import settings
    try:
        v = str(info["version"])
    except (KeyError, TypeError):
        return
    if parse_version(v) is None:
        return
    notes = str(info.get("notes") or "")[:MAX_NOTES]
    settings.set(S_WAITING, {"version": v, "notes": notes})


def forget():
    from . import settings
    settings.set(S_WAITING, None)


def waiting(local_version=None):
    """The newer version offered and not installed yet (not skipped):
    {"version", "notes"}, or None."""
    from . import settings
    w = settings.get(S_WAITING)
    if not isinstance(w, dict) or parse_version(str(w.get("version"))) \
            is None:
        return None
    local = local_version or current_version()
    if not is_newer(w["version"], local):
        return None
    if settings.get(S_SKIP) == w["version"]:
        return None
    return {"version": w["version"], "notes": str(w.get("notes") or "")}


NOTES_FILE = "whats_new.json"


def bundled_notes(version):
    """The notes for `version` that ship with the program
    (app/data/whats_new.json), or ''."""
    import json
    want = parse_version(str(version))
    if want is None:
        return ""
    try:
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", NOTES_FILE)
        with open(here, "r", encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return ""
    for k, v in (d or {}).items():
        if parse_version(str(k)) == want:
            return str(v or "")[:MAX_NOTES]
    return ""


def _used_before():
    """This PC ran QuantiSheet before (it has recent files)."""
    try:
        from . import settings
        return bool(settings.recent(1))
    except Exception:                                     # noqa: BLE001
        return False


def whats_new(local_version=None, used_before=None):
    """Once, on the first start after an update: {"version", "notes"} for
    the version now running - the notes it was offered with, else the
    notes shipped with it (the Store copy, or a first update to a version
    that has this) - else None. Records the running version either way."""
    from . import settings
    local = local_version or current_version()
    seen = settings.get(S_SEEN)
    out = None
    w = settings.get(S_WAITING)
    if seen and seen != local and isinstance(w, dict) and \
            parse_version(str(w.get("version"))) == parse_version(local) \
            and str(w.get("notes") or "").strip():
        out = {"version": local, "notes": str(w.get("notes") or "")}
    if out is None and seen != local:
        prior = bool(seen) or (_used_before() if used_before is None
                               else used_before)
        notes = bundled_notes(local)
        if prior and notes:
            out = {"version": local, "notes": notes}
    if isinstance(w, dict) and parse_version(str(w.get("version"))) and \
            not is_newer(w["version"], local):
        settings.set(S_WAITING, None)          # installed (or older)
    if seen != local:
        settings.set(S_SEEN, local)
    return out


# ---- download and install ---------------------------------------------------
def download_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), ".cache")
    return os.path.join(base, "QuantiSheet", "updates")


def installer_path(info, folder=None):
    v = info["version"]
    if parse_version(v) is None:
        raise UpdateError("bad version")
    return os.path.join(folder or download_dir(),
                        f"QuantiSheet-Team-Setup-{v}.exe")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path, info):
    """True only if the file has exactly the manifest's size and SHA-256."""
    try:
        if os.path.getsize(path) != info["size"]:
            return False
        return hmac.compare_digest(sha256_file(path), info["sha256"].lower())
    except OSError:
        return False


def download(info, folder=None, opener=None, progress=None, cancelled=None):
    """Download the installer to download_dir(), checking size and SHA-256.
    Returns the path. A mismatch deletes the file and raises HashMismatch.
    progress(done, total) is called now and then; cancelled() -> True
    stops it (UpdateError)."""
    folder = folder or download_dir()
    os.makedirs(folder, exist_ok=True)
    final = installer_path(info, folder)
    part = final + ".part"
    h = hashlib.sha256()
    done = 0
    try:
        with (opener or (lambda u: _open(u, DOWNLOAD_HOSTS,
                                         DOWNLOAD_TIMEOUT)))(
                info["url"]) as r, open(part, "wb") as out:
            while True:
                if cancelled and cancelled():
                    raise UpdateError("download cancelled")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > info["size"]:
                    raise HashMismatch("download is larger than expected")
                h.update(chunk)
                out.write(chunk)
                if progress:
                    progress(done, info["size"])
        if done != info["size"] or not hmac.compare_digest(
                h.hexdigest(), info["sha256"].lower()):
            raise HashMismatch("download doesn't match its SHA-256")
        os.replace(part, final)
    except BaseException:
        for p in (part,):
            try:
                os.remove(p)
            except OSError:
                pass
        raise
    if not verify_file(final, info):            # read back from disk
        try:
            os.remove(final)
        except OSError:
            pass
        raise HashMismatch("saved file doesn't match its SHA-256")
    return final


# How the downloaded setup runs (Nov 3, Jon: "like normal software - I
# say update, it downloads and installs by itself"): with a progress bar
# and no questions, closing any QuantiSheet window of this copy that is
# still open, and starting QuantiSheet again when it's done (/QSRELAUNCH:
# the setup's own [Run] entry, installer/quantisheet.iss). The person has
# already said yes by clicking Update now; the personal setup needs no
# administrator rights, and QuantiSheet never asks Windows for them.
QUIET_SWITCHES = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                  "/CLOSEAPPLICATIONS", "/QSRELAUNCH"]


def launch_installer(path, info, run=None):
    """Run the downloaded setup with QUIET_SWITCHES, only after its SHA-256
    is checked once more. Started with CreateProcess (Popen), not
    ShellExecute, so QuantiSheet itself never asks Windows to elevate it.
    Returns True if started; raises HashMismatch (and deletes the file) if
    it changed on disk."""
    if not verify_file(path, info):
        try:
            os.remove(path)
        except OSError:
            pass
        raise HashMismatch("installer changed since it was downloaded")
    if info.get("signer"):
        # once releases are code-signed (tools/codesign.py), the signed
        # manifest names the certificate and Windows must agree (QS-007).
        # Can't check (PowerShell blocked) = don't install (review, Nov 4)
        got = signed_by(path, info["signer"])
        if got is None:
            raise HashMismatch(
                "QuantiSheet couldn't check the installer's signature on "
                "this PC (Windows PowerShell may be blocked), so nothing "
                "was installed. Install the update by hand from the file "
                "your administrator or QuantiSheet's support sends you.")
        if not got:
            raise HashMismatch("installer isn't signed by QuantiSheet's "
                               "certificate")
    if run is None:
        import subprocess
        run = lambda a: subprocess.Popen(a, close_fds=True)  # noqa: E731
    run([path] + QUIET_SWITCHES)
    return True


def ready_download(info, folder=None):
    """The already-downloaded, still-valid installer for `info`, or None."""
    p = installer_path(info, folder)
    return p if os.path.isfile(p) and verify_file(p, info) else None


def signed_by(path, thumbprint, run=None):
    """True when Windows says the file's Authenticode signature is valid
    and made with the certificate `thumbprint`; False when it says
    otherwise; None when it couldn't be asked (callers treat that as
    "don't install")."""
    import subprocess
    if run is None:
        def run(cmd):
            return subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=60,
                                  creationflags=getattr(subprocess,
                                                        "CREATE_NO_WINDOW",
                                                        0)).stdout
    ps = ("$s = Get-AuthenticodeSignature -LiteralPath $args[0]; "
          "\"$($s.Status)|$($s.SignerCertificate.Thumbprint)\"")
    try:
        out = (run(["powershell", "-NoProfile", "-NonInteractive",
                    "-Command", ps, path]) or "").strip()
    except Exception:                                     # noqa: BLE001
        return None                    # couldn't check at all
    if "|" not in out:
        return None
    status, _, thumb = out.partition("|")
    return status == "Valid" and thumb.strip().upper() == \
        thumbprint.strip().upper()


def previous_installer(folder=None, current=None):
    """The installer of the version before this one, kept for going back
    (newest older version), or None."""
    folder = folder or download_dir()
    cur = parse_version(current or current_version())
    best = None
    try:
        names = os.listdir(folder)
    except OSError:
        return None
    for n in names:
        m = re.fullmatch(r"QuantiSheet-Team-Setup-(.+)\.exe", n)
        v = parse_version(m.group(1)) if m else None
        if v is None or cur is None or not v < cur:
            continue
        if best is None or v > best[0]:
            best = (v, os.path.join(folder, n))
    return best[1] if best else None


def tidy(keep_version=None, folder=None, keep_previous=True):
    """Delete old downloads (anything not for keep_version), keeping the
    installer of the version running now, for going back (QS-007)."""
    folder = folder or download_dir()
    try:
        names = os.listdir(folder)
    except OSError:
        return
    keep = {f"QuantiSheet-Team-Setup-{keep_version}.exe"
            if keep_version else None}
    if keep_previous:
        keep.add(f"QuantiSheet-Team-Setup-{current_version()}.exe")
    for n in names:
        if n.startswith("QuantiSheet-Team-Setup-") and n not in keep:
            try:
                os.remove(os.path.join(folder, n))
            except OSError:
                pass
