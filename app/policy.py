"""Settings the IT department manages (Group Policy), which users can't
change inside the program.

Read once per run, first match wins:
  1. HKLM\\SOFTWARE\\Policies\\QuantiSheet      (Group Policy, computer)
  2. HKCU\\SOFTWARE\\Policies\\QuantiSheet      (Group Policy, user)
  3. %ProgramData%\\QuantiSheet\\policy.json    (no domain: an admin
                                               writes this file)
The ADMX template in installer/policy/ writes the same names. See
docs/IT_DEPLOYMENT.md for every setting.

Users can't write the Policies keys, so a setting there can switch off a
prompt (the license, the agreement, the sign-in) for every user of the PC:
IT has accepted it for the organisation. Those three (REGISTRY_ONLY) are
never taken from policy.json - on a PC where IT hasn't made the folder, a
user could create that file. The server installer locks the folder to
administrators."""
import json
import logging
import os
import threading
from urllib.parse import urlparse

log = logging.getLogger(__name__)
KEY = r"SOFTWARE\Policies\QuantiSheet"

# name: (type, what it does) - the one list the ADMX, the docs and the
# diagnostics report are checked against (tests/test_policy.py)
SETTINGS = {
    "LicenseKey": (str, "Beta license key for every user of this PC"),
    "AcceptAgreement": (bool, "No longer used (no agreement since "
                              "1.0.0)"),
    "SkipEmailSignIn": (bool, "Don't ask users for their work email "
                              "(the PC is company-managed)"),
    "PriceDatabasePath": (str, "Shared price database (a UNC path such as "
                               "\\\\server\\share\\prices.db)"),
    "RelayURL": (str, "Collaboration relay address, e.g. "
                      "ws://quantisheet-relay:8765"),
    "RelayToken": (str, "The relay's access token (on the relay server: "
                        "C:\\ProgramData\\QuantiSheet\\relay\\"
                        "relay-token.txt)"),
    "DisableAI": (bool, "Turn off the local AI features"),
    "AIHost": (str, "Ollama address (default http://localhost:11434)"),
    "OfflineMode": (bool, "No internet use at all (every item below)"),
    "DisableAerial": (bool, "No aerial photos, address lookup or site "
                            "layers (USGS, Census, FEMA, USFWS)"),
    "DisableWeather": (bool, "No weather for daily logs (Open-Meteo)"),
    "DisableRateLookup": (bool, "No labor-rate downloads (BLS)"),
    "DisableDocuSign": (bool, "No DocuSign signature requests"),
    "DisableDropbox": (bool, "No Dropbox open and save (dropbox.com)"),
    "DisableUpdateCheck": (bool, "No daily update check: the team copy's "
                                 "check for a newer version, and the "
                                 "Microsoft Store copy's reminder when the "
                                 "Store has an update waiting"),
    "DisablePackageStatus": (bool, "No live package status from the "
                                   "carriers (Package Tracker > Check "
                                   "Status)"),
    "DropboxAppKey": (str, "The Dropbox App key for every user (from the "
                           "company's Dropbox app; no App secret is "
                           "needed)"),
    "LogDirectory": (str, "Write log files here instead of each user's "
                          "profile"),
}

# what each internet feature talks to (docs/IT_DEPLOYMENT.md lists these
# for the firewall); category -> (policy that turns it off, hosts)
def _update_host():
    """The team copy's update host - one value, in updatecheck.py."""
    try:
        from app.updatecheck import UPDATE_HOST
    except ImportError:              # loaded on its own (tools/make_admx.py)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_qs_updatecheck", os.path.join(os.path.dirname(
                os.path.abspath(__file__)), "updatecheck.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        UPDATE_HOST = mod.UPDATE_HOST
    return UPDATE_HOST


