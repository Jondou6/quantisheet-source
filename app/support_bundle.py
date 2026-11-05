"""A support zip written on this computer. Nothing in this module uploads.

Help already builds a different zip (app/diagnostics.py). This one is the
bundle Claude asked to wire up: the log, the version, what the installer
left, the settings, and the newest crash record.

Public functions
----------------
make_bundle(out_zip)
    Write the zip and return its path.
crash_path()
    Path of the newest crash record, or None. A menu item can open it.
scrub(text)
    Profile paths become ``%USERPROFILE%``, account names become
    ``%USERNAME%``, and email addresses are removed.
install_info()
    The same facts ``tools/install_info.py`` prints, as one string.
"""
import datetime
import getpass
import glob
import json
import os
import re
import zipfile

# Setting names whose values must not be copied into the zip. The name is
# kept so it is obvious something was left out. Emails and account names
# are scrubbed in place instead, so a path is still readable afterwards.
_SECRET_KEY = re.compile(
    r"(?i)(pass(?:word)?|secret|token|api[_-]?key|(?:^|_)key(?:$|_)|license)")
# C:\Users\<name> and the same path with escaped backslashes (JSON).
_WIN_PROFILE = re.compile(
    r"(?i)(?:[A-Za-z]:)\\+Users\\+[^\\\"\r\n/]+")
_WIN_PROFILE_FWD = re.compile(r"(?i)[A-Za-z]:/Users/[^\\\"\r\n/]+")
# \\server\share, including the doubled backslashes of a JSON string.
# Not a path that continues a drive letter or %USERPROFILE% (those
# backslashes belong to the profile rewrite above).
_UNC = re.compile(
    r"(?<![A-Za-z0-9%])\\{2,}(?!\\)[\w.$-]+\\+[\w.$-]+")
_READ_LIMIT = 3_000_000


def crash_path():
    """Path of the newest crash record, or None when there isn't one.

    Uses crashreport.reports (newest first). Does not write anything and
    does not send anything.
    """
    try:
        from . import crashreport
        found = crashreport.reports(1)
    except Exception:                                     # noqa: BLE001
        return None
    return found[0] if found else None


def scrub(text):
    """Take user names, profile paths and email addresses out of `text`.

    ``C:\\Users\\<name>`` (and ``C:/Users/<name>``) becomes
    ``%USERPROFILE%``. This computer's own home folder is rewritten the
    same way, so a Linux path or a JSON-escaped Windows path does not
    leak the account. Email addresses go through crashreport's cleaner.
    The Windows account name, the login name, and the Author Name setting
    become ``%USERNAME%``.
    """
    from . import crashreport
    text = "" if text is None else str(text)
    for home in _homes():
        text = _replace_home(text, home)
    text = _WIN_PROFILE.sub("%USERPROFILE%", text)
    text = _WIN_PROFILE_FWD.sub("%USERPROFILE%", text)
    # a function, not a replacement string: re.sub would eat the backslashes
    # and leave JSON with an invalid escape
    text = _UNC.sub(lambda _m: r"\\[server]\\[share]", text)
    text = crashreport._clean(text)
    for name in _names():
        text = _hide_name(text, name)
    return text


def install_info():
    """The same facts as tools/install_info.py, as one string.

    Read-only. It does not change the install, and it does not download
    an update: it only lists the install folder, setup logs already in
    TEMP, and the update folder (app.updatecheck.download_dir).
    """
    from . import branding, updatecheck
    lines = []
    exe = branding.installed_exe()
    folder = os.path.dirname(exe)
    lines.append("install folder: " + folder)
    for name in ("QuantiSheet.exe", "unins000.exe", "unins000.dat",
                 "unins000.msg"):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            lines.append(f"  {name:16} {_stamp(path)}  "
                         f"{os.path.getsize(path):,} bytes")
    tmp = os.environ.get("TEMP", "")
    lines.append("TEMP: " + tmp)
    found = []
    for pattern in (os.path.join(tmp, "Setup Log*.txt"),
                    os.path.join(tmp, "is-*")):
        found.extend(glob.glob(pattern))
    found = [p for p in found if os.path.exists(p)]
    for path in sorted(found, key=os.path.getmtime)[-12:]:
        lines.append(f"  {_stamp(path)}  {os.path.basename(path)}")
    try:
        downloads = updatecheck.download_dir()
    except Exception as exc:                              # noqa: BLE001
        downloads = ""
        lines.append(f"download folder: ? {exc}")
    if downloads and os.path.isdir(downloads):
        lines.append("update downloads: " + downloads)
        for path in sorted(glob.glob(os.path.join(downloads, "*")),
                           key=os.path.getmtime):
            if os.path.isfile(path):
                lines.append(f"  {_stamp(path)}  {os.path.basename(path)}  "
                             f"{os.path.getsize(path):,}")
    logs = sorted(glob.glob(os.path.join(tmp, "Setup Log*.txt")),
                  key=os.path.getmtime)
    if logs:
        path = logs[-1]
        lines.append("== newest setup log: " + os.path.basename(path))
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                body = fh.readlines()
        except OSError as exc:
            lines.append(f"   (could not read: {exc})")
        else:
            # same slice the installer script prints, including the "..."
            for line in body[:8] + ["...\n"] + body[-8:]:
                lines.append("   " + line.rstrip()[:220])
    return "\n".join(lines) + "\n"


