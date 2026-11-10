"""Auto-count review (triage), from the Takeoff Studio mockup with its bugs
fixed: confidence is the matcher's real score (autocount.find), the
commit is one undo step (History.begin_pages/commit_pages), and the undo cap
is a setting (0 = no step limit; the memory cap still applies).

- auto-accept slider (default 0.92) and auto-reject floor (0.60); hits in
  between wait for a person. Manual Y/N always wins over the thresholds.
- Y / N keys, Up / Down to move; progress = triaged / remaining /
  accepted / rejected; a "why" line per hit.
- 3+ rejects that look alike (same rotation, similar size) -> offer to
  train them as a second symbol (so they stop showing up as this one).
"""
from . import annotate, autocount
from .dmoney import c2 as _c2

ACCEPT, REJECT = 0.92, 0.60
SIMILAR_MIN = 3


def why(h):
    parts = [f"match {_c2(h.get('score', 0)):.2f}"]
    a = h.get("angle_hint")
    if a:
        parts.append(f"rotated {int(a)}\u00b0")
    if h.get("mirrored"):
        parts.append("mirrored")
    if "tag_ok" in h:
        parts.append("tag found" if h["tag_ok"] else "no tag")
    if h.get("scale") and abs(h["scale"] - 1) > 0.02:
        parts.append(f"size x{_c2(h['scale']):.2f}")
    parts.append(f"p{h.get('page', 0) + 1}")
    return " \u00b7 ".join(parts)


class Triage:
    def __init__(self, hits, accept=ACCEPT, reject=REJECT):
        self.hits = sorted(hits, key=lambda h: -h.get("score", 0))
        self.manual = {}
        self.state = {}
        self.accept, self.reject = accept, reject
        self._apply()
        self.pos = 0
        self._to_pending(0, 1)

    def _apply(self):
        for h in self.hits:
            k = id(h)
            if k in self.manual:
                self.state[k] = self.manual[k]
            elif h.get("score", 0) >= self.accept:
                self.state[k] = "accepted"
            elif h.get("score", 0) < self.reject:
                self.state[k] = "rejected"
            else:
                self.state[k] = "pending"

    def set_thresholds(self, accept=None, reject=None):
        if accept is not None:
            self.accept = accept
        if reject is not None:
            self.reject = reject
        if self.reject > self.accept:
            self.reject = self.accept
        self._apply()
        self._to_pending(self.pos, 1)

    def _pending_idx(self):
        return [i for i, h in enumerate(self.hits)
                if self.state[id(h)] == "pending"]

    def _to_pending(self, start, step):
        p = self._pending_idx()
        if not p:
            self.pos = None
            return
        if step > 0:
            nxt = [i for i in p if i >= (start or 0)]
            self.pos = nxt[0] if nxt else p[0]
        else:
            prv = [i for i in p if i <= start]
            self.pos = prv[-1] if prv else p[-1]

    def current(self):
        return None if self.pos is None else self.hits[self.pos]

    def key(self, k):
        if self.pos is None:
            return
        if k in ("Y", "N"):
            h = self.hits[self.pos]
            v = "accepted" if k == "Y" else "rejected"
            self.manual[id(h)] = v
            self.state[id(h)] = v
            self._to_pending(self.pos + 1, 1)
        elif k == "Down":
            self._to_pending(self.pos + 1, 1)
        elif k == "Up":
            self._to_pending(self.pos - 1, -1)

    def progress(self):
        v = list(self.state.values())
        acc, rej = v.count("accepted"), v.count("rejected")
        return {"total": len(v), "accepted": acc, "rejected": rej,
                "triaged": acc + rej, "remaining": v.count("pending")}

    def accepted(self):
        return [h for h in self.hits if self.state[id(h)] == "accepted"]

    def second_symbol_suggestion(self):
        """A cluster of >= 3 manual rejects with the same rotation and
        similar size, or None."""
        rej = [h for h in self.hits if self.manual.get(id(h)) == "rejected"]
        groups = {}
        for h in rej:
            r = h.get("rect") or [0, 0, 0, 0]
            w, ht = r[2] - r[0], r[3] - r[1]
            key = (int(h.get("angle_hint") or 0), bool(h.get("mirrored")),
                   round(w / 2), round(ht / 2))
            groups.setdefault(key, []).append(h)
        best = max(groups.values(), key=len, default=[])
        if len(best) < SIMILAR_MIN:
            return None
        return {"hits": best, "text": f"{len(best)} rejected hits look alike. "
                "Train them as a second symbol so they're counted separately?"}

    def commit(self, doc, history=None, group="Count", color=(1, 0, 0)):
        """Add count marks for the accepted hits as ONE undo step."""
        acc = self.accepted()
        for h in acc:
            h["method"] = "auto count (reviewed)"
        marks = autocount.count_marks(acc, group=group, doc=doc, color=color)
        before = history.begin_pages(doc, {p for p, _, _ in marks}) \
            if history is not None and marks else None
        for p, kind, payload in marks:
            annotate.apply_op(doc, annotate.new_op(kind, p, **payload))
        if before is not None:
            history.commit_pages(doc, before)
        return len(acc)


