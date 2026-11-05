"""Rooms for the collaboration relays: passwords, who may open a room,
brute-force lockout and message limits.

Shared by Live Collaboration's own relay (app/collab/relay.py) and the
hostable server (server/relay_server.py). This file is the only one to
edit: server/relaycore.py is generated from it by tools/sync_server.py
(a test fails if they differ), so the server folder deploys on its own.

Rules:
* every message is at most MAX_MESSAGE (16 MB); big PDF snapshots travel
  as several "snapshot_part" messages;
* a room is opened (and its password set) only by someone holding the
  relay token, or by a client on the relay's own computer - so nobody on
  the network can grab a room name before its host;
* 5 wrong passwords or tokens from one address within a minute lock that
  address out for a minute.
"""
import collections
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time

log = logging.getLogger("relay")

MAX_MESSAGE = 16 * 1024 * 1024
FORWARDED = ("snapshot", "snapshot_part", "cursor", "event")
MAX_TRIES = 5
WINDOW = 60.0
LOCKOUT = 60.0


def pw_hash(salt, password):
    return hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                               salt, 100_000)


def is_loopback(ip):
    try:
        return ipaddress.ip_address(str(ip).split("%")[0]).is_loopback
    except ValueError:
        return str(ip) == "localhost"


# Which proxies may set X-Forwarded-For (0.13.5 security fix). Only a peer
# on this computer (loopback) is believed by default: a LAN or internet
# client typing its own header could otherwise rotate addresses and dodge
# the wrong-password lockout. A relay behind a hosting proxy (Fly, Render,
# nginx on another box) names that proxy's address or network in the
# TRUSTED_PROXIES environment variable (comma-separated IPs or CIDRs, e.g.
# "10.0.0.0/8,fd00::/8"), or the app passes a setting to
# set_trusted_proxies(). Loopback is always trusted.
TRUSTED_PROXIES_ENV = "TRUSTED_PROXIES"
_PROXY_OVERRIDE = None
_PROXY_CACHE = {"raw": None, "nets": []}


