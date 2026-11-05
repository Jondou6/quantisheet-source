"""Lock Bid Set toggle (v14).

prebid.lock/unlock already record who locked, when, the total and a hash
of the takeoff. This adds the enforcement: while the bid is locked the
takeoff is read-only in the viewer (no new measurements, counts, scale
changes, or edits/deletes of takeoffs); notes, clouds and status changes
still work. Unlocking asks for a reason, logged by prebid.unlock.
Wire with `bidlock.install(win)` (adds "Lock Bid Set" checkable action,
a status-bar chip, and the viewer guard)."""
from PySide6.QtWidgets import QInputDialog, QLabel, QMessageBox

from . import annotate, prebid

_SAFE_SET_KEYS = {"target", "xref", "rect", "id", "status", "scope",
                  "reason"}


def is_locked(doc):
    try:
        return prebid.lock_state(doc) is not None
    except Exception:
        return False


def _hits_takeoff(doc, page, payload):
    try:
        for a in annotate.find_annots(doc[page], payload) or []:
            if (a.info or {}).get("subject", "").startswith(
                    annotate.TAKEOFF + ":"):
                return True
    except Exception:
        return True                       # can't tell: be safe
    return False


def blocks(kind, payload, doc=None, page=None):
    """Would this edit change the locked takeoff?"""
    p = payload or {}
    if kind in ("set_scale", "add_count") or isinstance(p.get("measure"), dict):
        return True
    if kind in ("delete_annot", "set_annot") and doc is not None:
        if kind == "set_annot" and set(p) <= _SAFE_SET_KEYS:
            return False
        return _hits_takeoff(doc, page, p)
    return False


def banner_text(doc):
    lk = prebid.lock_state(doc)
    if not lk:
        return ""
    s = f"🔒 Bid locked by {lk.get('by', '')} {str(lk.get('at', ''))[:16]}"
    if lk.get("total"):
        s += f" at ${lk['total']}"
    if lk.get("stale"):
        s += " - takeoff changed since lock"
    return s


def _total(doc):
    try:
        from . import proposal
        return float(proposal.price(doc, proposal.read(doc))["total"])
    except Exception:
        return 0.0


def toggle(win):
    """Lock or unlock the current bid. Returns "locked", "unlocked" or
    None (cancelled / refused)."""
    v = getattr(win, "_view", None)
    if v is None:
        return None
    doc = v.doc
    if is_locked(doc):
        reason, ok = QInputDialog.getText(
            win, "Unlock Bid Set", "Why are you unlocking the bid?")
        if not ok:
            return None
        try:
            prebid.unlock(doc, reason=reason)
        except prebid.PrebidError as e:
            QMessageBox.warning(win, "Unlock Bid Set", str(e))
            return None
        result = "unlocked"
    else:
        try:
            prebid.lock(doc, _total(doc))
        except prebid.PrebidError as e:
            QMessageBox.warning(win, "Lock Bid Set", str(e) +
                                "\n\nOpen Estimate > Pre-bid Checklist.")
            return None
        result = "locked"
    try:
        v.mark_dirty()
    except Exception:
        pass
    refresh(win)
    return result


def refresh(win):
    v = getattr(win, "_view", None)
    locked = bool(v) and is_locked(v.doc)
    act = getattr(win, "_bl_action", None)
    if act is not None:
        act.blockSignals(True)
        act.setChecked(locked)
        act.blockSignals(False)
    chip = getattr(win, "_bl_chip", None)
    if chip is not None:
        chip.setText(banner_text(v.doc) if locked else "")
        chip.setVisible(locked)


def _patch_viewer():
    from . import viewer
    cls = viewer.PdfView if hasattr(viewer, "PdfView") else None
    if cls is None:
        cls = next(c for c in vars(viewer).values()
                   if isinstance(c, type) and hasattr(c, "do_op"))
    if getattr(cls, "_bl_patched", False):
        return
    orig = cls.do_op

    def do_op(self, kind, page, **payload):
        if is_locked(self.doc) and blocks(kind, payload, self.doc, page):
            w = self.window()
            try:
                w.statusBar().showMessage(
                    "Bid is locked - unlock it (Lock Bid Set) to change "
                    "the takeoff.", 5000)
            except Exception:
                pass
            return False
        return orig(self, kind, page, **payload)

    cls.do_op = do_op
    cls._bl_patched = True


def install(win):
    if getattr(win, "_bl_installed", False):
        return
    from PySide6.QtGui import QAction
    _patch_viewer()
    act = QAction("Lock Bid Set", win)
    act.setCheckable(True)
    act.triggered.connect(lambda _c=False: toggle(win))
    win.addAction(act)
    win._bl_action = act
    chip = QLabel("")
    chip.setStyleSheet("background:#fde68a;padding:1px 6px;"
                       "border-radius:6px;font-weight:bold")
    chip.setVisible(False)
    try:
        win.statusBar().addPermanentWidget(chip)
    except Exception:
        pass
    win._bl_chip = chip
    try:
        win.tabs.currentChanged.connect(lambda _i: refresh(win))
    except Exception:
        pass
    win._bl_installed = True
    refresh(win)
