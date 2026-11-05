"""Talk to the hub on a relay (ours or a hosted one) from QuantiSheet.

    c = HubClient("wss://relay.example.com/", token="...")
    c.call("env.status", env_id=..., sender_key=...)

Uses the relay address and token from Live Collaboration's settings unless
given. Every call opens a short connection, so nothing is left running.
"""
import logging
import base64
import hashlib
import itertools
import json
import os

from .. import settings
from .hub import MAX_CHUNK

log = logging.getLogger(__name__)
_ids = itertools.count(1)


class HubClientError(RuntimeError):
    pass


def default_url():
    from .. import policy
    return (policy.get("RelayURL") or settings.get("hub_url") or
            settings.get("collab_relay") or "ws://127.0.0.1:8765").strip()


def default_token():
    from .. import policy
    return policy.get("RelayToken") or settings.get(
        "hub_token", settings.get("collab_token", "")) or ""


def web_base(url=None):
    """http(s) address of the relay's web pages for a ws(s) relay address.
    Our own relay serves pages one port up (8765 -> 8766)."""
    url = (url or default_url()).rstrip("/")
    base = settings.get("hub_web")
    if base:
        return base.rstrip("/")
    if url.startswith("wss://"):
        return "https://" + url[6:]
    if url.startswith("ws://"):
        host = url[5:]
        if host.endswith(":8765"):
            host = host[:-5] + ":8766"
        return "http://" + host
    return url


class HubClient:
    def __init__(self, url=None, token=None, timeout=60):
        self.url = url or default_url()
        self.token = default_token() if token is None else token
        self.timeout = timeout

    def _connect(self):
        try:
            from websockets.sync.client import connect
        except ImportError:
            raise HubClientError("The 'websockets' package (12 or newer) is "
                                 "needed to reach the relay.")
        from .client import InsecureRelay, check_url
        from .relaycore import auth_headers
        try:
            check_url(self.url)
        except InsecureRelay as e:
            raise HubClientError(str(e))
        from . import pin               # PR 16: pinned relay certificate
        ctx = pin.context(self.url)

        def open_(headers):
            kw = {"ssl": ctx} if ctx is not None else {}
            ws = connect(self.url, max_size=64 * 1024 * 1024,
                         open_timeout=15, close_timeout=5,
                         additional_headers=headers, **kw).__enter__()
            if ctx is not None:
                try:
                    pin.check_socket(ws.socket)
                except pin.PinMismatch:
                    ws.close()
                    raise
            return ws
        self.send_token = bool(self.token)
        try:
            try:
                return open_(auth_headers(self.token))
            except Exception as e:
                if not (self.token and "401" in str(e)):
                    raise
                # wrong relay token: carry on without it, as a phone would
                # (project passwords still work), like older versions did
                log.warning("relay token refused by %s", self.url)
                self.send_token = False
                return open_([])
        except Exception as e:
            raise HubClientError(f"Can't reach the relay at {self.url} "
                                 f"({e}).")

    def session(self):
        return _Session(self)

    def call(self, op, **args):
        with self.session() as s:
            return s.call(op, **args)

    # ---------------------------------------------------------- files
    def upload(self, key, project, path, name=None, base_version=None,
               note="", user=None, force=False, progress=None):
        name = name or os.path.basename(path)
        size = os.path.getsize(path)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        user = user or settings.author()
        with self.session() as s:
            up = s.call("proj.put_begin", project=project, key=key,
                        name=name, size=size, sha256=h.hexdigest(),
                        base_version=base_version, note=note, user=user,
                        force=force)["upload"]
            off = 0
            with open(path, "rb") as f:
                while True:
                    data = f.read(MAX_CHUNK)
                    if not data:
                        break
                    s.call("proj.put_chunk", project=project, key=key,
                           upload=up, offset=off,
                           data=base64.b64encode(data).decode("ascii"))
                    off += len(data)
                    if progress:
                        progress(off, size)
            return s.call("proj.put_end", project=project, key=key,
                          upload=up)

    def download(self, key, project, name, dest, version=None,
                 progress=None):
        tmp = dest + ".part"
        with self.session() as s, open(tmp, "wb") as f:
            off, total, v = 0, None, version
            while total is None or off < total:
                r = s.call("proj.get_chunk", project=project, key=key,
                           name=name, version=v, offset=off)
                data = base64.b64decode(r["data"])
                total, v = r["total"], r["version"]
                f.write(data)
                off += len(data)
                if progress:
                    progress(off, total)
                if not data:
                    break
        os.replace(tmp, dest)
        return v


class _Session:
    def __init__(self, client):
        self.c = client
        self.ws = None

    def __enter__(self):
        self.ws = self.c._connect()
        self.ws.send(json.dumps({"type": "api", "token": self.c.token
                                 if getattr(self.c, "send_token", True)
                                 else None,
                                 "client_id": settings.author()}))
        try:
            hello = json.loads(self.ws.recv(timeout=15))
        except Exception as e:
            self.ws.close()
            raise HubClientError(f"The relay didn't answer ({e}). Is it a "
                                 "QuantiSheet relay from this version?")
        if hello.get("type") != "api_ready":
            self.ws.close()
            raise HubClientError(hello.get("msg") or
                                 "The relay refused the connection.")
        self.authed = hello.get("authed", True)
        return self

    def __exit__(self, *exc):
        try:
            self.ws.close()
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)

    def call(self, op, **args):
        rid = next(_ids)
        self.ws.send(json.dumps({"id": rid, "op": op, "args": args}))
        while True:
            try:
                msg = json.loads(self.ws.recv(timeout=self.c.timeout))
            except TimeoutError:
                raise HubClientError("The relay took too long to answer.")
            except Exception as e:
                raise HubClientError(f"Lost the relay connection ({e}).")
            if msg.get("type") == "api_reply" and msg.get("id") == rid:
                break
        if not msg.get("ok"):
            raise HubClientError(msg.get("error") or "Request failed.")
        return msg.get("result")