def _parse_proxies(raw):
    nets = []
    for part in str(raw or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            log.warning("TRUSTED_PROXIES: ignoring %r (not an IP or "
                        "network)", part)
    return nets


def set_trusted_proxies(value):
    """Use these proxies (list or comma-separated text) instead of the
    TRUSTED_PROXIES environment variable; None goes back to the variable."""
    global _PROXY_OVERRIDE
    if value is None:
        _PROXY_OVERRIDE = None
    else:
        if not isinstance(value, str):
            value = ",".join(str(v) for v in value)
        _PROXY_OVERRIDE = _parse_proxies(value)


def trusted_proxies():
    """The configured proxy networks (loopback is trusted on top)."""
    if _PROXY_OVERRIDE is not None:
        return list(_PROXY_OVERRIDE)
    import os
    raw = os.environ.get(TRUSTED_PROXIES_ENV, "")
    if raw != _PROXY_CACHE["raw"]:
        _PROXY_CACHE.update(raw=raw, nets=_parse_proxies(raw))
    return list(_PROXY_CACHE["nets"])


def is_trusted_proxy(peer):
    peer = str(peer or "")
    try:
        ip = ipaddress.ip_address(peer.split("%")[0])
    except ValueError:
        return peer == "localhost"
    if ip.is_loopback:
        return True
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
        if ip.is_loopback:
            return True
    return any(ip.version == n.version and ip in n
               for n in trusted_proxies())


def forwarded_ip(peer, xff):
    """The client's address from the connecting peer and its
    X-Forwarded-For header. The header is only believed when the peer is
    on this computer or in TRUSTED_PROXIES; then its LAST hop is used - the
    one that proxy added. Earlier hops are whatever the client typed, and a
    header from any other peer is ignored, so neither "X-Forwarded-For:
    127.0.0.1" nor a rotating fake address can pass for another caller or
    dodge the lockout."""
    peer = str(peer or "")
    hops = [h.strip() for h in str(xff or "").split(",") if h.strip()]
    if not hops:
        return peer
    return hops[-1] if is_trusted_proxy(peer) else peer


# ---- relay token and transport --------------------------------------------------

def request_headers(ws):
    """The WebSocket handshake headers (any websockets version), or {}."""
    try:
        h = (getattr(getattr(ws, "request", None), "headers", None) or
             getattr(ws, "request_headers", None))
        return h if h is not None else {}
    except Exception:
        return {}


def bearer(headers):
    """Token from an "Authorization: Bearer ..." header, or ""."""
    try:
        v = str((headers or {}).get("Authorization") or "")
    except Exception:
        return ""
    return v[7:].strip() if v[:7].lower() == "bearer " else ""


def given_token(hello, headers=None):
    """The relay token a client gave: the Authorization header first (the
    desktop app), else the first message (browsers can't set headers on a
    WebSocket, and older QuantiSheet versions)."""
    return bearer(headers) or str((hello or {}).get("token") or "")


def auth_headers(token):
    """Handshake headers that carry the relay token."""
    return [("Authorization", f"Bearer {token}")] if token else []


def check_transport(host, tls, allow_plain):
    """A relay other computers can reach should be encrypted (wss://).
    Plain ws:// off this computer only with an explicit opt-in (an
    in-house network); returns the warning to show/log then."""
    if tls or is_loopback(host):
        return None
    msg = (f"The relay on {host!r} is unencrypted (ws://): anyone on the "
           "network can read the relay token, room passwords and drawings. ")
    if not allow_plain:
        raise SystemExit(
            msg + "Configure a certificate (TLS_CERT/TLS_KEY) or put it behind "
            "an HTTPS proxy (TLS_PROXY=1). On a trusted in-house network set "
            "ALLOW_PLAIN_WS=1 (or tick \"In-house network: allow unencrypted "
            "connections\" in QuantiSheet).")
    return msg + "Allowed for an in-house network only."


def remote_ip(ws):
    """The caller's address (see forwarded_ip for proxies)."""
    try:
        peer = str(ws.remote_address[0])
    except Exception:
        peer = ""
    try:
        h = (getattr(getattr(ws, "request", None), "headers", None) or
             getattr(ws, "request_headers", None))
        if h is not None:
            return forwarded_ip(peer, h.get("X-Forwarded-For"))
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    return peer


def _direct_local(ws):
    try:
        peer = str(ws.remote_address[0])
    except Exception:
        return True                       # tests / in-process callers
    h = request_headers(ws) if "request_headers" in globals() else {}
    try:
        fwd = (h or {}).get("X-Forwarded-For")
    except Exception:
        fwd = None
    return is_loopback(peer) and not fwd


class Room:
    def __init__(self, password):
        self.salt = secrets.token_bytes(16)
        self.pw = pw_hash(self.salt, password)
        self.clients = {}               # websocket -> client_id

    def check(self, password):
        return hmac.compare_digest(self.pw, pw_hash(self.salt, password))


class Guard:
    """Counts failed tries per address."""

    def __init__(self, tries=MAX_TRIES, window=WINDOW, lockout=LOCKOUT,
                 clock=time.monotonic):
        self.tries, self.window, self.lockout = tries, window, lockout
        self.clock = clock
        self.fails = collections.defaultdict(collections.deque)
        self.locked = {}

    def blocked(self, ip):
        until = self.locked.get(ip)
        if until is None:
            return False
        if self.clock() >= until:
            del self.locked[ip]
            self.fails.pop(ip, None)
            return False
        return True

    def fail(self, ip):
        now = self.clock()
        q = self.fails[ip]
        q.append(now)
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.tries:
            self.locked[ip] = now + self.lockout
        if len(self.fails) > 10000:         # don't grow without bound
            self.fails.clear()
        if len(self.locked) > 10000:        # drop lockouts that ran out
            self.locked = {k: v for k, v in self.locked.items() if v > now}


class Rooms:
    def __init__(self, token=None):
        self.token = token
        self.rooms = {}
        self.guard = Guard()

    async def _error(self, ws, msg):
        try:
            await ws.send(json.dumps({"type": "error", "msg": msg}))
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)

    async def serve(self, ws, hello, ip=None):
        """Run one client that sent a "hello" until it leaves."""
        ip = remote_ip(ws) if ip is None else ip
        if self.guard.blocked(ip):
            await self._error(ws, "Too many wrong passwords. Wait a minute "
                                  "and try again.")
            return
        token_ok = False
        if self.token:
            if not hmac.compare_digest(
                    given_token(hello, request_headers(ws)), self.token):
                self.guard.fail(ip)
                await self._error(ws, "Bad relay token.")
                return
            token_ok = True
        name = str(hello.get("room") or "default")[:100]
        password = str(hello.get("password") or "")
        room = self.rooms.get(name)
        if room is None:
            # "this computer" = a direct loopback connection with no
            # X-Forwarded-For at all: a LAN machine sending the header
            # "127.0.0.1" (believed by forwarded_ip only from a trusted
            # proxy) must not count as local (review 3 #21, residual)
            if not (token_ok or (is_loopback(ip) and _direct_local(ws))):
                await self._error(
                    ws, f"There's no session called {name!r} yet. The host "
                        "has to start it first.")
                return
            room = self.rooms[name] = Room(password)
        elif not room.check(password):
            self.guard.fail(ip)
            await self._error(ws, "Wrong room password.")
            return
        cid = str(hello.get("client_id") or "?")[:64]
        room.clients[ws] = cid
        log.info("room %s: %s joined (%d)", name, cid, len(room.clients))
        await self.broadcast(room, {"type": "peer_join",
                                    "count": len(room.clients)})
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("type") in FORWARDED:
                    msg["client_id"] = cid      # senders can't impersonate
                    await self.broadcast(room, msg, skip=ws)
        except Exception as e:
            log.info("room %s: %s dropped (%s)", name, cid, e)
        finally:
            room.clients.pop(ws, None)
            if room.clients:
                await self.broadcast(room, {"type": "peer_leave",
                                            "count": len(room.clients)})
            elif self.rooms.get(name) is room:
                del self.rooms[name]          # empty room: password resets

    async def broadcast(self, room, msg, skip=None):
        data = json.dumps(msg)
        for w in list(room.clients):
            if w is skip:
                continue
            try:
                await w.send(data)
            except Exception:
                room.clients.pop(w, None)