def make_bundle(out_zip):
    """Write a support zip at `out_zip` and return that path.

    Contents (text is passed through scrub):

    * NOTICE.txt — states that the zip is not uploaded
    * version.txt — legal.versions()
    * install.txt — install_info()
    * settings.json — settings, secret values withheld
    * logs/ — the app log, its rotated copy, and crash.log
    * crashes/ — the newest crash record only (crash_path)

    No network. A folder that does not exist yet is created. An existing
    zip at the same path is replaced.
    """
    out_zip = os.fspath(out_zip)
    parent = os.path.dirname(os.path.abspath(out_zip))
    if parent:
        os.makedirs(parent, exist_ok=True)
    from . import legal
    version = "".join(f"{name}: {value}\n" for name, value in legal.versions())
    notice = ("QuantiSheet support bundle\n"
              "This zip was written on this computer. "
              "QuantiSheet does not upload it.\n")
    part = out_zip + ".part"
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("NOTICE.txt", notice)
            z.writestr("version.txt", scrub(version))
            z.writestr("install.txt", scrub(install_info()))
            z.writestr("settings.json",
                       scrub(json.dumps(_public_settings(), indent=2,
                                        default=str) + "\n"))
            for name, path in _log_files():
                z.writestr("logs/" + name, scrub(_read_text(path)))
            newest = crash_path()
            if newest and os.path.isfile(newest):
                z.writestr("crashes/" + os.path.basename(newest),
                           scrub(_read_text(newest)))
        os.replace(part, out_zip)
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
    return out_zip


def _public_settings():
    from . import settings
    raw = settings._load()
    if not isinstance(raw, dict):
        return {}
    return {k: _redact(k, v) for k, v in raw.items()}


def _redact(key, value):
    if _SECRET_KEY.search(str(key or "")):
        return "[withheld]"
    if isinstance(value, dict):
        return {k: _redact(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact("", v) if isinstance(v, (dict, list)) else v
                for v in value]
    return value


def _log_files():
    from . import settings
    from .main import log_folder
    folder = log_folder()
    for name in (settings.LOG_NAME, settings.LOG_NAME + ".old",
                 "crash.log", "crash.log.old"):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            yield name, path


def _read_text(path, limit=_READ_LIMIT):
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - limit))
        data = fh.read()
    if size > limit:
        cut = data.find(b"\n")
        if cut >= 0:
            data = data[cut + 1:]
    return data.decode("utf-8", "replace")


def _stamp(path):
    return datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime(
        "%Y-%m-%d %H:%M:%S")


def _homes():
    found = []
    for key in ("USERPROFILE", "HOME"):
        value = os.environ.get(key) or ""
        if value:
            found.append(value)
    try:
        found.append(os.path.expanduser("~"))
    except Exception:                                     # noqa: BLE001
        pass
    out = []
    for value in found:
        value = str(value).rstrip("\\/")
        if len(value) >= 4 and value not in out and any(
                sep in value for sep in ("\\", "/")):
            out.append(value)
    return out


def _replace_home(text, home):
    variants = {home, home.replace("\\", "/"), home.replace("/", "\\")}
    extra = set()
    for variant in variants:
        if "\\" in variant:
            extra.add(variant.replace("\\", "\\\\"))
    variants |= extra
    for variant in sorted(variants, key=len, reverse=True):
        if len(variant) < 4 or variant in ("%USERPROFILE%",):
            continue
        if os.name == "nt":
            text = re.sub(re.escape(variant), "%USERPROFILE%", text,
                          flags=re.I)
        elif variant in text:
            text = text.replace(variant, "%USERPROFILE%")
    return text


def _names():
    found = []
    for key in ("USERNAME", "USER"):
        value = os.environ.get(key) or ""
        if len(value) >= 3:
            found.append(value)
    try:
        value = getpass.getuser()
    except Exception:                                     # noqa: BLE001
        value = ""
    if value and len(value) >= 3:
        found.append(value)
    try:
        from . import settings
        author = settings.get("author")
    except Exception:                                     # noqa: BLE001
        author = None
    if isinstance(author, str) and len(author.strip()) >= 3:
        found.append(author.strip())
    out = []
    for name in sorted(found, key=len, reverse=True):
        if name not in out and name not in ("%USERNAME%", "%USERPROFILE%"):
            out.append(name)
    return out


def _hide_name(text, name):
    if any(ch in name for ch in (" ", "\\", "/")):
        return re.sub(re.escape(name), "%USERNAME%", text, flags=re.I)
    return re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", "%USERNAME%",
                  text, flags=re.I)