def apply_undo_limit(history, limit):
    """Undo step cap from settings ("undo_limit"); 0 / None = no step cap
    (History.max_bytes still bounds memory)."""
    history.limit = int(limit) if limit else 10 ** 9
    return history.limit


try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel,
                                   QProgressBar, QPushButton, QSlider,
                                   QVBoxLayout)
except ImportError:          # pragma: no cover
    QDialog = None

if QDialog is not None:
    class TriageDialog(QDialog):
        def __init__(self, triage, parent=None):
            super().__init__(parent)
            self.t = triage
            self.setWindowTitle("Review Auto Count")
            v = QVBoxLayout(self)
            row = QHBoxLayout()
            self.slider = QSlider(Qt.Horizontal)
            self.slider.setRange(50, 100)
            self.slider.setValue(round(triage.accept * 100))
            self.floor = QSlider(Qt.Horizontal)
            self.floor.setRange(0, 100)
            self.floor.setValue(round(triage.reject * 100))
            row.addWidget(QLabel("Auto-accept \u2265"))
            row.addWidget(self.slider)
            row.addWidget(QLabel("Auto-reject <"))
            row.addWidget(self.floor)
            v.addLayout(row)
            self.bar = QProgressBar()
            self.progress_label = QLabel()
            self.why_label = QLabel()
            self.suggest = QPushButton()
            self.suggest.hide()
            v.addWidget(self.bar)
            v.addWidget(self.progress_label)
            v.addWidget(self.why_label)
            v.addWidget(QLabel("Y = accept, N = reject, \u2191/\u2193 = move"))
            v.addWidget(self.suggest)
            self.slider.valueChanged.connect(self._thr)
            self.floor.valueChanged.connect(self._thr)
            self.setFocusPolicy(Qt.StrongFocus)
            self.refresh()

        def _thr(self):
            self.t.set_thresholds(self.slider.value() / 100,
                                  self.floor.value() / 100)
            self.refresh()

        def refresh(self):
            p = self.t.progress()
            self.bar.setMaximum(max(1, p["total"]))
            self.bar.setValue(p["triaged"])
            self.progress_label.setText(
                f"Triaged {p['triaged']} \u00b7 Remaining {p['remaining']} \u00b7 "
                f"Accepted {p['accepted']} \u00b7 Rejected {p['rejected']}")
            h = self.t.current()
            self.why_label.setText(why(h) if h else "All hits reviewed.")
            s = self.t.second_symbol_suggestion()
            self.suggest.setVisible(bool(s))
            if s:
                self.suggest.setText(s["text"])

        def keyPressEvent(self, e):
            m = {Qt.Key_Y: "Y", Qt.Key_N: "N", Qt.Key_Up: "Up",
                 Qt.Key_Down: "Down"}
            if e.key() in m:
                self.t.key(m[e.key()])
                self.refresh()
                return
            super().keyPressEvent(e)


