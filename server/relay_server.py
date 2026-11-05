"""QuantiSheet collaboration relay for hosting (a VPS, Fly.io, Render...).

One port carries both the WebSocket relay and the mobile web app, so it
works behind a single TLS proxy or a platform that gives you one port.

    PORT=8765 RELAY_TOKEN=secret python relay_server.py

Environment:
  PORT          port to listen on (default 8765)
  HOST          address to bind (default 0.0.0.0)
  RELAY_TOKEN   if set, every client must give it (Live Collaboration >
                Relay token)
  WEB_DIR       folder of the mobile web app (default ./web)
  DATA_DIR      where the hub keeps signature requests, project files and
                punch items (default ./data). On Fly.io or Render put this
                on a persistent volume or disk.

  TLS_CERT, TLS_KEY  certificate and key files: serve wss:// directly
  TLS_PROXY     1 when a platform or proxy in front does HTTPS (Fly.io,
                Render, Caddy) and this process listens plain behind it
  ALLOW_PLAIN_WS  1 to listen unencrypted on a network address anyway
                (a trusted in-house network only; a warning is logged)

In QuantiSheet: Tools > Live Collaboration > Join, relay address
wss://your-host/. The desktop app sends the relay token in an
"Authorization: Bearer" header, checked before the connection is
accepted; browsers send it in their first message.

RELAY_TOKEN is required unless HOST is a loopback address. Rooms are
password protected: whoever opens a room (a token holder) sets the
password, everyone after must give the same one; 5 wrong tries from one
address lock it out for a minute. Messages are limited to 16 MB (big PDF
snapshots are sent in parts). Live sessions are only
forwarded, never stored. The hub (hub.py) stores what must outlast a
session: e-signature requests, project files and punch items.
"""
import asyncio
import json
import logging
import mimetypes
import os
import signal

try:
    import hub as hubmod
    import relaycore
except ImportError:                            # running from the repo
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "..", "app", "collab"))
    import hub as hubmod
    import relaycore

try:                                           # websockets >= 13
    from websockets.asyncio.server import serve
    from websockets.datastructures import Headers
    from websockets.http11 import Response
    NEW_API = True
except ImportError:                            # older releases
    from websockets import serve
    NEW_API = False

log = logging.getLogger("relay")
MAX_MESSAGE = relaycore.MAX_MESSAGE
FORWARDED = relaycore.FORWARDED
WEB_DIR = os.environ.get("WEB_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "web")
HUB = None


class Relay:
    def __init__(self, token=None, data_dir=None):
        global HUB, HUB_RELAY
        HUB_RELAY = self
        self.token = token
        self.room_set = relaycore.Rooms(token)
        self.hub = HUB = hubmod.Hub(data_dir or os.environ.get("DATA_DIR") or
                                    os.path.join(os.path.dirname(
                                        os.path.abspath(__file__)), "data"))

    async def handler(self, ws, path=None):
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 15))
        except Exception:
            return
        if isinstance(hello, dict) and hello.get("type") == "api":
            try:
                await hubmod.api_session(self.hub, ws, hello,
                                         hubmod.ws_context(ws), self.token)
            except Exception as e:
                log.info("hub client dropped (%s)", e)
            return
        if not isinstance(hello, dict) or hello.get("type") != "hello":
            return
        await self.room_set.serve(ws, hello)

    @property
    def rooms(self):
        return self.room_set.rooms


def _file_for(path):
    path = path.split("?", 1)[0]
    if path in ("", "/"):
        path = "/index.html"
    from urllib.parse import unquote
    full = relaycore.safe_join(WEB_DIR, unquote(path))
    if full is None or not os.path.isfile(full):
        return None
    return full


def _http(path):
    """(status, content type, body) for a plain HTTP request."""
    if path.startswith("/healthz"):
        return 200, "text/plain", b"ok"
    if path.startswith("/hub/") and HUB is not None:
        return HUB.get(path)
    full = _file_for(path)
    if full is None:
        return 404, "text/plain", b"not found"
    with open(full, "rb") as f:
        body = f.read()
    ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
    return 200, ctype, body


def _is_upgrade(headers):
    return "websocket" in str(headers.get("Upgrade", "")).lower()


def _bad_bearer(headers):
    """True when a relay token is required and the handshake carries a
    wrong one (no header at all is left to the first message)."""
    token = getattr(HUB_RELAY, "token", None)
    given = relaycore.bearer(headers)
    if not token or not given:
        return False
    import hmac
    return not hmac.compare_digest(given, token)


HUB_RELAY = None


def tls_context():
    """SSL context from TLS_CERT / TLS_KEY, or None."""
    cert, key = os.environ.get("TLS_CERT"), os.environ.get("TLS_KEY")
    if not (cert and key):
        return None
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


if NEW_API:
    def process_request(connection, request):
        if _is_upgrade(request.headers):
            if _bad_bearer(request.headers):
                return Response(401, "Unauthorized", Headers(
                    [("Content-Length", "17")]), b"Bad relay token.\n")
            return None
        status, ctype, body = _http(request.path)
        headers = Headers([("Content-Type", ctype),
                           ("Content-Length", str(len(body))),
                           ("Cache-Control", "no-cache")])
        return Response(status, {200: "OK", 403: "Forbidden"}.get(
            status, "Not Found"),
                        headers, body)
else:
    async def process_request(path, request_headers):
        if _is_upgrade(request_headers):
            if _bad_bearer(request_headers):
                return 401, [("Content-Length", "17")], b"Bad relay token.\n"
            return None
        status, ctype, body = _http(path)
        return status, [("Content-Type", ctype),
                        ("Content-Length", str(len(body)))], body


async def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8765"))
    token = os.environ.get("RELAY_TOKEN") or None
    relaycore.check_bind(host, token)
    ctx = tls_context()
    warn = relaycore.check_transport(
        host, tls=ctx is not None or os.environ.get("TLS_PROXY") == "1",
        allow_plain=os.environ.get("ALLOW_PLAIN_WS") == "1")
    if warn:
        log.warning(warn)
    relay = Relay(token)
    stop = asyncio.get_running_loop().create_future()
    for sig in (getattr(signal, "SIGTERM", None),
                getattr(signal, "SIGINT", None)):
        if sig is None:
            continue
        try:
            asyncio.get_running_loop().add_signal_handler(
                sig, lambda: stop.done() or stop.set_result(None))
        except NotImplementedError:          # Windows
            pass
    async with serve(relay.handler, host, port, max_size=MAX_MESSAGE,
                     ping_interval=20, process_request=process_request,
                     ssl=ctx):
        log.info("QuantiSheet relay on %s:%d (%s, token %s)", host, port,
                 "wss" if ctx else "ws", "required" if relay.token else "off")
        await stop


if __name__ == "__main__":
    asyncio.run(main())
