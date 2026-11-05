"""Operation log for live collaboration.

Every edit is an Op. Ops are merged by id (a set union), and every client
applies them in the same order, so all copies converge on the same document.

Ordering uses a Lamport clock rather than wall-clock time, so peers whose
system clocks disagree still agree on the order of edits.
"""
import hashlib
import json
import logging
import time
import uuid

log = logging.getLogger(__name__)


def _plain(value):
    """Turn payload values (fitz.Rect, Point, tuples) into JSON-safe data.

    Normalising here means the local copy of an op is byte-for-byte what a
    peer receives, so both sides compute the same id.
    """
    def coerce(v):
        try:
            return list(v)
        except TypeError:
            raise TypeError(f"op payload value not serialisable: {v!r}")
    return json.loads(json.dumps(value, default=coerce))


def op_id(kind, page, client_id, seq, lamport, payload):
    """Content hash of everything that affects how an op is applied.

    The web client (collab/web/index.html) computes the same hash, so the
    canonical form must match JSON.stringify with sorted keys: compact
    separators and non-ASCII characters left unescaped.
    """
    key = canonical({"kind": kind, "page": page, "client_id": client_id,
                     "seq": seq, "lamport": lamport, "payload": payload})
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def js_number(x):
    """A number written exactly as JavaScript's JSON.stringify writes it:
    1.0 -> "1", 1e-7 -> "1e-7", 1e21 -> "1e+21". (Python's json writes
    "1.0" and "1e-07", which gave the desktop and the web client different
    op ids for the same edit.)"""
    import math
    from decimal import Decimal
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return "null"
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    t = Decimal(repr(abs(x))).normalize().as_tuple()
    digits = "".join(map(str, t.digits))
    k = len(digits)
    n = t.exponent + k               # where the decimal point goes
    if k <= n <= 21:
        out = digits + "0" * (n - k)
    elif 0 < n <= 21:
        out = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mant = digits if k == 1 else digits[0] + "." + digits[1:]
        out = f"{mant}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + out


def canonical(v):
    """JSON with sorted keys and JavaScript number formatting - the same
    text as canonical() in collab/web/index.html."""
    if isinstance(v, dict):
        return "{" + ",".join(
            json.dumps(str(k), ensure_ascii=False) + ":" + canonical(v[k])
            for k in sorted(v, key=str)) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(canonical(x) for x in v) + "]"
    if v is None:
        return "null"
    if isinstance(v, (bool, int, float)):
        return js_number(v)
    return json.dumps(str(v), ensure_ascii=False)


def _is_int(v, minimum):
    return isinstance(v, int) and not isinstance(v, bool) and v >= minimum


class Op:
    def __init__(self, kind, client_id, seq, page, payload=None, lamport=0,
                 ts=None):
        self.kind = kind
        self.client_id = client_id
        self.seq = seq
        self.page = page
        self.payload = payload or {}
        self.lamport = lamport
        self.ts = time.time() if ts is None else ts   # display only
        self.id = op_id(kind, page, client_id, seq, lamport, self.payload)

    def sort_key(self):
        return (self.lamport, self.client_id, self.seq)

    def to_dict(self):
        return {"id": self.id, "kind": self.kind, "client_id": self.client_id,
                "seq": self.seq, "page": self.page, "payload": self.payload,
                "lamport": self.lamport, "ts": self.ts}

    @classmethod
    def from_dict(cls, d):
        """Build an Op from untrusted data. Raises ValueError if malformed."""
        if not isinstance(d, dict):
            raise ValueError("op is not an object")
        kind, cid = d.get("kind"), d.get("client_id")
        seq, page = d.get("seq"), d.get("page")
        lamport, payload = d.get("lamport", 0), d.get("payload") or {}
        if not isinstance(kind, str) or not isinstance(cid, str):
            raise ValueError("bad kind/client_id")
        if not (_is_int(seq, 1) and _is_int(page, 0) and _is_int(lamport, 0)):
            raise ValueError("bad seq/page/lamport")
        if not isinstance(payload, dict):
            raise ValueError("bad payload")
        ts = d.get("ts")
        o = cls(kind, cid, seq, page, payload, lamport,
                ts if isinstance(ts, (int, float)) else None)
        if "id" in d and d["id"] != o.id:
            raise ValueError("op id does not match its contents")
        return o


class OpLog:
    """Per-client operation log with merge-by-id union."""

    def __init__(self, client_id=None):
        # Random per session: window handles and similar repeat across
        # machines and restarts, which would make op ids collide.
        self.client_id = str(client_id) if client_id else uuid.uuid4().hex
        self.seq = 0
        self.clock = 0
        self.ops = {}          # id -> Op

    def next_seq(self):
        self.seq += 1
        return self.seq

    def add_local(self, kind, page, **payload):
        self.clock += 1
        o = Op(kind, self.client_id, self.next_seq(), page, _plain(payload),
               self.clock)
        if o.id in self.ops:      # cannot happen unless seq was reset
            raise RuntimeError(f"duplicate op id {o.id}")
        self.ops[o.id] = o
        return o

    def add_remote(self, d):
        try:
            o = Op.from_dict(d)
        except ValueError as e:
            log.warning("dropping malformed op: %s", e)
            return None
        if o.id in self.ops:
            return None
        self.ops[o.id] = o
        self.clock = max(self.clock, o.lamport)
        if o.client_id == self.client_id:     # our own ops echoed back
            self.seq = max(self.seq, o.seq)
        return o

    def merge(self, other_dicts):
        """Add unseen ops; returns the new ones in apply order."""
        added = [o for o in map(self.add_remote, other_dicts or []) if o]
        return sorted(added, key=Op.sort_key)

    def ordered(self):
        return sorted(self.ops.values(), key=Op.sort_key)

    def since(self, clock):
        """Ops with a Lamport time after `clock`, in apply order."""
        return [o.to_dict() for o in self.ordered() if o.lamport > clock]

    def to_list(self):
        return [o.to_dict() for o in self.ordered()]
