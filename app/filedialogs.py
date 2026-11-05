"""Open and Save boxes start in the folder you used last (not the
program's install folder, where an empty start folder put them) and
remember where you went. Installed once at start-up for every
QFileDialog.get... call in the program (it patches QFileDialog itself, so
any library's box opened from here gets the same start folder)."""
import functools
import os

from PySide6.QtWidgets import QFileDialog

from . import settings

_DONE = False
# files picked in a Save box this session, newest first (reports, Excel,
# CSV...): File > Save to Dropbox As... offers them (dropbox_ui)
SAVED = []


def _start_dir(d):
    d = d or ""
    if not d:
        return settings.last_dir()
    if not os.path.isabs(d):            # a file name or a relative path:
        return os.path.join(settings.last_dir(), d)   # not the install folder
    return d


def _remember(result):
    first = result[0] if isinstance(result, tuple) else result
    if isinstance(first, list):
        first = first[0] if first else ""
    if isinstance(first, str) and first:
        d = first if os.path.isdir(first) else os.path.dirname(first)
        if d and os.path.isdir(d) and not settings._is_temp(d):
            settings.set("last_dir", d)
    return result


_ARGS = ("parent", "caption", "dir")       # the first three, in order


def _remember_saved(result):
    first = result[0] if isinstance(result, tuple) else result
    if isinstance(first, str) and first:
        p = os.path.abspath(first)
        SAVED[:] = [p] + [x for x in SAVED if os.path.normcase(x) !=
                          os.path.normcase(p)][:29]
    return result


def recent_saves():
    """Files saved through a Save box this session that still exist."""
    return [p for p in SAVED if os.path.isfile(p)]


def _wrap(fn, dir_pos, saving=False):
    """Calls with any mix of positional and keyword parent / caption / dir
    (Grok F14: caption= with no dir used to pass caption twice)."""
    @functools.wraps(fn)
    def call(*args, **kw):
        args = list(args)
        head = args[:3]
        while len(head) < 3:                 # fill from keywords, in order
            name = _ARGS[len(head)]
            if name in kw:
                head.append(kw.pop(name))
            elif name == "parent":
                head.append(None)
            else:
                head.append("")
        head[dir_pos] = _start_dir(head[dir_pos])
        out = _remember(fn(*head, *args[3:], **kw))
        return _remember_saved(out) if saving else out
    call._quantisheet = True
    return call


def install():
    global _DONE
    if _DONE:
        return
    for name in ("getOpenFileName", "getOpenFileNames", "getSaveFileName",
                 "getExistingDirectory"):
        fn = getattr(QFileDialog, name)
        if getattr(fn, "_quantisheet", False):
            continue
        setattr(QFileDialog, name, staticmethod(
            _wrap(fn, 2, saving=name == "getSaveFileName")))
    _DONE = True
