"""Live collaboration for one open document.

Protocol (all messages go through the relay):
  op             one new edit, broadcast as it happens
  ops            a client's whole log, sent on (re)connect and when someone
                 joins; receivers ignore ops they already have
  request_snapshot / snapshot + snapshot_ops
                 a joining peer gets the host's document, plus the ids of the
                 ops already baked into it, then replays anything else

Every client applies ops in the same Lamport order, and applying is
idempotent (see app.annotate), so all copies converge without duplicates.
"""
import logging

import fitz

from .client import CollabClient
from .oplog import OpLog
from . import merge

log = logging.getLogger(__name__)

try:
    from PySide6.QtCore import QObject, Signal, Slot

    class _GuiBridge(QObject):
        """Runs callables on the GUI thread (where this object was made)."""
        call = Signal(object)

        def __init__(self):
            super().__init__()
            self.call.connect(self._run)

        @Slot(object)
        def _run(self, fn):
            try:
                fn()
            except Exception:
                log.exception("collab callback failed")

        def post(self, fn):
            self.call.emit(fn)
except ImportError:                     # headless use (tests)
    class _GuiBridge:
        def post(self, fn):
            fn()


class CollabSession:
    def __init__(self, view, url, room="default", token=None, password=None,
                 host_name="peer", role="peer", on_status=None):
        self.view = view
        self.role = role
        self.host_name = host_name
        self.on_status = on_status
        self.log = OpLog()
        self._gui = _GuiBridge()
        post = self._gui.post
        self.client = CollabClient(
            url, room=room, token=token, password=password,
            on_snapshot=lambda data: post(lambda: self._on_snapshot(data)),
            on_peers=lambda n: post(lambda: self._on_peers(n)),
            on_cursor=lambda m: post(lambda: self._on_cursor(m)),
            on_event=lambda m: post(lambda: self._on_event(m)),
            on_connect=lambda: post(self._on_connect),
            on_error=lambda e: post(lambda: self._status(e)))
        self.peers = []
        self._peer_count = 0
        self._applied = set()               # op ids reflected in view.doc
        self._have_snapshot = role == "host"
        self._force_next = False
        self._skip_snapshot_ops = False

    def start(self):
        self.client.start()

    def stop(self):
        self.client.stop()

    def _status(self, text):
        if self.on_status:
            self.on_status(text)

    # ---- local edits ----
    def local_op(self, kind, page, **payload):
        """Log and broadcast a local edit; returns the op for the caller to
        apply to the document."""
        op = self.prepare_op(kind, page, **payload)
        self.publish_op(op)
        return op

    def prepare_op(self, kind, page, **payload):
        """Log a local edit without sending it: the caller applies it first
        and then publish_op()s it, or discard_op()s it if applying failed,
        so peers never get an edit this copy doesn't have (review 3b B2)."""
        o = self.log.add_local(kind, page, **payload)
        self._applied.add(o.id)
        return o.to_dict()

    def publish_op(self, op):
        self.client.send_event("op", {"op": op})

    def discard_op(self, op):
        self.log.ops.pop(op["id"], None)
        self._applied.discard(op["id"])

    def on_local_op(self, kind, page, **payload):   # older name
        return self.local_op(kind, page, **payload)

    def send_cursor(self, page, x, y):
        self.client.send_cursor(page, x, y)

    def _send_full_log(self):
        if self.log.ops:
            self.client.send_event("ops", {"ops": self.log.to_list()})

    # ---- inbound (always on the GUI thread) ----
    def _on_connect(self):
        self._status("connected")
        self._send_full_log()               # covers anything sent while away
        if self.role == "peer" and not self._have_snapshot:
            self.client.send_event("request_snapshot")

    def _on_snapshot(self, data):
        if self.role == "host":
            return                          # the host's copy is the source
        # A snapshot sent for a newcomer reaches everyone; peers that already
        # have the document keep it unless the host forced a resend.
        accept = not self._have_snapshot or self._force_next
        self._force_next = False
        self._skip_snapshot_ops = not accept
        if not accept:
            return
        try:
            doc = fitz.open(stream=data, filetype="pdf")
        except Exception:
            log.exception("could not open snapshot from host")
            self._status("received a document that could not be opened")
            return
        if hasattr(self.view, "replace_document"):
            self.view.replace_document(doc)
        else:
            self.view.doc.close()
            self.view.doc = doc
            self.view.page = max(0, min(self.view.page, doc.page_count - 1))
            self.view._render()
        self._applied = set()               # filled in by snapshot_ops
        self._have_snapshot = True
        self._status("received document from host")

    def _on_snapshot_ops(self, payload):
        self.log.merge(payload.get("ops", []))
        if self._skip_snapshot_ops:         # we ignored the snapshot itself
            self._skip_snapshot_ops = False
        else:
            ids = payload.get("ids", [])
            self._applied = {i for i in ids if isinstance(i, str)}
        self._apply_pending()

    def _on_peers(self, count):
        prev, self._peer_count = self._peer_count, count
        self.peers = [f"peer{i}" for i in range(max(0, count - 1))]
        if count > prev and prev:           # someone else joined
            self._send_full_log()
            # the host may have just arrived after us
            if self.role == "peer" and not self._have_snapshot:
                self.client.send_event("request_snapshot")
        self._status(f"connected — {count} in room")

    def _on_cursor(self, msg):
        if msg.get("client_id") == self.client.client_id:
            return
        try:
            self.view.paint_remote_cursor(int(msg.get("page", 0)),
                                          float(msg.get("x", 0)),
                                          float(msg.get("y", 0)))
        except (TypeError, ValueError):
            pass

    def _on_event(self, msg):
        name = msg.get("name")
        payload = msg.get("payload") or {}
        if not isinstance(payload, dict):
            return
        if name == "request_snapshot" and self.role == "host":
            self.push_document()
        elif name == "snapshot_incoming" and self.role != "host":
            self._force_next = bool(payload.get("force"))
        elif name == "snapshot_ops" and self.role != "host":
            self._on_snapshot_ops(payload)
        elif name == "op":
            op = payload.get("op")
            if op:
                self._merge_remote([op])
        elif name == "ops":
            ops = payload.get("ops", [])
            if isinstance(ops, list):
                self._merge_remote(ops)

    def _merge_remote(self, op_dicts):
        if self.log.merge(op_dicts):
            self._apply_pending()

    def _apply_pending(self):
        """Apply every logged op not yet in the document, in shared order."""
        allops = self.log.to_list()
        dead = merge.tombstones(allops)
        latest = merge.latest_fields(allops)
        pages = set()
        for o in self.log.ordered():
            if o.id in self._applied:
                continue
            self._applied.add(o.id)
            if o.id in dead:
                continue
            d = merge.effective(o.to_dict(), latest)
            if d is not None and merge.apply_op(self.view.doc, d):
                pages.add(o.page)
        if pages:
            if hasattr(self.view, "mark_dirty"):
                self.view.mark_dirty()
            self.view._render()
            sig = getattr(self.view, "page_changed", None)
            for p in pages:
                if sig is not None:
                    sig.emit(p)

    # ---- host sends the full document ----
    def push_document(self, force=False):
        """Send the document. force=True makes peers that already have one
        replace it (e.g. the host opened a different file)."""
        try:
            self.client.send_event("snapshot_incoming", {"force": force})
            self.client.send_snapshot(self.view.doc.tobytes())
            self.client.send_event("snapshot_ops", {
                "ids": sorted(self._applied), "ops": self.log.to_list()})
        except Exception:
            log.exception("could not send snapshot")
            self._status("could not send the document")
