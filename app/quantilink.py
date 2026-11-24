"""Send with QuantiLink: Project Center files (RFIs, submittals, daily logs,
meeting minutes) uploaded to the office's QuantiLink server, with a share
link handed back to paste into an email (Jon, Nov 23).

QuantiLink is the office's own file-sharing server. It is reached over its
HTTP API with one shared access key for the office (Jon: "one shared key"),
sent as "Authorization: Bearer qlt_..." and never in a URL:
  POST /api/rpc {"method": "listSpaces", "args": []}       where it can go
  POST /api/upload?space=<id>&path=<folder/name>          the file's bytes
  POST /api/rpc {"method": "createShare", "args": [id, {"expiresDays": n}]}
       -> {"token": ...}; the link is <server>/s/<token>
Same name in the same folder adds a new version there, never overwrites.

The key: IT can set it for every user (policy QuantiLinkURL /
QuantiLinkKey); otherwise it is typed once in the Send window and kept
DPAPI-encrypted for this Windows user (secretstore). Network use only when
someone clicks Send or Test; IT can turn it off (DisableQuantiLink, or
OfflineMode). Never logged: the key, file contents, share links.

No Qt here (quantilink_ui.py is the window), so it is tested against a
fake server (tests/test_quantilink.py)."""
import json
import logging
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import policy, settings

log = logging.getLogger(__name__)

S_URL = "quantilink_url"
S_KEY = "quantilink_key"                 # DPAPI (secretstore)
S_SPACE = "quantilink_space"             # {"id", "name"}
S_DAYS = "quantilink_days"
DAYS = 7
TIMEOUT = 120

# Project Center tools that can be sent (Jon: RFIs, submittals, daily
# logs, meeting minutes) -> folder name on QuantiLink
KINDS = {"rfi": "RFIs", "submittal": "Submittals", "daily": "Daily Logs",
         "meeting": "Meeting Minutes"}

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class QuantiLinkError(RuntimeError):
    """str(e) is a plain message for the user."""


# ---- connection ---------------------------------------------------------------
def connection():
    """{"url", "key", "space", "days", "it"}: it is True when IT set the
    server and key (the window then doesn't let them be changed)."""
    url = (policy.get("QuantiLinkURL") or "").strip()
    key = (policy.get("QuantiLinkKey") or "").strip()
    it = bool(url and key)
    if not it:
        from . import secretstore
        url = url or str(settings.get(S_URL) or "").strip()
        key = key or secretstore.get_secret(S_KEY)
    space = settings.get(S_SPACE) or {}
    if not isinstance(space, dict):
        space = {}
    try:
        days = int(settings.get(S_DAYS) or DAYS)
    except (TypeError, ValueError):
        days = DAYS
    return {"url": url.rstrip("/"), "key": key, "space": space,
            "days": max(1, min(days, 365)), "it": it}


def save_connection(url=None, key=None, space=None, days=None):
    """Keep what the user typed (the key encrypted). Values IT set are
    not stored."""
    if url is not None:
        settings.set(S_URL, check_url(url) if url.strip() else "")
    if key is not None:
        from . import secretstore
        secretstore.set_secret(S_KEY, key.strip())
    if space is not None:
        settings.set(S_SPACE, {"id": str(space.get("id", "")),
                               "name": str(space.get("name", ""))}
                     if space else {})
    if days is not None:
        settings.set(S_DAYS, max(1, min(int(days), 365)))


def check_url(url):
    """The server address, cleaned: https, or http only on this PC."""
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "https://" + url
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("https", "http") or not p.hostname or \
            not re.fullmatch(r"[A-Za-z0-9.\-]+|[0-9A-Fa-f:]+",
                             p.hostname) or " " in url:
        raise QuantiLinkError("That isn't a server address. It looks like "
                              "https://files.yourcompany.com")
    if p.scheme == "http" and p.hostname not in LOCAL_HOSTS:
        raise QuantiLinkError("The QuantiLink server needs an https:// "
                              "address so the office key isn't sent in "
                              "the clear.")
    if p.username or p.password or p.query or p.fragment:
        raise QuantiLinkError("Type only the server address, without a "
                              "name, password or anything after it.")
    return url


# ---- the API ------------------------------------------------------------------
_STATUS = {
    400: "QuantiLink didn't accept the request.",
    401: "QuantiLink didn't accept the office key. Check it in the Send "
         "window's Connection.",
    403: "QuantiLink refused: the key can only view that folder, or the "
         "file's label doesn't allow it.",
    404: "QuantiLink couldn't find that folder or file.",
    413: "The file is too big for the QuantiLink server.",
    423: "That file is locked or on hold in QuantiLink.",
    429: "QuantiLink is busy. Try again in a minute.",
    507: "The QuantiLink server is out of storage space.",
}