def attach(dlg, accept=None, reject=None):
    """Put the triage controls on the thumbnail review (autocount.
    CountReviewDialog): auto-accept / auto-reject sliders that set the
    check boxes, Y / N on the current thumbnail (then on to the next
    doubtful one), the "why" line and the second-symbol hint. A box the
    user ticks or unticks by hand is never changed by the sliders.
    Returns the Triage."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtWidgets import QHBoxLayout as _H, QLabel as _L, \
        QSlider as _S
    settings_get = None
    try:
        from . import settings as _st
        settings_get = _st.get
    except Exception:
        pass
    a = accept if accept is not None else \
        (settings_get("count_accept", ACCEPT) if settings_get else ACCEPT)
    r = reject if reject is not None else \
        (settings_get("count_reject", REJECT) if settings_get else REJECT)
    t = Triage(dlg.hits, a, r)
    row_of = {id(h): i for i, h in enumerate(dlg.hits)}
    busy = [False]

    def sync():
        busy[0] = True
        try:
            for h in t.hits:
                it = dlg.list.item(row_of[id(h)])
                it.setCheckState(_Qt.Checked if t.state[id(h)] == "accepted"
                                 else _Qt.Unchecked)
        finally:
            busy[0] = False
        p = t.progress()
        tip = t.second_symbol_suggestion()
        dlg.triage_info.setText(
            f"Auto-accepted at {_c2(t.accept):.2f}+, auto-rejected under "
            f"{_c2(t.reject):.2f}. {p['remaining']} left to look at - Y / N "
            "on the selected one." + (f"  {tip['text']}" if tip else ""))
        dlg._count()

    def thr():
        t.set_thresholds(hi.value() / 100, lo.value() / 100)
        sync()

    def by_hand(it):
        if busy[0]:
            return
        h = dlg.hits[dlg.list.row(it)]
        v = "accepted" if it.checkState() == _Qt.Checked else "rejected"
        t.manual[id(h)] = v
        t.state[id(h)] = v
        sync()

    def current(it, _prev=None):
        if it is not None:
            dlg.why_label.setText(why(dlg.hits[dlg.list.row(it)]))

    def key(k):
        it = dlg.list.currentItem()
        if it is None:
            return False
        h = dlg.hits[dlg.list.row(it)]
        t.pos = t.hits.index(h)
        t.key(k)
        sync()
        nxt = t.current()
        if nxt is not None:
            dlg.list.setCurrentRow(row_of[id(nxt)])
        return True

    row = _H()
    hi, lo = _S(_Qt.Horizontal), _S(_Qt.Horizontal)
    hi.setRange(50, 100)
    lo.setRange(0, 100)
    hi.setValue(round(t.accept * 100))
    lo.setValue(round(t.reject * 100))
    row.addWidget(_L("Auto-accept at or above"))
    row.addWidget(hi)
    row.addWidget(_L("Auto-reject below"))
    row.addWidget(lo)
    dlg.triage_info, dlg.why_label = _L(""), _L("")
    dlg.triage_info.setWordWrap(True)
    lay = dlg.layout()
    lay.insertLayout(1, row)
    lay.insertWidget(2, dlg.triage_info)
    lay.insertWidget(3, dlg.why_label)
    dlg.accept_slider, dlg.reject_slider = hi, lo
    hi.valueChanged.connect(lambda _v: thr())
    lo.valueChanged.connect(lambda _v: thr())
    dlg.list.itemChanged.connect(by_hand)
    dlg.list.currentItemChanged.connect(current)
    dlg.triage_key = key
    old_kp = dlg.keyPressEvent

    def kp(e):
        m = {_Qt.Key_Y: "Y", _Qt.Key_N: "N"}
        if e.key() in m and key(m[e.key()]):
            return
        old_kp(e)
    dlg.keyPressEvent = kp
    dlg.list.keyPressEvent = (lambda e, f=dlg.list.keyPressEvent:
                              kp(e) if e.key() in (_Qt.Key_Y, _Qt.Key_N)
                              else f(e))
    dlg.triage = t
    sync()
    first = t.current()
    if first is not None:
        dlg.list.setCurrentRow(row_of[id(first)])
    return t