NETWORK = {
    "aerial": ("DisableAerial", ["imagery.nationalmap.gov",
                                 "basemap.nationalmap.gov",
                                 "carto.nationalmap.gov",
                                 "geocoding.geo.census.gov",
                                 "hazards.fema.gov",
                                 "fwspublicservices.wim.usgs.gov"]),
    # the customer-... servers: with an Open-Meteo commercial API key
    # (weather._url)
    "weather": ("DisableWeather", ["api.open-meteo.com",
                                   "archive-api.open-meteo.com",
                                   "geocoding-api.open-meteo.com",
                                   "customer-api.open-meteo.com",
                                   "customer-archive-api.open-meteo.com",
                                   "customer-geocoding-api.open-meteo.com"]),
    "rates": ("DisableRateLookup", ["api.bls.gov", "data.bls.gov"]),
    "docusign": ("DisableDocuSign", ["*.docusign.net"]),
    "dropbox": ("DisableDropbox", ["www.dropbox.com", "api.dropboxapi.com",
                                   "content.dropboxapi.com"]),
    "ai": ("DisableAI", ["localhost:11434 (or AIHost)"]),
    # Package Tracker > Check Status (packages_live.HOSTS), only with a
    # carrier's keys and only when someone clicks it
    "packages": ("DisablePackageStatus", ["onlinetools.ups.com",
                                          "apis.fedex.com", "apis.usps.com",
                                          "api-eu.dhl.com"]),
    # team copy only (updatecheck.py; must equal its MANIFEST_HOSTS |
    # DOWNLOAD_HOSTS - tests/test_updatecheck.py)
    "update": ("DisableUpdateCheck", [_update_host()]),
}

_cache = None
_lock = threading.Lock()


class Blocked(RuntimeError):
    """A feature the IT department turned off."""


def _from_registry():
    out = {}
    try:
        import winreg
    except ImportError:
        return out
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, KEY) as k:
                i = 0
                while True:
                    try:
                        name, val, _t = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    out.setdefault(name, val)        # HKLM first: it wins
        except OSError:
            continue
    return out


# settings that unlock something for the user: only Group Policy (the
# registry, which users can't write) may set them - never policy.json,
# which a user could create on a PC where IT hasn't made the folder
# (Fable review S1)
REGISTRY_ONLY = {"LicenseKey", "AcceptAgreement", "SkipEmailSignIn"}


def _program_data():
    """C:\\ProgramData from Windows itself - not from the environment, which
    the user controls."""
    try:
        import ctypes
        from ctypes import wintypes
        # FOLDERID_ProgramData {62AB5D82-FDC1-4DC3-A9DD-070D1D495D97},
        # as the GUID struct lays it out in memory
        guid = (ctypes.c_byte * 16).from_buffer_copy(bytes.fromhex(
            "825dab62c1fdc34da9dd070d1d495d97"))
        out = wintypes.LPWSTR()
        if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(guid), 0, None, ctypes.byref(out)) == 0:
            path = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            return path
    except Exception:                                     # noqa: BLE001
        pass
    return r"C:\ProgramData" if os.name == "nt" else os.path.join(
        os.path.expanduser("~"), ".quantisheet-programdata")


# the machine data folder in ProgramData
DATA_DIR = "QuantiSheet"
POLICY_FILE = "policy.json"
# owners of a policy.json an administrator made (SYSTEM, Administrators,
# TrustedInstaller)
_ADMIN_OWNERS = {"S-1-5-18", "S-1-5-32-544",
                 "S-1-5-80-956008885-3418522649-1831038044-1853292631-"
                 "2271478464"}


def data_dir():
    """The machine data folder: ProgramData\\QuantiSheet."""
    return os.path.join(_program_data(), DATA_DIR)


