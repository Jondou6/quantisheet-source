"""Live accounting-system connectors (P3-03) - guard only.

Decision 15 = A: sync is file-based (erpsync.py). No live connector ships.
This module holds the rules any future connector must pass, so one can only
be added together with a written agreement with the accounting-system
vendor:
  * a stored agreement reference (the vendor's partner/API agreement) and
    stored credentials are both required, or nothing runs;
  * the endpoint must be https;
  * credentials are encrypted at rest with the company data key (protected
    by Windows DPAPI on Windows) and never written to the audit trail, logs,
    sync runs or error messages;
  * a system with no connector code shipped is refused.
"""
from __future__ import annotations

import logging
import urllib.parse

from . import clock

log = logging.getLogger(__name__)
REGISTRY: dict = {}        # system -> callable(endpoint, credentials) -> dict


class ConnectorError(RuntimeError):
    pass


def _redact(text, secret) -> str:
    text = str(text)
    if secret:
        text = text.replace(secret, "[credentials]")
    return text


def save(office, system, endpoint="", agreement_ref="", credentials=None):
    """Store a connector's settings; credentials are encrypted."""
    office.require("settings.edit", "connector", system)
    if endpoint:
        p = urllib.parse.urlparse(endpoint)
        if p.scheme != "https" or not p.hostname:
            raise ConnectorError("A connector endpoint must be https.")
    cur = office.db.one("SELECT * FROM connectors WHERE system = ?",
                        (system,))
    fields = {"endpoint": endpoint, "agreement_ref": agreement_ref.strip()}
    if credentials is not None:
        fields["credentials"] = office.crypto.encrypt(credentials) \
            if credentials else None
    with office.db.tx():
        if cur:
            office.db.update("connectors", cur["id"], **fields)
            cid = cur["id"]
        else:
            cid = office.db.insert("connectors", system=system,
                                   status="Not connected", **fields)
        office.audit("change", "connector", cid, None,
                     {"system": system, "endpoint": endpoint,
                      "agreement_ref": fields["agreement_ref"],
                      "credentials": "(stored, encrypted)" if credentials
                      else "(none)"})
    return cid


def status(office, system) -> str:
    c = office.db.one("SELECT * FROM connectors WHERE system = ?", (system,))
    if system not in REGISTRY:
        return "File-based only (no live connector)"
    if not c or not c["agreement_ref"] or not c["credentials"]:
        return "Needs agreement reference and credentials"
    return c["status"] or "Ready"


def run(office, system, **kw) -> dict:
    """Run a live connector. Refused unless an agreement reference and
    credentials are stored and connector code exists for the system."""
    office.require("sync.run", "connector", system)
    c = office.db.one("SELECT * FROM connectors WHERE system = ? AND "
                      "deleted = 0", (system,))
    if not c or not (c["agreement_ref"] or "").strip():
        office.audit("denied", "connector", system, None,
                     {"reason": "no agreement reference"})
        raise ConnectorError(f"{system}: no vendor agreement reference is "
                             f"stored; live connectors need one. Use file "
                             f"sync instead.")
    if not c["credentials"]:
        office.audit("denied", "connector", system, None,
                     {"reason": "no credentials"})
        raise ConnectorError(f"{system}: no credentials are stored.")
    fn = REGISTRY.get(system)
    if fn is None:
        raise ConnectorError(f"No live connector is included for {system} "
                             f"(file-based sync only).")
    secret = office.crypto.decrypt(c["credentials"])
    try:
        result = fn(c["endpoint"], secret, **kw)
        ok, msg = True, _redact(result.get("message", "ok"), secret)
    except Exception as e:                                # noqa: BLE001
        ok, msg, result = False, _redact(e, secret), {}
        log.warning("connector %s failed: %s", system, msg)
    with office.db.tx():
        office.db.update("connectors", c["id"], last_run=clock.iso_now(),
                         last_result=msg, status="Ready" if ok else "Error")
        office.audit("connector run", "connector", c["id"], None,
                     {"system": system, "ok": ok, "message": msg})
    if not ok:
        raise ConnectorError(f"{system}: {msg}")
    return {k: _redact(v, secret) if isinstance(v, str) else v
            for k, v in result.items()}
