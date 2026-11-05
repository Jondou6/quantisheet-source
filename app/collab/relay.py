"""Collaboration relay: forwards messages between everyone in a room, and
serves the mobile web app (collab/web) over plain HTTP.

Rooms are protected by a password: the first person to join a room sets
it, and everyone after must supply the same one. An optional server-wide
token can be required as well. Traffic is encrypted (wss://, https://)
when a certificate is set (settings relay_cert / relay_key); otherwise it
runs only on this computer, or on the LAN after an explicit opt-in,
so use this on networks you trust, or put it behind a TLS proxy.
"""
import asyncio
import functools
import http.server
import json
import logging
import os
import socket
import threading

from .. import settings
from . import hub as hubmod
from .relaycore import FORWARDED, MAX_MESSAGE, Rooms  # noqa: F401

try:                                    # websockets >= 13
    from websockets.asyncio.server import serve as _serve
except ImportError:                     # older releases
    try:
        from websockets import serve as _serve
    except ImportError:
        _serve = None

log = logging.getLogger(__name__)

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
HUB_DIR = os.path.join(settings.DIR, "hub")       # the per-user data folder
_HUBS = {}


def get_hub(data_dir=None):
    """One Hub per data folder (the WebSocket and HTTP sides share it)."""
    d = os.path.abspath(data_dir or HUB_DIR)
    if d not in _HUBS:
        _HUBS[d] = hubmod.Hub(d)
    return _HUBS[d]


class Relay:
    def __init__(self, host="0.0.0.0", ws_port=8765, http_port=8766,
                 token=None, data_dir=None, ssl_ctx=None):
        self.ssl_ctx = ssl_ctx
        self.host = host
        self.ws_port = ws_port
        self.http_port = http_port
        self.token = token
        self.room_set = Rooms(token)
        self.hub = get_hub(data_dir)

    async def _ws(self, ws, path=None):     # `path` only on old websockets
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

    async def run(self, ready=None):
        if _serve is None:
            raise RuntimeError("The 'websockets' package is not installed.")
        kw = {"ssl": self.ssl_ctx} if self.ssl_ctx else {}
        async with _serve(self._ws, self.host, self.ws_port,
                          max_size=MAX_MESSAGE, ping_interval=20, **kw):
            if ready:
                ready()
            await asyncio.Future()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    hub = None

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/hub/") and self.hub is not None:
            status, ctype, body = self.hub.get(self.path)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()


def _http_server(host, port, data_dir=None, ssl_ctx=None):
    cls = type("_Handler", (_QuietHandler,), {"hub": get_hub(data_dir)})
    handler = functools.partial(cls, directory=WEB_DIR)
    srv = http.server.ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    if ssl_ctx is not None:
        srv.socket = ssl_ctx.wrap_socket(srv.socket, server_side=True)
    return srv


def tls_context(cert=None, key=None):
    """SSL context for a configured certificate (settings relay_cert /
    relay_key), or None."""
    from .. import settings
    cert = cert or settings.get("relay_cert")
    key = key or settings.get("relay_key")
    if not (cert and key and os.path.isfile(cert) and os.path.isfile(key)):
        return None
    import ssl
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


class RelayHandle:
    """A relay running on background threads (as started from the GUI)."""

    def __init__(self, host, ws_port, http_port, token=None, tls=False):
        self.host, self.ws_port, self.http_port = host, ws_port, http_port
        self.token = token
        self.tls = tls

    @property
    def lan_ip(self):
        return lan_ip()

    def urls(self):
        """(desktop address, phone link). The phone link carries the relay
        token after "#", which browsers never send to a server or write to
        its logs; the page removes it from the address bar."""
        ip = lan_ip()
        s = "s" if self.tls else ""
        web = f"http{s}://{ip}:{self.http_port}/"
        if self.token:
            web += f"#t={self.token}"
        return (f"ws{s}://{ip}:{self.ws_port}", web)


def start_background(host="0.0.0.0", ws_port=8765, http_port=8766, token=None,
                     timeout=5, data_dir=None, allow_plain=None, ssl_ctx=None):
    """Start relay + web server on daemon threads. Raises if a port is busy.
    A relay other computers can reach must have a token (relaycore
    check_bind) and be encrypted, unless plain connections were allowed
    for an in-house network (settings collab_allow_plain_lan)."""
    from .relaycore import check_bind, check_transport
    from .. import settings
    check_bind(host, token)
    if ssl_ctx is None:
        ssl_ctx = tls_context()
    if allow_plain is None:
        allow_plain = bool(settings.get("collab_allow_plain_lan"))
    warn = check_transport(host, ssl_ctx is not None, allow_plain)
    if warn:
        log.warning(warn)
    httpd = _http_server(host, http_port, data_dir, ssl_ctx)   # OSError if busy
    threading.Thread(target=httpd.serve_forever, daemon=True,
                     name="relay-http").start()

    started, failure = threading.Event(), []

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                Relay(host, ws_port, http_port, token, data_dir, ssl_ctx)
                .run(started.set))
        except Exception as e:
            failure.append(e)
            started.set()

    threading.Thread(target=run, daemon=True, name="relay-ws").start()
    started.wait(timeout)
    if failure:
        httpd.shutdown()
        raise failure[0]
    return RelayHandle(host, ws_port, http_port, token, ssl_ctx is not None)


def run_relay(host="0.0.0.0", ws_port=8765, http_port=8766, token=None,
              data_dir=None, ssl_ctx=None):
    """Run relay + web server in the foreground (blocks). With ssl_ctx
    (tls_context(cert, key)) both are encrypted: wss:// and https://."""
    from .relaycore import check_bind, check_transport
    check_bind(host, token)
    warn = check_transport(host, ssl_ctx is not None, True)
    if warn:
        log.warning(warn)
    httpd = _http_server(host, http_port, data_dir, ssl_ctx)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log.info("relay on %s:%s (web %s), %s, data in %s", host, ws_port,
             http_port, "TLS" if ssl_ctx else "no TLS",
             os.path.abspath(data_dir or HUB_DIR))
    asyncio.run(Relay(host, ws_port, http_port, token, data_dir,
                      ssl_ctx).run())


def lan_ip():
    """Best guess at this machine's address on the local network."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))     # no packet is actually sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
