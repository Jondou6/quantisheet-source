"""Dropbox open and save, through the Dropbox HTTP API v2 (no Dropbox
desktop app needed). The Qt side is in dropbox_ui.py; nothing here
imports Qt, so it is tested with a fake Dropbox (tests/test_dropbox.py).

Sign-in is OAuth 2 with PKCE (RFC 7636): the program has no App secret.
The team registers its own free Dropbox app and pastes the App key into
File > Dropbox Settings... (setting "dropbox_app_key"), or IT sets it for
every user (policy DropboxAppKey). The browser comes back to a one-shot
server on http://127.0.0.1:<port>/ (REDIRECT_PORT, setting
"dropbox_redirect_port"), bound to 127.0.0.1 only and checking the state;
when that port can't be opened, Dropbox's "copy this code" page is used
instead. Offline access: the refresh token is kept DPAPI-encrypted for
this Windows user (secretstore), or in a file only this user can read off
Windows. Access tokens live in memory only.

Network use only happens when the user runs a Dropbox command: nothing at
start-up, no polling. IT can turn it off (policy DisableDropbox, or
OfflineMode).

Working copies: a file opened from Dropbox is downloaded to
<settings.DIR>/Dropbox/<its Dropbox path>. A sidecar
(<settings.DIR>/Dropbox/.links/<hash of the local path>.json) records the
Dropbox path, rev and content_hash, for any local file that came from or
was saved to Dropbox. "Save to Dropbox" sends the file back with mode
update + the remembered rev, so a version someone else saved meanwhile is
never overwritten silently (Conflict); a new file uses mode add with no
autorename (a name already there is a Conflict too).

Never logged, and never in a URL: tokens, codes, file contents. Only the
endpoint name and HTTP status are logged.
"""
import base64
import hashlib
import http.client
import http.server
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import settings

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://www.dropbox.com/oauth2/authorize"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
API = "https://api.dropboxapi.com/2/"
CONTENT = "https://content.dropboxapi.com/2/"
APPS_URL = "https://www.dropbox.com/developers/apps"
# account_info.read is ticked (and locked) on every scoped Dropbox app; it
# is what users/get_current_account (the signed-in name and email) needs
SCOPES = ("account_info.read", "files.metadata.read", "files.content.read",
          "files.content.write")
REDIRECT_PORT = 53917
LOOPBACK_HOST = "127.0.0.1"

BLOCK = 4 * 1024 * 1024                  # Dropbox content-hash block size
SINGLE_UPLOAD_MAX = 150 * 1024 * 1024    # /upload takes files under this
CHUNK = 8 * 1024 * 1024                  # upload-session chunk (4 MB x 2)
READ = 1024 * 1024                       # download read size
TIMEOUT = 120

TOKEN_FILE_DPAPI = "dropbox-token.dpapi"
TOKEN_FILE_PLAIN = "dropbox-token.json"
WORK_DIR = "Dropbox"
LINKS_DIR = ".links"

_lock = threading.RLock()


# ---- errors: every message is one a user understands -------------------------
class DropboxError(RuntimeError):
    """Something went wrong; str(e) is a plain message for the user."""


class NetworkError(DropboxError):
    pass


class NotSignedIn(DropboxError):
    pass


class Cancelled(DropboxError):
    pass


class ApiError(DropboxError):
    def __init__(self, msg, status=0, summary=""):
        super().__init__(msg)
        self.status = status
        self.summary = summary


class NotFound(ApiError):
    pass


class Conflict(ApiError):
    """The file in Dropbox isn't the one we remembered (someone saved a
    newer version), or a new file's name is already taken. `remote` is the
    Dropbox file's metadata when known."""

    def __init__(self, msg, status=409, summary="", remote=None):
        super().__init__(msg, status, summary)
        self.remote = remote


class LocalChanges(DropboxError):
    """The working copy has changes not yet saved to Dropbox."""


# ---- policy and settings ---------------------------------------------------------
def allowed():
    """May Dropbox be used on this PC (IT policy DisableDropbox /
    OfflineMode)?"""
    from . import policy
    return policy.allowed("dropbox")


def check_allowed():
    from . import policy
    policy.check("dropbox", API)


def app_key():
    """The Dropbox App key: IT's (policy DropboxAppKey) wins over the
    user's setting "dropbox_app_key". "" until one is set."""
    from . import policy
    k = policy.get("DropboxAppKey") or settings.get("dropbox_app_key") or \
        company_app_key() or ""
    return str(k).strip()


