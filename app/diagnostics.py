"""Support bundle for the help desk: Help > Support Bundle, or
`QuantiSheet.exe diagnostics --out bundle.zip`.

What's in it: versions, Windows edition (desktop / Server / Server Core,
Remote Desktop session or not), the IT policy in effect, whether the
license, sign-in, price database, relay, AI and OCR are working, and the
log files. What is NOT: license keys, passwords, tokens, the settings'
values, or email addresses (removed from the logs as well)."""
import datetime
import json
import logging
import os
import platform
import re
import sys
import zipfile

log = logging.getLogger(__name__)

SECRET = re.compile(r"key|token|pass|secret|email|mail|account|user|"
                    r"contact", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
UNC = re.compile(r"\\\\[\w.$-]+\\[\w.$-]+")       # \\server\share


def windows():
    """{'edition', 'install_type', 'build', 'server', 'remote_session'}"""
    out = {"platform": platform.platform(), "server": False,
           "install_type": "", "build": "", "edition": ""}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
                            ) as k:
            for name, key in (("edition", "ProductName"),
                              ("install_type", "InstallationType"),
                              ("build", "CurrentBuildNumber"),
                              ("display", "DisplayVersion")):
                try:
                    out[name] = str(winreg.QueryValueEx(k, key)[0])
                except OSError:
                    pass
    except Exception:                                     # noqa: BLE001
        pass
    out["server"] = out["install_type"].lower().startswith("server") or \
        "server" in out["edition"].lower()
    out["server_core"] = out["install_type"].lower() == "server core"
    sess = os.environ.get("SESSIONNAME", "")
    out["remote_session"] = sess.upper().startswith("RDP-")
    out["session"] = sess
    return out


def _try(fn):
    try:
        return fn()
    except Exception as e:                                # noqa: BLE001
        return f"error: {type(e).__name__}: {e}"[:200]


def report():
    from . import __version__, policy, settings
    r = {"made": datetime.datetime.now().isoformat(timespec="seconds"),
         "version": __version__, "frozen": bool(getattr(sys, "frozen",
                                                        False)),
         "program": sys.executable, "python": sys.version.split()[0],
         "windows": windows(), "policy": policy.masked()}
    r["libraries"] = {}
    for mod in ("fitz", "PySide6", "numpy", "ezdxf", "modulor"):
        def ver(m=mod):
            x = __import__(m)
            return getattr(x, "__version__", None) or getattr(
                x, "VersionBind", "") or "present"
        r["libraries"][mod] = _try(ver)

    def lic():
        from . import betalicense
        info = betalicense.current()
        return {"required": betalicense.required(),
                "licensed": bool(info), "agreement": betalicense.accepted(),
                "days_left": betalicense.days_left(info) if info else None}
    r["license"] = _try(lic)
    r["signed_in"] = _try(lambda: __import__(
        "app.onboard", fromlist=["x"]).signed_in())

    def prices():
        from . import pricedb
        p = pricedb.path()
        return {"path": p, "set_by_it": bool(pricedb.managed()),
                "reachable": os.path.exists(p)}
    r["price_database"] = _try(prices)
    r["relay"] = _try(lambda: __import__(
        "app.collab.hubclient", fromlist=["x"]).default_url())

    def ai():
        from .genset import brief
        return {"allowed": policy.allowed("ai"), "answering": brief.ai_up()}
    r["ai"] = _try(ai)
    r["ocr"] = _try(lambda: bool(__import__(
        "app.ocr", fromlist=["x"]).find_tesseract()))
    r["internet_features"] = {c: policy.allowed(c) for c in policy.NETWORK
                              if c != "ai"}

    def disk():
        import shutil
        u = shutil.disk_usage(settings.DIR if os.path.isdir(settings.DIR)
                              else os.path.expanduser("~"))
        return f"{u.free / 2 ** 30:.1f} GB free"
    r["disk"] = _try(disk)
    # which settings exist - names only, never values that could be private
    r["settings"] = _try(lambda: sorted(
        k + ("" if not SECRET.search(k) else " (value withheld)")
        for k in settings._load()))
    return r


def _logs(crashes=True):
    from . import settings
    from .main import log_folder
    d = log_folder()
    for name in (settings.LOG_NAME, settings.LOG_NAME + ".old",
                 "crash.log", "crash.log.old"):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            yield name, p
    if not crashes:                 # left out in Report an Issue (Nov 4)
        return
    try:                            # the newest crash reports (0.12.24)
        from . import crashreport
        for p in crashreport.reports(10):
            yield "crashes/" + os.path.basename(p), p
    except Exception:                                     # noqa: BLE001
        pass


def _secrets():
    """Values that must never leave in a support zip (Venice review S5):
    the license key and relay token in effect, and every setting whose
    name looks secret. Literal values, longest first."""
    from . import policy, settings
    vals = set()
    for k in ("LicenseKey", "RelayToken"):
        v = _try(lambda k=k: policy.get(k))
        if isinstance(v, str) and len(v) >= 6:
            vals.add(v)
    try:
        for k, v in settings._load().items():
            if SECRET.search(k) and isinstance(v, str) and len(v) >= 6:
                vals.add(v)
    except Exception:                                     # noqa: BLE001
        pass
    try:
        from . import betalicense
        v = settings.get("beta_key") or betalicense._reg("k")
        if isinstance(v, str) and len(v) >= 6:
            vals.add(v)
    except Exception:                                     # noqa: BLE001
        pass
    return sorted(vals, key=len, reverse=True)


def scrub(text, secrets=None):
    """Emails, known secrets, the Windows user name and UNC paths out."""
    secrets = _secrets() if secrets is None else secrets
    for v in secrets:
        text = text.replace(v, "[secret removed]")
    text = EMAIL.sub("[email removed]", text)
    text = UNC.sub(r"\\\\[server]\\[share]", text)
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if len(user) >= 3:
        text = re.sub(re.escape(user), "[user]", text, flags=re.I)
    return text


def bundle(out_path, crashes=True):
    """Write the zip; returns its path. crashes=False leaves the crash
    reports out (the Report an Issue checkbox, Venice #8)."""
    rep = report()
    secrets = _secrets()
    rep = json.loads(scrub(json.dumps(rep, default=str), secrets))
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.json", json.dumps(rep, indent=2, default=str))
        try:                        # install facts (support_bundle, PR 13)
            from . import support_bundle
            z.writestr("install.txt", scrub(support_bundle.scrub(
                support_bundle.install_info()), secrets))
        except Exception:                                 # noqa: BLE001
            log.warning("install facts left out", exc_info=True)
        for name, p in _logs(crashes):
            with open(p, "rb") as f:
                data = f.read()[-3_000_000:]          # the newest 3 MB
            text = data.decode("utf-8", "replace")
            z.writestr("logs/" + name, scrub(text, secrets))
    return out_path
