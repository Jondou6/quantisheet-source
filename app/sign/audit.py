"""Hash-chained audit log.

Each entry includes the hash of the one before, so editing or removing an
entry in the middle breaks the chain and verify() reports it. Note the
chain is not secret: someone could rewrite every entry and recompute all
the hashes. Sign the PDF after embedding the log so the signature covers it.
"""
import json
import time
import hashlib


class AuditEntry:
    def __init__(self, action, actor, detail, prev_hash=None, ts=None):
        self.ts = time.time() if ts is None else ts
        self.iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.ts))
        self.action = action
        self.actor = actor
        self.detail = detail
        self.prev_hash = prev_hash or "0" * 64
        self.hash = self._hash()

    def _hash(self):
        payload = json.dumps({"ts": self.ts, "action": self.action,
                              "actor": self.actor, "detail": self.detail,
                              "prev": self.prev_hash}, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self):
        return {"ts": self.ts, "iso": self.iso, "action": self.action,
                "actor": self.actor, "detail": self.detail,
                "prev_hash": self.prev_hash, "hash": self.hash}


class AuditLog:
    def __init__(self):
        self.entries = []

    def add(self, action, actor, detail):
        prev = self.entries[-1].hash if self.entries else None
        e = AuditEntry(action, actor, detail, prev)
        self.entries.append(e)
        return e

    def verify(self):
        prev = "0" * 64
        for e in self.entries:
            if e.prev_hash != prev or e.hash != e._hash():
                return False
            prev = e.hash
        return True

    def to_json(self):
        return json.dumps([e.to_dict() for e in self.entries], indent=2)

    @classmethod
    def from_json(cls, text):
        """Load a log. Raises ValueError if it is not a valid audit log."""
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("audit log must be a list")
        log = cls()
        for d in data:
            try:
                e = AuditEntry(d["action"], d["actor"], d["detail"],
                               d["prev_hash"], ts=d["ts"])
                e.hash = d["hash"]          # stored value; verify() rechecks
                e.iso = d.get("iso", e.iso)
            except (KeyError, TypeError) as ex:
                raise ValueError(f"bad audit entry: {ex}") from ex
            log.entries.append(e)
        return log