class Client:
    """One QuantiLink server with the office key. opener: tests pass a
    function (request, timeout) -> response."""

    def __init__(self, url, key, opener=None, timeout=TIMEOUT):
        self.url = check_url(url)
        self.key = (key or "").strip()
        if not self.key:
            raise QuantiLinkError("There is no QuantiLink key yet. Paste "
                                  "the office key in Connection.")
        policy.check("quantilink", self.url)
        self._open = opener or urllib.request.urlopen
        self.timeout = timeout

    def _call(self, path, body, ctype, query=None):
        url = self.url + path + ("?" + urllib.parse.urlencode(query)
                                 if query else "")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", "Bearer " + self.key)
        req.add_header("Content-Type", ctype)
        req.add_header("Accept", "application/json")
        endpoint = path.rsplit("/", 1)[-1]
        try:
            r = self._open(req, timeout=self.timeout)
            status, raw = getattr(r, "status", 200), r.read()
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                raw = e.read()
            except Exception:                             # noqa: BLE001
                raw = b""
        except (urllib.error.URLError, OSError) as e:
            log.info("quantilink %s: no connection (%s)", endpoint,
                     type(e).__name__)
            raise QuantiLinkError("Couldn't reach the QuantiLink server. "
                                  "Check the address and that this PC "
                                  "is online.") from None
        log.info("quantilink %s: HTTP %s", endpoint, status)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            data = {}
        if status >= 400 or (isinstance(data, dict) and data.get("error")):
            msg = data.get("error") if isinstance(data, dict) else None
            if not isinstance(msg, str) or not msg.strip():
                msg = _STATUS.get(status, f"QuantiLink answered with an "
                                          f"error ({status}).")
            raise QuantiLinkError(msg.strip()[:500])
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data

    def rpc(self, method, *args):
        body = json.dumps({"method": method, "args": list(args)}).encode()
        return self._call("/api/rpc", body, "application/json")

    def spaces(self):
        """[{"id", "name", "personal", "role"}], the person's own files
        first."""
        got = self.rpc("listSpaces")
        if isinstance(got, dict):
            got = got.get("spaces") or []
        out = []
        for s in got or []:
            if isinstance(s, dict) and s.get("id") is not None:
                out.append({"id": str(s["id"]),
                            "name": str(s.get("name") or "My Files"),
                            "personal": bool(s.get("personal")),
                            "role": str(s.get("role") or "")})
        return sorted(out, key=lambda s: (not s["personal"],
                                          s["name"].lower()))

    def upload(self, space, path, data, ctype=None):
        ctype = ctype or (mimetypes.guess_type(path)[0] or
                          "application/octet-stream")
        got = self._call("/api/upload", data, ctype,
                         {"space": str(space), "path": path})
        if not isinstance(got, dict) or got.get("id") is None:
            raise QuantiLinkError("QuantiLink didn't say where it put the "
                                  "file.")
        return got

    def share(self, file_id, days=DAYS):
        got = self.rpc("createShare", file_id, {"expiresDays": int(days)})
        token = got.get("token") if isinstance(got, dict) else None
        if not token or not re.fullmatch(r"[A-Za-z0-9_\-]{6,200}",
                                         str(token)):
            raise QuantiLinkError("QuantiLink didn't give back a share "
                                  "link.")
        return f"{self.url}/s/{token}"


# ---- what is sent -------------------------------------------------------------
def clean_part(text, n=80):
    """One folder or file name: no slashes or characters QuantiLink or
    Windows can't keep."""
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:n].strip(" .") or "item"


def remote_path(project, kind, name):
    """<Project>/<RFIs>/<file> on QuantiLink."""
    return "/".join((clean_part(project), clean_part(KINDS.get(kind, kind)),
                     clean_part(name, 120)))


def record_label(kind, rec):
    from .pm import schema
    t = schema.TOOLS[kind]
    tf = t.get("title_field", "title")
    title = str(rec.get(tf) or "").strip()
    no = str(rec.get("_no") or "").strip()
    return " ".join(x for x in (t["one"], no, "-" if title and no else "",
                                title) if x).strip()


def gather(store, kind, recs, attachments=True):
    """[(local path, remote name)] for the records: each one's PDF (as
    printed from Project Center) and, if asked, its attachments."""
    from .pm import report, schema
    out = []
    t = schema.TOOLS[kind]
    att_fields = [f["key"] for f in t["fields"]
                  if f["type"] == "attachments"]
    for rec in recs:
        label = record_label(kind, rec)
        pdf = report.temp_pdf(store, kind, rec)
        out.append((pdf, clean_part(label, 110) + ".pdf"))
        if not attachments:
            continue
        for fk in att_fields:
            for ref in rec.get(fk) or []:
                if not isinstance(ref, dict) or not ref.get("sha256"):
                    continue
                try:
                    path = store.attachment_path(ref)
                except Exception as e:                    # noqa: BLE001
                    out.append((None, f"{label} - {ref.get('name', '')}: "
                                      f"{e}"))
                    continue
                out.append((path, clean_part(f"{label} - "
                                             f"{ref.get('name') or 'file'}",
                                             120)))
    return out


def send(client, space, project, kind, items, days=DAYS, progress=None):
    """Upload each (path, name) and make its share link. Returns
    [{"name", "link"} or {"name", "error"}]; one failure doesn't stop the
    rest. progress(i, n, name) is called before each file."""
    out = []
    n = len(items)
    for i, (path, name) in enumerate(items):
        if progress:
            progress(i, n, name)
        if path is None:                     # attachment not on this PC
            out.append({"name": name.split(":")[0], "error":
                        name.split(":", 1)[-1].strip() or "not on this PC"})
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
            got = client.upload(space, remote_path(project, kind, name),
                                data)
            out.append({"name": name,
                        "link": client.share(got["id"], days)})
        except (QuantiLinkError, OSError) as e:
            out.append({"name": name, "error": str(e)})
    if progress:
        progress(n, n, "")
    return out


def links_text(results, days=DAYS):
    """The text to paste into an email."""
    ok = [r for r in results if r.get("link")]
    if not ok:
        return ""
    lines = [f"{r['name']}: {r['link']}" for r in ok]
    lines.append("")
    lines.append(f"Links work for {days} day{'s' if days != 1 else ''}.")
    return "\n".join(lines)