def check_bind(host, token):
    """A relay reachable from other computers must have a token."""
    if not token and not is_loopback(host):
        raise SystemExit(
            "RELAY_TOKEN is required when the relay listens on "
            f"{host!r} (reachable from other computers). Set RELAY_TOKEN, "
            "or HOST=127.0.0.1 behind a proxy that adds its own login.")


def safe_join(base, path):
    """`path` inside folder `base`, or None if it would leave it."""
    import os
    base = os.path.realpath(base)
    full = os.path.realpath(os.path.join(base, path.lstrip("/\\")))
    try:
        if os.path.commonpath([full, base]) != base:
            return None
    except ValueError:                  # different drives on Windows
        return None
    return full


# ---- big snapshots in parts ------------------------------------------------------
PART = 8 * 1024 * 1024                  # base64 characters per part


def split_snapshot(b64, sid):
    """[message, ...] carrying base64 text `b64`: one "snapshot" when it
    fits in a message, else "snapshot_part"s."""
    if len(b64) <= PART:
        return [{"type": "snapshot", "data": b64}]
    n = (len(b64) + PART - 1) // PART
    return [{"type": "snapshot_part", "sid": sid, "i": i, "n": n,
             "data": b64[i * PART:(i + 1) * PART]} for i in range(n)]


class Assembler:
    """Puts snapshot_parts back together; one snapshot at a time."""
    MAX_PARTS = 256                     # 2 GB of base64

    def __init__(self):
        self.sid, self.n, self.parts = None, 0, {}

    def add(self, msg):
        """The whole base64 text once the last part is in, else None."""
        try:
            sid, i, n = str(msg["sid"]), int(msg["i"]), int(msg["n"])
            data = str(msg.get("data") or "")
        except (KeyError, TypeError, ValueError):
            return None
        if not (0 < n <= self.MAX_PARTS and 0 <= i < n):
            return None
        if sid != self.sid:
            self.sid, self.n, self.parts = sid, n, {}
        self.parts[i] = data
        if len(self.parts) == self.n:
            out = "".join(self.parts[k] for k in range(self.n))
            self.sid, self.n, self.parts = None, 0, {}
            return out
        return None


__all__ = ["MAX_MESSAGE", "FORWARDED", "Rooms", "Room", "Guard",
           "is_loopback", "remote_ip", "forwarded_ip", "check_bind",
           "trusted_proxies", "set_trusted_proxies", "is_trusted_proxy",
           "safe_join",
           "request_headers", "bearer", "given_token", "auth_headers",
           "check_transport",
           "split_snapshot", "Assembler", "PART"]
