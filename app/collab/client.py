"""WebSocket client for the collaboration relay.

Runs its own asyncio loop on a background thread. Callbacks fire on that
thread; CollabSession moves them onto the Qt GUI thread before touching any
widget or the document.
"""
import asyncio
import base64
import collections
import json
import logging
import threading
import uuid

_HEADERS_ARG = "additional_headers"
try:                                    # websockets >= 13
    from websockets.asyncio.client import connect as ws_connect
except ImportError:                     # older releases
    _HEADERS_ARG = "extra_headers"
    try:
        from websockets import connect as ws_connect
    except ImportError:
        ws_connect = None

log = logging.getLogger(__name__)

from .relaycore import (MAX_MESSAGE, Assembler, auth_headers,  # noqa: E402
                        is_loopback, split_snapshot)


class InsecureRelay(ValueError):
    pass


def check_url(url):
    """Refuse an unencrypted ws:// relay on another computer unless the
    in-house network switch (settings collab_allow_plain_lan) is on."""
    from urllib.parse import urlparse
    from .. import policy, settings
    u = urlparse(url or "")
    if u.scheme != "ws" or is_loopback(u.hostname or "") or \
            settings.get("collab_allow_plain_lan"):
        return
    # the relay the IT department set up (Group Policy RelayURL) is
    # trusted as it is (Fable review M3)
    it_url = (policy.get("RelayURL") or "").strip().rstrip("/")
    if it_url and (url or "").strip().rstrip("/") == it_url:
        return
    raise InsecureRelay(
        f"{url} is unencrypted (ws://): the relay token, room password and "
        "drawings would cross the network readable. Use a wss:// address, "
        "or, on a trusted in-house network, tick \"In-house network: allow "
        "unencrypted connections\" in Live Collaboration.")


def encode_pdf(data):
    return base64.b64encode(data).decode("ascii")


def decode_pdf(text):
    return base64.b64decode(text)


class CollabClient:
    def __init__(self, url, room="default", token=None, password=None,
                 on_snapshot=None, on_peers=None, on_cursor=None, on_event=None,
                 on_connect=None, on_error=None):
        self.url = url
        self.room = room
        self.token = token
        self.password = password
        self.on_snapshot = on_snapshot
        self.on_peers = on_peers
        self.on_cursor = on_cursor
        self.on_event = on_event
        self.on_connect = on_connect
        self.on_error = on_error
        self._loop = None
        self._thread = None
        self._ws = None
        self._outbox = collections.deque()   # never drops edits
        self._cursor = None                  # only the latest cursor matters
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.connected = False
        self.peer_count = 0
        self.error = None
        self.client_id = uuid.uuid4().hex
        self._parts = Assembler()

    # ---- lifecycle ----
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if ws_connect is None:
            self._fail("The 'websockets' package is not installed.")
            return
        try:
            check_url(self.url)
        except InsecureRelay as e:
            self._fail(str(e))
            return
        self._stop.clear()
        self.error = None
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="collab-client")
        self._thread.start()

    def stop(self):
        self._stop.set()
        loop, ws = self._loop, self._ws
        if loop and ws and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except RuntimeError:
                pass

    def _fail(self, msg):
        self.error = msg
        self.connected = False
        log.warning("collab: %s", msg)
        if self.on_error:
            self.on_error(msg)

    def _connect_kwargs(self):
        kw = {"max_size": MAX_MESSAGE, "ping_interval": 20}
        from . import pin               # PR 16: pinned relay certificate
        ctx = pin.context(self.url)
        if ctx is not None:
            kw["ssl"] = ctx
        if self.token:                  # checked before the relay accepts
            kw[_HEADERS_ARG] = auth_headers(self.token)
        return kw

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            log.exception("collab client crashed")
            self._fail(f"Connection failed: {e}")
        finally:
            self._loop.close()

    async def _main(self):
        delay = 1
        while not self._stop.is_set():
            try:
                async with ws_connect(self.url,
                                      **self._connect_kwargs()) as ws:
                    self._ws = ws
                    from . import pin
                    if pin.context(self.url) is not None:  # before anything
                        sslobj = ws.transport.get_extra_info("ssl_object")
                        pin.check_socket(sslobj)
                    await ws.send(json.dumps({
                        "type": "hello", "room": self.room,
                        "token": self.token, "password": self.password,
                        "client_id": self.client_id}))
                    self.connected = True
                    delay = 1
                    if self.on_connect:
                        self.on_connect()
                    await self._pump(ws)
            except Exception as e:                        # noqa: BLE001
                from . import pin
                if isinstance(e, pin.PinMismatch):   # never retry, say so
                    self._fail(str(e))
                    break
                if isinstance(e, OSError):
                    log.info("collab: cannot reach %s (%s)", self.url, e)
                elif "401" in str(e):   # token refused before connecting
                    self._fail("Bad relay token.")
                    break
                else:
                    log.info("collab: connection dropped (%s)", e)
            self.connected = False
            self._ws = None
            if self.error:              # relay rejected us; don't retry
                return
            if not self._stop.is_set():
                await asyncio.sleep(delay)
                delay = min(delay * 2, 15)

    async def _pump(self, ws):
        recv = asyncio.create_task(self._recv_loop(ws))
        send = asyncio.create_task(self._send_loop(ws))
        done, pending = await asyncio.wait(
            {recv, send}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        self.connected = False

    async def _recv_loop(self, ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get("type")
            try:
                if t == "error":
                    self._fail(str(msg.get("msg", "rejected by relay")))
                    await ws.close()
                    return
                if t == "snapshot" and self.on_snapshot:
                    self.on_snapshot(decode_pdf(msg.get("data", "")))
                elif t == "snapshot_part" and self.on_snapshot:
                    whole = self._parts.add(msg)
                    if whole is not None:
                        self.on_snapshot(decode_pdf(whole))
                elif t in ("peer_list", "peer_join", "peer_leave"):
                    self.peer_count = int(msg.get("count", 1))
                    if self.on_peers:
                        self.on_peers(self.peer_count)
                elif t == "cursor" and self.on_cursor:
                    self.on_cursor(msg)
                elif t == "event" and self.on_event:
                    self.on_event(msg)
            except Exception:
                log.exception("collab: error handling %r message", t)

    async def _send_loop(self, ws):
        while not self._stop.is_set():
            with self._lock:
                if self._outbox:
                    item = self._outbox.popleft()
                elif self._cursor is not None:
                    item, self._cursor = self._cursor, None
                else:
                    item = None
            if item is None:
                await asyncio.sleep(0.02)
                continue
            try:
                await ws.send(json.dumps(item))
            except Exception:
                if item.get("type") != "cursor":
                    with self._lock:
                        self._outbox.appendleft(item)   # resend on reconnect
                return

    # ---- outgoing ----
    def _enqueue(self, msg):
        with self._lock:
            self._outbox.append(msg)

    def send_snapshot(self, pdf_bytes):
        """The whole PDF; in several messages when it's bigger than the
        relay's message limit."""
        with self._lock:
            self._outbox.extend(split_snapshot(encode_pdf(pdf_bytes),
                                               uuid.uuid4().hex))

    def send_cursor(self, page, x, y, mode=None):
        with self._lock:
            self._cursor = {"type": "cursor", "client_id": self.client_id,
                            "page": page, "x": x, "y": y, "mode": mode}

    def send_event(self, name, payload=None):
        self._enqueue({"type": "event", "name": name,
                       "client_id": self.client_id, "payload": payload or {}})