def _owner_sid(path):
    """The file owner's SID as text (S-1-5-...), or None (not Windows, or
    it can't be read)."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        adv.GetNamedSecurityInfoW.restype = wintypes.DWORD
        adv.GetNamedSecurityInfoW.argtypes = [
            wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p)]
        adv.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        k32.LocalFree.argtypes = [ctypes.c_void_p]
        owner, sd = ctypes.c_void_p(), ctypes.c_void_p()
        # SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION
        if adv.GetNamedSecurityInfoW(path, 1, 1, ctypes.byref(owner), None,
                                     None, None, ctypes.byref(sd)) != 0:
            return None
        try:
            text = wintypes.LPWSTR()
            if not adv.ConvertSidToStringSidW(owner, ctypes.byref(text)):
                return None
            try:
                return text.value
            finally:
                k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        finally:
            k32.LocalFree(sd)
    except Exception:                                     # noqa: BLE001
        log.debug("owner of %s not read", path, exc_info=True)
        return None


def _admin_made(path):
    """Was `path` made by an administrator (owned by SYSTEM,
    Administrators or TrustedInstaller)? Always yes off Windows (the
    stand-in folder is the user's own)."""
    if os.name != "nt":
        return True
    return _owner_sid(path) in _ADMIN_OWNERS


def _file():
    """The policy.json to read: ProgramData\\QuantiSheet's - and ONLY one
    an administrator made (owned by SYSTEM, Administrators or TrustedInstaller). ProgramData
    lets any user make a folder and a file, so a file a regular user made
    is ignored, with a warning in the log (threat model T-001: it could
    point the AI helper, the price database or the logs somewhere else for
    everyone on the PC). The setups' copy is administrator-owned; IT
    copying one by hand should make Administrators its owner."""
    import sys
    if not getattr(sys, "frozen", False) and \
            os.environ.get("QUANTISHEET_POLICY_FILE"):
        return os.environ["QUANTISHEET_POLICY_FILE"]      # tests, source runs
    path = os.path.join(data_dir(), POLICY_FILE)
    if not os.path.isfile(path):
        return path                  # the usual place; nothing there yet
    if _admin_made(path):
        return path
    log.warning("policy file %s is not owned by an administrator - "
                "ignored", path)
    return ""


def _from_file():
    path = _file()
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:                                     # noqa: BLE001
        log.warning("policy file %s can't be read", path, exc_info=True)
        return {}


def _coerce(name, val):
    typ = SETTINGS[name][0]
    if typ is bool:
        if isinstance(val, str):
            return val.strip().lower() in ("1", "true", "yes", "on")
        return bool(val)
    return str(val).strip() if val is not None else ""


def _load():
    raw = _from_registry()
    for k, v in _from_file().items():
        if k in REGISTRY_ONLY:
            log.info("policy %s ignored in policy.json (Group Policy only)",
                     k)
            continue
        raw.setdefault(k, v)
    out = {}
    for k, v in raw.items():
        if k in SETTINGS:
            try:
                out[k] = _coerce(k, v)
            except Exception:                             # noqa: BLE001
                log.warning("policy %s has a bad value", k)
        else:
            log.info("unknown policy setting %s ignored", k)
    return out


def all_set():
    """{name: value} for every setting IT has made."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load()
        return dict(_cache)


def reload():
    global _cache
    with _lock:
        _cache = None


def get(name, default=None):
    if name not in SETTINGS:
        raise KeyError(name)
    v = all_set().get(name)
    if v in (None, ""):
        return default
    return v


def on(name):
    return bool(get(name, False))


def masked():
    """For the diagnostics report: the key's middle is hidden."""
    out = {}
    for k, v in all_set().items():
        if k in ("LicenseKey", "RelayToken") and v:
            out[k] = "(set)"          # nothing of it (Venice review S5)
        else:
            out[k] = v
    return out


def allowed(category):
    """Is this internet feature allowed? (OfflineMode turns off all.)"""
    if category == "ai":
        return not on("DisableAI")
    if on("OfflineMode"):
        return False
    name = NETWORK.get(category, (None,))[0]
    return not (name and on(name))


def check(category, url=""):
    """Raise Blocked (with a message a user understands) if IT turned the
    feature off."""
    if allowed(category):
        return
    name = "DisableAI" if category == "ai" else (
        "OfflineMode" if on("OfflineMode") else NETWORK[category][0])
    host = urlparse(url).hostname if url else ""
    raise Blocked("Turned off by your IT department (policy "
                  f"{name}){' - ' + host if host else ''}.")
