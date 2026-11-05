"""Voice commands in the window: a Listener whose results arrive on the GUI
thread, and what each command does."""
import re

from PySide6.QtCore import QObject, Signal

from . import voice


PRIVACY = ("Speech is recognised by Windows on this PC; no audio "
           "leaves the computer.")


class VoiceControl(QObject):
    heard = Signal(str, float, str)
    state = Signal(str, str)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.listener = voice.Listener(
            lambda t, c, g: self.heard.emit(t, c, g),
            lambda s, m: self.state.emit(s, m))
        self.heard.connect(self._on_heard)
        self.state.connect(self._on_state)
        self.last = ""
        self._sheet_cache = {}

    @property
    def active(self):
        return self.listener.running

    def toggle(self):
        if self.active:
            self.stop()
            return False
        return self.listener.start()

    def stop(self):
        self.listener.stop()
        self._set_button(False)
        self.win._flash("Voice commands off")

    def _set_button(self, on):
        a = self.win.command("Voice Commands")
        if a is not None:
            a.setCheckable(True)
            a.setChecked(on)

    def _on_state(self, state, msg):
        if state == "listening":
            self._set_button(True)
            # said where it's used (review 2, Nov 4)
            msg = ((msg + " - ") if msg else "") + PRIVACY
        elif state in ("error", "stopped"):
            self._set_button(False)
        if state == "error":
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self.win, "Voice Commands", msg)
        elif msg:
            self.win._flash("🎤 " + msg)

    def _on_heard(self, text, conf, grammar):
        if not voice.accept(text, conf, grammar):
            self.win._flash(f"🎤 Didn't catch that (\"{text}\")")
            return
        self.do(text)

    def do(self, text):
        """Carry out a spoken command. Returns what it did, or ''."""
        names = list(getattr(self.win, "_cmd", {}).keys())
        action, value = voice.interpret(text, names)
        self.last = text
        w = self.win
        v = w._view
        done = ""
        if action == "stop":
            self.stop()
            return "stop"
        if action == "page" and v:
            n = max(1, min(value, v.doc.page_count))
            w._go_page(n - 1)
            done = f"page {n}"
        elif action == "sheet" and v:
            p = self.find_sheet(value)
            if p is not None:
                w._go_page(p)
                done = f"sheet {value}"
            else:
                w._flash(f"🎤 No sheet {value} in this file")
                return ""
        elif action == "zoom" and v:
            v.set_zoom(value / 100.0)
            done = f"zoom {value}%"
        elif action == "search" and v:
            w.search.open_bar(v.doc)
            w.search.edit.setText(value)
            w.search.run()
            if getattr(w.search, "hits", None):
                w.search.step(1)
            done = f"search \"{value}\""
        elif action == "command":
            a = w.command(value)
            if a is None or not a.isEnabled():
                w._flash(f"🎤 Heard \"{text}\" - {value} isn't available "
                         "here")
                return ""
            a.trigger()
            done = value
        else:
            w._flash(f"🎤 Heard \"{text}\" - not a command I know")
            return ""
        w._flash(f"🎤 {done}")
        return done

    def find_sheet(self, code):
        from . import sheets
        v = self.win._view
        key = re.sub(r"[-. ]", "", code.upper())
        cache = self._sheet_cache.get(id(v.doc))
        if cache is None:
            cache = {}
            for i in range(v.doc.page_count):
                num, _ = sheets.sheet_info(sheets.page_words(v.doc[i]),
                                           v.doc[i].rect.width,
                                           v.doc[i].rect.height)
                if num:
                    cache.setdefault(re.sub(r"[-. ]", "", num.upper()), i)
            self._sheet_cache[id(v.doc)] = cache
        return cache.get(key)