def company_app_key():
    """The company's own Dropbox app (app/data/company_dropbox.json, in the
    company's builds only; never in public builds or the source zip)."""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                     "company_dropbox.json")
    try:
        with open(p, encoding="utf-8") as f:
            return str(json.load(f).get("app_key") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def app_key_from_policy():
    from . import policy
    return bool(policy.get("DropboxAppKey"))


def valid_app_key(key):
    """A Dropbox App key looks like 15 lower-case letters and digits."""
    return bool(re.fullmatch(r"[A-Za-z0-9]{8,40}", (key or "").strip()))


def set_app_key(key):
    settings.set("dropbox_app_key", (key or "").strip())


def redirect_port():
    try:
        p = int(settings.get("dropbox_redirect_port") or REDIRECT_PORT)
        return p if 1024 <= p <= 65535 else REDIRECT_PORT
    except (TypeError, ValueError):
        return REDIRECT_PORT


def redirect_uri(port=None):
    """The exact redirect URI to add in the Dropbox app's settings."""
    return f"http://{LOOPBACK_HOST}:{port or redirect_port()}/"


def default_folder():
    return normalize(settings.get("dropbox_default_folder") or "")


def set_default_folder(path):
    settings.set("dropbox_default_folder", normalize(path))


# ---- PKCE (RFC 7636) and the authorize URL ----------------------------------------
def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def pkce_challenge(verifier):
    """S256: BASE64URL(SHA256(ASCII(code_verifier)))."""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def pkce_pair():
    """(code_verifier, code_challenge). The verifier is 86 characters of
    [A-Za-z0-9-_] (RFC 7636 asks for 43-128)."""
    verifier = secrets.token_urlsafe(64)
    return verifier, pkce_challenge(verifier)


def new_state():
    return secrets.token_urlsafe(24)


def authorize_url(key, challenge, state=None, redirect=None):
    """The page that asks the user to allow QuantiSheet. Without
    `redirect`, Dropbox shows a code to copy instead."""
    q = {"client_id": key, "response_type": "code",
         "code_challenge": challenge, "code_challenge_method": "S256",
         "token_access_type": "offline", "scope": " ".join(SCOPES)}
    if redirect:
        q["redirect_uri"] = redirect
    if state:
        q["state"] = state
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        q, quote_via=urllib.parse.quote)


# ---- Dropbox content hash -------------------------------------------------------
class ContentHasher:
    """Dropbox's content_hash: SHA-256 of each 4 MB block, then SHA-256 of
    the block hashes put together. Takes data in any size of pieces."""

    def __init__(self):
        self._outer = hashlib.sha256()
        self._block = hashlib.sha256()
        self._in_block = 0

    def update(self, data):
        mv = memoryview(data)
        while len(mv):
            take = min(BLOCK - self._in_block, len(mv))
            self._block.update(mv[:take])
            self._in_block += take
            mv = mv[take:]
            if self._in_block == BLOCK:
                self._outer.update(self._block.digest())
                self._block = hashlib.sha256()
                self._in_block = 0

    def hexdigest(self):
        outer = self._outer.copy()
        if self._in_block:
            outer.update(self._block.digest())
        return outer.hexdigest()


def content_hash(path):
    h = ContentHasher()
    with open(path, "rb") as f:
        while True:
            b = f.read(BLOCK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---- paths -----------------------------------------------------------------------
def normalize(path):
    """A Dropbox path: "" for the root, else "/a/b" (no trailing /)."""
    p = (path or "").replace("\\", "/").strip()
    p = "/" + "/".join(x for x in p.split("/") if x)
    return "" if p == "/" else p


def join(folder, name):
    return normalize(normalize(folder) + "/" + name)


def parent(path):
    p = normalize(path)
    return p.rsplit("/", 1)[0] if p else ""


def basename(path):
    return normalize(path).rsplit("/", 1)[-1]


_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def _safe_part(part):
    s = _BAD.sub("_", part).rstrip(" .")
    if not s or s in (".", ".."):
        s = "_"
    if s.split(".")[0].upper() in _RESERVED:
        s = "_" + s
    return s


def work_root():
    return os.path.join(settings.DIR, WORK_DIR)


def local_path_for(dropbox_path):
    """Where the working copy of a Dropbox file goes: mirrors the Dropbox
    path under <settings.DIR>/Dropbox (names Windows can't hold are made
    safe, so it never leaves that folder)."""
    parts = [_safe_part(x) for x in normalize(dropbox_path).split("/") if x]
    if not parts:
        raise DropboxError("That isn't a Dropbox file.")
    return os.path.join(work_root(), *parts)


def is_working_copy(local):
    root = os.path.normcase(os.path.abspath(work_root())) + os.sep
    return os.path.normcase(os.path.abspath(local)).startswith(root)


# ---- sidecars: which Dropbox file a local file belongs to ------------------------
def _key(local):
    return os.path.normcase(os.path.abspath(local))


def sidecar_path(local):
    h = hashlib.sha256(_key(local).encode("utf-8")).hexdigest()[:40]
    return os.path.join(work_root(), LINKS_DIR, h + ".json")


def read_link(local):
    """{"path", "rev", "content_hash", ...} for a local file that came from
    or was saved to Dropbox, else None."""
    if not local:
        return None
    try:
        with open(sidecar_path(local), encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or rec.get("local_key") != _key(local) or \
            not rec.get("path") or not rec.get("rev"):
        return None
    return rec


def write_link(local, meta):
    rec = {"local": os.path.abspath(local), "local_key": _key(local),
           "path": meta.get("path_display") or meta.get("path_lower"),
           "path_lower": meta.get("path_lower"), "id": meta.get("id"),
           "rev": meta.get("rev"), "content_hash": meta.get("content_hash"),
           "size": meta.get("size"),
           "server_modified": meta.get("server_modified"),
           "synced": time.strftime("%Y-%m-%dT%H:%M:%S")}
    p = sidecar_path(local)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, p)
    return rec


def forget_link(local):
    try:
        os.remove(sidecar_path(local))
    except OSError:
        pass


# ---- the stored sign-in (refresh token) --------------------------------------------
def _token_path():
    from . import secretstore
    name = TOKEN_FILE_DPAPI if secretstore.available() else TOKEN_FILE_PLAIN
    return os.path.join(settings.DIR, name)


def load_tokens():
    """The stored sign-in: {"refresh_token", "app_key", "account_id",
    "name", "email"}, or {}."""
    from . import secretstore
    p = _token_path()
    try:
        with open(p, "rb") as f:
            raw = f.read()
    except OSError:
        return {}
    try:
        if secretstore.available():
            raw = secretstore.unprotect(raw)
        data = json.loads(raw.decode("utf-8"))
    except Exception:                                     # noqa: BLE001
        log.warning("the stored Dropbox sign-in can't be read (another "
                    "Windows user or PC?); sign in again")
        return {}
    return data if isinstance(data, dict) else {}


def save_tokens(data):
    from . import secretstore
    keep = {k: data.get(k) for k in ("refresh_token", "app_key",
                                     "account_id", "name", "email")
            if data.get(k)}
    raw = json.dumps(keep).encode("utf-8")
    p = _token_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    if secretstore.available():
        blob = secretstore.protect(raw, "The Dropbox sign-in")
        with open(tmp, "wb") as f:
            f.write(blob)
    else:
        # no DPAPI: a file only this user can read or write
        try:
            os.remove(tmp)
        except OSError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    os.replace(tmp, p)


def clear_tokens():
    for name in (TOKEN_FILE_DPAPI, TOKEN_FILE_PLAIN):
        try:
            os.remove(os.path.join(settings.DIR, name))
        except OSError:
            pass


def signed_in():
    t = load_tokens()
    return bool(t.get("refresh_token")) and t.get("app_key") == app_key()


# ---- the HTTP layer (tests replace `transport`) ------------------------------------
class Response:
    def __init__(self, status, headers=None, fp=None, body=b""):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self._fp = fp
        self._body = body

    def read(self, n=-1):
        if self._fp is None:
            if n is None or n < 0:
                out, self._body = self._body, b""
            else:
                out, self._body = self._body[:n], self._body[n:]
            return out
        return self._fp.read() if n is None or n < 0 else self._fp.read(n)

    def json(self):
        try:
            return json.loads(self.read().decode("utf-8") or "null")
        except ValueError:
            return None

    def close(self):
        if self._fp is not None:
            try:
                self._fp.close()
            except Exception:                             # noqa: BLE001
                pass


def _urllib_send(method, url, headers, data, timeout):
    """One HTTPS request. Returns a Response for every HTTP status;
    raises NetworkError when Dropbox can't be reached."""
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return Response(r.status, dict(r.headers.items()), fp=r)
    except urllib.error.HTTPError as e:
        return Response(e.code, dict(e.headers.items()) if e.headers else {},
                        fp=e)
    except urllib.error.URLError as e:
        raise NetworkError(_net_msg(e.reason)) from None
    except (OSError, http.client.HTTPException) as e:
        raise NetworkError(_net_msg(e)) from None


def _net_msg(reason):
    if isinstance(reason, socket.timeout) or "timed out" in str(reason):
        return ("Dropbox didn't answer in time. Check the internet "
                "connection and try again.")
    return ("Can't reach Dropbox. Check the internet connection (or ask IT "
            "whether dropbox.com is blocked) and try again.")


transport = _urllib_send


def _arg(obj):
    """The Dropbox-API-Arg header: JSON with every non-ASCII character
    (and DEL) escaped, as Dropbox asks."""
    return json.dumps(obj, ensure_ascii=True).replace("\x7f", "\\u007f")


class _Body:
    """An upload body read from a file: reports progress and checks for
    Cancel as the HTTP layer reads it."""

    def __init__(self, f, start, length, progress=None, cancel=None,
                 done_before=0, total=0):
        self.f, self.start, self.length = f, start, length
        self.progress, self.cancel = progress, cancel
        self.done_before, self.total = done_before, total or length
        self.rewind()

    def rewind(self):
        self.f.seek(self.start)
        self.left = self.length
        return self

    def read(self, n=-1):
        if self.cancel and self.cancel():
            raise Cancelled("Cancelled.")
        if n is None or n < 0 or n > self.left:
            n = self.left
        b = self.f.read(n) if n else b""
        self.left -= len(b)
        if self.progress:
            self.progress(self.done_before + self.length - self.left,
                          self.total)
        return b

    def __len__(self):
        return self.length


def _error_message(status, summary, text=""):
    s = summary or ""
    if "missing_scope" in (s + text):
        return ("The Dropbox app is missing a permission. In the app's "
                "Permissions tab, tick files.metadata.read, "
                "files.content.read and files.content.write, Submit, then "
                "sign out and in again (File > Dropbox Settings…).")
    if status == 409:
        if "not_found" in s:
            return "That file or folder isn't in Dropbox any more."
        if "conflict" in s:
            return "A file with that name is already in Dropbox."
        if "insufficient_space" in s:
            return "The Dropbox account is full."
        if "no_write_permission" in s:
            return "You can't save in that Dropbox folder (read-only)."
        if "disallowed_name" in s or "malformed_path" in s:
            return "Dropbox doesn't allow that file or folder name."
        if "too_large" in s:
            return "The file is too large for Dropbox."
        return f"Dropbox couldn't do that ({s.split('/')[0] or 'error'})."
    if status == 401:
        return ("Dropbox signed you out. Sign in again in File > Dropbox "
                "Settings…")
    if status == 403:
        return "Dropbox refused access to that file or folder."
    if status == 429:
        return ("Dropbox is busy (too many requests). Wait a minute and "
                "try again.")
    if status >= 500:
        return (f"Dropbox had a problem (HTTP {status}). Try again in a few "
                "minutes.")
    return f"Dropbox refused the request (HTTP {status})."


# ---- the client ---------------------------------------------------------------------
class Client:
    """One signed-in Dropbox account. Thread-safe enough for one worker
    thread at a time plus the UI (the token refresh is locked)."""

    def __init__(self, key=None, tokens=None, send=None, persist=True):
        self.key = (key if key is not None else app_key()) or ""
        self.tokens = dict(tokens if tokens is not None else load_tokens())
        if self.tokens.get("app_key") not in (None, self.key):
            self.tokens = {}          # signed in with a different app
        self._send = send
        self.persist = persist
        self._access = None
        self._expires = 0.0

    # -- plumbing
    def _t(self, method, url, headers, data, timeout=TIMEOUT):
        check_allowed()
        send = self._send or transport
        return send(method, url, headers, data, timeout)

    def _form(self, fields):
        """POST to the token endpoint (codes and tokens go in the body, as
        OAuth asks - never in the URL)."""
        body = urllib.parse.urlencode(fields).encode("ascii")
        r = self._t("POST", TOKEN_URL, {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json"}, body)
        try:
            data = r.json() or {}
        finally:
            r.close()
        log.info("Dropbox oauth2/token (%s) -> %s",
                 fields.get("grant_type"), r.status)
        return r.status, data

    def exchange_code(self, code, verifier, redirect=None):
        """The code from the browser -> tokens (stored)."""
        if not self.key:
            raise DropboxError("Set the Dropbox App key first.")
        f = {"code": (code or "").strip(), "grant_type": "authorization_code",
             "client_id": self.key, "code_verifier": verifier}
        if redirect:
            f["redirect_uri"] = redirect
        status, data = self._form(f)
        if status != 200 or not data.get("access_token"):
            err = data.get("error") if isinstance(data, dict) else ""
            if err == "invalid_grant":
                raise DropboxError("That sign-in code didn't work (it may "
                                   "have expired). Try signing in again.")
            if err in ("invalid_client", "unauthorized_client"):
                raise DropboxError(
                    "Dropbox doesn't accept the App key, or the app doesn't "
                    "allow PKCE sign-in. Check the key, and in the app's "
                    "Settings tab set \"Allow public clients\" to Allow.")
            raise DropboxError(_error_message(status, str(err)))
        self._take(data)
        self.tokens.update(app_key=self.key,
                           account_id=data.get("account_id"))
        if not self.tokens.get("refresh_token"):
            raise DropboxError("Dropbox didn't give offline access. Try "
                               "signing in again.")
        self._save()

    def _take(self, data):
        self._access = data["access_token"]
        self._expires = time.time() + float(data.get("expires_in") or 14400)
        if data.get("refresh_token"):
            self.tokens["refresh_token"] = data["refresh_token"]

    def _save(self):
        if self.persist:
            save_tokens(self.tokens)

    def refresh(self):
        with _lock:
            rt = self.tokens.get("refresh_token")
            if not rt or not self.key:
                raise NotSignedIn("Sign in to Dropbox first (File > Dropbox "
                                  "Settings…).")
            status, data = self._form({"grant_type": "refresh_token",
                                       "refresh_token": rt,
                                       "client_id": self.key})
            if status == 200 and data.get("access_token"):
                self._take(data)
                return
            if status in (400, 401):
                # the sign-in was revoked (or the app changed): forget it
                self.tokens = {}
                self._access = None
                if self.persist:
                    clear_tokens()
                raise NotSignedIn("Dropbox signed you out (the sign-in was "
                                  "revoked or expired). Sign in again.")
            raise DropboxError(_error_message(status, ""))

    def _token(self):
        with _lock:
            if not self._access or time.time() > self._expires - 60:
                self.refresh()
            return self._access

    def _authed(self, method, url, headers, body, name):
        """Send with the access token; on 401 (expired_access_token...)
        refresh once and send again. `body` is bytes, None or a _Body."""
        for attempt in (0, 1):
            h = dict(headers)
            h["Authorization"] = "Bearer " + self._token()
            data = body.rewind() if isinstance(body, _Body) else body
            if isinstance(body, _Body):
                h["Content-Length"] = str(len(body))
            r = self._t(method, url, h, data)
            log.info("Dropbox %s -> %s", name, r.status)
            if r.status == 401 and attempt == 0:
                err = r.json() or {}
                r.close()
                tag = (err.get("error") or {}).get(".tag", "") \
                    if isinstance(err, dict) and \
                    isinstance(err.get("error"), dict) else ""
                if tag in ("expired_access_token", "invalid_access_token",
                           ""):
                    with _lock:
                        self._access = None
                    continue
                raise ApiError(_error_message(401, tag), 401, tag)
            return r
        raise NotSignedIn(_error_message(401, ""))

    def _raise_for(self, r):
        if r.status == 200:
            return
        text = ""
        summary = ""
        try:
            raw = r.read(65536).decode("utf-8", "replace")
            try:
                j = json.loads(raw)
                summary = j.get("error_summary", "") if isinstance(j, dict) \
                    else ""
            except ValueError:
                text = raw[:300]
        finally:
            r.close()
        msg = _error_message(r.status, summary, text)
        if r.status == 409 and "not_found" in summary:
            raise NotFound(msg, 409, summary)
        if r.status == 409 and "conflict" in summary:
            raise Conflict(msg, 409, summary)
        if r.status == 401 and "missing_scope" not in summary:
            raise NotSignedIn(msg)
        raise ApiError(msg, r.status, summary)

    def rpc(self, endpoint, args=None):
        body = json.dumps(args).encode("utf-8")      # "null" for no args
        r = self._authed("POST", API + endpoint,
                         {"Content-Type": "application/json"}, body,
                         endpoint)
        self._raise_for(r)
        try:
            return r.json() or {}
        finally:
            r.close()

    # -- account
    def current_account(self):
        a = self.rpc("users/get_current_account")
        name = (a.get("name") or {}).get("display_name") or ""
        self.tokens.update(name=name, email=a.get("email") or "",
                           account_id=a.get("account_id") or
                           self.tokens.get("account_id"))
        self._save()
        return {"name": name, "email": a.get("email") or ""}

    def revoke(self):
        """Sign out: revoke the token at Dropbox (that ends the refresh
        token too) and forget it here, even when Dropbox can't be
        reached (then the error is raised after forgetting)."""
        err = None
        try:
            if self.tokens.get("refresh_token"):
                r = self._authed("POST", API + "auth/token/revoke",
                                 {"Content-Type": "application/json"},
                                 b"null", "auth/token/revoke")
                r.close()
        except DropboxError as e:
            err = e
        finally:
            self.tokens = {}
            self._access = None
            if self.persist:
                clear_tokens()
        if err is not None and not isinstance(err, NotSignedIn):
            raise DropboxError("Signed out here, but Dropbox couldn't be "
                               "told (" + str(err) + ") - the sign-in "
                               "also ends by itself if unused.")

    # -- files
    def list_folder(self, path=""):
        """Every entry of a folder (all pages, via list_folder/continue)."""
        res = self.rpc("files/list_folder", {
            "path": normalize(path), "recursive": False,
            "include_deleted": False, "limit": 2000})
        out = list(res.get("entries") or [])
        while res.get("has_more"):
            res = self.rpc("files/list_folder/continue",
                           {"cursor": res["cursor"]})
            out.extend(res.get("entries") or [])
        return out

    def get_metadata(self, path):
        """The file's metadata, or None when it isn't there."""
        try:
            return self.rpc("files/get_metadata", {"path": normalize(path)})
        except NotFound:
            return None

    def create_folder(self, path):
        res = self.rpc("files/create_folder_v2",
                       {"path": normalize(path), "autorename": False})
        return res.get("metadata") or {}

    def download(self, path, dest, progress=None, cancel=None):
        """Download to `dest` (written as dest.part, checked against
        Dropbox's content_hash, then moved into place). Returns the
        file's metadata."""
        r = self._authed("POST", CONTENT + "files/download",
                         {"Dropbox-API-Arg": _arg({"path": path})}, None,
                         "files/download")
        self._raise_for(r)
        try:
            meta = json.loads(r.headers.get("dropbox-api-result") or "{}")
        except ValueError:
            meta = {}
        total = int(meta.get("size") or 0)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + ".part"
        h = ContentHasher()
        done = 0
        try:
            with open(part, "wb") as f:
                while True:
                    if cancel and cancel():
                        raise Cancelled("Cancelled.")
                    b = r.read(READ)
                    if not b:
                        break
                    f.write(b)
                    h.update(b)
                    done += len(b)
                    if progress:
                        progress(done, total)
            if meta.get("content_hash") and \
                    h.hexdigest() != meta["content_hash"]:
                raise DropboxError("The download was damaged on the way. "
                                   "Try again.")
            os.replace(part, dest)
        except BaseException:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        finally:
            r.close()
        return meta

    def upload(self, local, path, mode="add", rev=None, progress=None,
               cancel=None):
        """Upload a local file exactly as it is on disk (an encrypted PDF
        stays encrypted). mode: "add" (fails with Conflict when the name is
        taken), "update" with `rev` (fails with Conflict when Dropbox's
        copy isn't that rev any more). Files of 150 MB and more go up in
        an upload session. Returns the new metadata."""
        if mode == "update":
            if not rev:
                raise ValueError("update needs the rev")
            m = {".tag": "update", "update": rev}
        elif mode in ("add", "overwrite"):
            m = mode
        else:
            raise ValueError(mode)
        commit = {"path": normalize(path), "mode": m, "autorename": False,
                  "mute": False, "strict_conflict": True}
        size = os.path.getsize(local)
        expect = content_hash(local)
        with open(local, "rb") as f:
            if size < SINGLE_UPLOAD_MAX:
                meta = self._upload_one(f, size, commit, progress, cancel)
            else:
                meta = self._upload_session(f, size, commit, progress,
                                            cancel)
        if meta.get("content_hash") and meta["content_hash"] != expect:
            raise DropboxError("Dropbox received a different file than the "
                               "one saved here. Try again.")
        return meta

    def _upload_one(self, f, size, commit, progress, cancel):
        body = _Body(f, 0, size, progress, cancel)
        r = self._authed("POST", CONTENT + "files/upload", {
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": _arg(commit)}, body, "files/upload")
        return self._json_result(r)

    def _json_result(self, r):
        self._raise_for(r)
        try:
            return r.json() or {}
        finally:
            r.close()

    def _upload_session(self, f, size, commit, progress, cancel):
        oct_ = {"Content-Type": "application/octet-stream"}
        first = min(CHUNK, size)
        r = self._authed("POST", CONTENT + "files/upload_session/start",
                         dict(oct_, **{"Dropbox-API-Arg":
                                       _arg({"close": False})}),
                         _Body(f, 0, first, progress, cancel, 0, size),
                         "files/upload_session/start")
        sid = self._json_result(r).get("session_id")
        if not sid:
            raise DropboxError("Dropbox didn't start the upload. Try again.")
        offset = first
        while offset < size:
            n = min(CHUNK, size - offset)
            r = self._authed(
                "POST", CONTENT + "files/upload_session/append_v2",
                dict(oct_, **{"Dropbox-API-Arg": _arg({
                    "cursor": {"session_id": sid, "offset": offset},
                    "close": False})}),
                _Body(f, offset, n, progress, cancel, offset, size),
                "files/upload_session/append_v2")
            self._raise_for(r)
            r.close()
            offset += n
        r = self._authed("POST", CONTENT + "files/upload_session/finish",
                         dict(oct_, **{"Dropbox-API-Arg": _arg({
                             "cursor": {"session_id": sid, "offset": size},
                             "commit": commit})}),
                         b"", "files/upload_session/finish")
        return self._json_result(r)


# ---- open, re-save, save as ----------------------------------------------------------
def local_state(local, link=None):
    """"clean" (the working copy is what came from Dropbox), "changed"
    (edited here since), or "missing"."""
    link = link or read_link(local)
    if not os.path.isfile(local):
        return "missing"
    if link and content_hash(local) == link.get("content_hash"):
        return "clean"
    return "changed"


def fetch(client, path, progress=None, cancel=None, replace_local=False):
    """Download a Dropbox file to its working copy and remember where it
    came from. Raises LocalChanges when the working copy has edits not
    saved to Dropbox (unless replace_local). Returns the local path."""
    local = local_path_for(path)
    if os.path.isfile(local) and not replace_local and \
            local_state(local) == "changed":
        raise LocalChanges(
            f"Your copy of {basename(path)} has changes that aren't saved "
            "to Dropbox yet.")
    meta = client.download(path, local, progress, cancel)
    write_link(local, meta)
    return local


def resave_plan(link, remote, local_hash):
    """What "Save to Dropbox" should do for a file linked to Dropbox:
    ("missing", None)      it isn't in Dropbox any more
    ("up_to_date", rev)    Dropbox already has exactly this file
    ("update", rev)        unchanged in Dropbox since: send it (update rev)
    ("changed", rev)       someone saved a newer version meanwhile"""
    if not remote:
        return "missing", None
    rev = remote.get("rev")
    same = rev == link.get("rev") or (
        remote.get("content_hash") and
        remote.get("content_hash") == link.get("content_hash"))
    if not same:
        return "changed", rev
    if remote.get("content_hash") == local_hash:
        return "up_to_date", rev
    return "update", rev


def resave(client, local, progress=None, cancel=None, overwrite_rev=None):
    """Put a linked local file back where it came from in Dropbox. Raises
    Conflict (with .remote) when Dropbox's copy changed meanwhile, NotFound
    when it is gone. overwrite_rev: the user chose to overwrite that
    (newer) version. Returns (metadata, uploaded?)."""
    link = read_link(local)
    if not link:
        raise DropboxError("This file isn't linked to Dropbox yet.")
    path = link.get("path")
    if overwrite_rev:
        return _send_update(client, local, path, overwrite_rev, progress,
                            cancel), True
    remote = client.get_metadata(path)
    plan, rev = resave_plan(link, remote, content_hash(local))
    if plan == "missing":
        raise NotFound(f"{basename(path)} isn't in Dropbox any more (it was "
                       "moved, renamed or deleted).", 409, "path/not_found")
    if plan == "changed":
        raise Conflict(f"Someone saved a newer {basename(path)} in Dropbox "
                       "since you opened it.", remote=remote)
    if plan == "up_to_date":
        write_link(local, remote)
        return remote, False
    return _send_update(client, local, path, rev, progress, cancel), True


def _send_update(client, local, path, rev, progress, cancel):
    try:
        meta = client.upload(local, path, "update", rev, progress, cancel)
    except Conflict as e:          # changed between the check and the save
        e.remote = client.get_metadata(path)
        raise
    write_link(local, meta)
    return meta


def save_new(client, local, path, progress=None, cancel=None,
             replace_rev=None):
    """Upload a local file to a new Dropbox path (mode add, no autorename:
    Conflict when the name is taken). replace_rev: the user chose to
    replace the file already there (that rev). Links the local file to
    the result."""
    if replace_rev:
        meta = client.upload(local, path, "update", replace_rev, progress,
                             cancel)
    else:
        meta = client.upload(local, path, "add", None, progress, cancel)
    write_link(local, meta)
    return meta


def copy_name(name, who="", when=None):
    """"Plan.pdf" -> "Plan (copy by Sam 2026-10-23).pdf"."""
    stem, ext = os.path.splitext(name)
    when = when or time.strftime("%Y-%m-%d")
    tag = f"copy by {who} {when}" if who else f"copy {when}"
    tag = _BAD.sub("_", tag).replace("/", "_")
    return f"{stem} ({tag}){ext}"


# ---- the one-shot loopback server for the sign-in redirect --------------------------
_PAGE = ("<!doctype html><meta charset=utf-8><title>QuantiSheet</title>"
         "<body style='font-family:Segoe UI,Arial,sans-serif;margin:3em'>"
         "<h2>{head}</h2><p>{text}</p></body>")


class _Server(http.server.HTTPServer):
    # never share the port: another program must not be able to bind it
    # too and catch the code
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):       # Windows
            try:
                self.socket.setsockopt(socket.SOL_SOCKET,
                                       socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        http.server.HTTPServer.server_bind(self)


class LoopbackReceiver:
    """Waits for Dropbox to send the browser back to
    http://127.0.0.1:<port>/?code=...&state=... . Bound to 127.0.0.1 only;
    a request with a wrong state is refused (400) and the wait goes on.
    One code is accepted, then it stops."""

    def __init__(self, state, port=None):
        self.state = state
        self.port = redirect_port() if port is None else port
        self.code = None
        self.error = None
        self.rejected = 0
        self.done = threading.Event()
        self.server = None
        self._thread = None

    @property
    def redirect(self):
        return redirect_uri(self.server.server_address[1]
                            if self.server else self.port)

    def start(self):
        """Open the port (OSError when it can't: use the code flow)."""
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):        # the URL holds the code
                pass

            def _reply(self, status, head, text):
                body = _PAGE.format(head=head, text=text).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                if u.path != "/" or owner.done.is_set():
                    self._reply(404, "Not found", "")
                    return
                q = urllib.parse.parse_qs(u.query)
                got = (q.get("state") or [""])[0]
                if not got or not secrets.compare_digest(
                        got.encode(), owner.state.encode()):
                    owner.rejected += 1
                    self._reply(400, "This sign-in isn't QuantiSheet's",
                                "Start the Dropbox sign-in again from "
                                "QuantiSheet.")
                    return
                if q.get("error"):
                    owner.error = (q.get("error_description") or
                                   q.get("error"))[0]
                    owner.done.set()
                    self._reply(200, "Dropbox sign-in cancelled",
                                "You can close this tab.")
                    return
                code = (q.get("code") or [""])[0]
                if not code:
                    self._reply(400, "No sign-in code", "Try again.")
                    return
                owner.code = code
                owner.done.set()
                self._reply(200, "QuantiSheet is connected to Dropbox",
                            "You can close this tab and go back to "
                            "QuantiSheet.")

        self.server = _Server((LOOPBACK_HOST, self.port), Handler)
        self.server.timeout = 0.5
        self._thread = threading.Thread(target=self._serve, daemon=True,
                                        name="dropbox-signin")
        self._thread.start()
        return self

    def _serve(self):
        try:
            while not self.done.is_set() and self.server is not None:
                self.server.handle_request()
        except Exception:                                 # noqa: BLE001
            log.debug("sign-in listener stopped", exc_info=True)

    def wait(self, timeout=None):
        """The code, or None (timed out / cancelled / refused)."""
        self.done.wait(timeout)
        return self.code

    def close(self):
        self.done.set()
        srv, self.server = self.server, None
        if self._thread is not None:
            self._thread.join(2)
        if srv is not None:
            try:
                srv.server_close()
            except OSError:
                pass
