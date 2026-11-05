import logging
import os
import sys
import threading
import time

_T0 = time.perf_counter()
_MARKS = []


def _mark(name):
    """Start-up timing: seconds since the program began, per step (in the
    log, and written out for tools/time_launch.py)."""
    _MARKS.append((name, round(time.perf_counter() - _T0, 2)))

from PySide6.QtWidgets import QApplication, QSplashScreen
# MainWindow (and everything it pulls in) is imported in run(), after the
# splash is up, so the splash appears as soon as Qt is ready.


def log_folder():
    """Each user's own folder, or the IT department's LogDirectory (one
    sub-folder per user, so people on a Remote Desktop server don't write
    into the same file)."""
    from . import policy, settings
    if getattr(_setup_logging, "fallback", False):
        return settings.DIR          # IT's folder couldn't be written
    it = policy.get("LogDirectory")
    if it:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
        return os.path.join(os.path.expandvars(it), user)
    return settings.DIR


def _setup_logging():
    """Log to ~/.quantisheet/quantisheet.log. With pythonw there is no console,
    so without this an error or crash leaves no trace."""
    from . import settings
    handlers = [logging.StreamHandler()] if sys.stderr else []
    try:
        log_dir = log_folder()
        try:                         # IT's LogDirectory must be writable
            os.makedirs(log_dir, exist_ok=True)
            probe = os.path.join(log_dir, ".write-test")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
        except OSError:              # Venice review M3: else no log at all
            log_dir = settings.DIR
            os.makedirs(log_dir, exist_ok=True)
            _setup_logging.fallback = True
        path = os.path.join(log_dir, settings.LOG_NAME)
        if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
            os.replace(path, path + ".old")
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
        import faulthandler
        if getattr(_setup_logging, "crash_file", None) is None:
            crash = os.path.join(log_dir, "crash.log")
            if os.path.exists(crash) and os.path.getsize(crash) > 2_000_000:
                os.replace(crash, crash + ".old")      # same limit as the log
            _setup_logging.crash_file = open(crash, "a", encoding="utf-8")
            try:                    # date and build each crash (0.12.30 N5)
                import datetime
                from . import __version__
                _setup_logging.crash_file.write(
                    f"--- {datetime.datetime.now().isoformat(timespec='seconds')}"
                    f" QuantiSheet {__version__} pid {os.getpid()} ---\n")
                _setup_logging.crash_file.flush()
            except Exception:                             # noqa: BLE001
                pass
            faulthandler.enable(_setup_logging.crash_file)   # hard crashes
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    if not handlers:                   # no console and no log file: say
        handlers = [logging.NullHandler()]     # nothing, but don't break
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: "
                               "%(message)s")
    if getattr(_setup_logging, "fallback", False):
        logging.getLogger("quantisheet").warning(
            "the IT log folder (LogDirectory) can't be written - logging "
            "to %s instead", settings.DIR)

    def hook(kind, value, tb):
        logging.getLogger("quantisheet").error("Unhandled error",
                                             exc_info=(kind, value, tb))
        try:                         # a report on this PC (0.12.24)
            from . import crashreport
            crashreport.from_exception(kind, value, tb)
        except Exception:                                 # noqa: BLE001
            pass
    sys.excepthook = hook            # keep running instead of quitting


def run(argv=None):
    argv = sys.argv if argv is None else argv
    _mark("python and imports")
    from . import settings
    if os.environ.get("QUANTISHEET_SMOKE"):
        _private_settings()        # the build check never touches yours
    _setup_logging()
    if not os.environ.get("QUANTISHEET_SMOKE"):
        try:            # the shared copy: open this person's own one (Nov 3)
            from . import owncopy
            if owncopy.redirect(argv):
                logging.getLogger("quantisheet").info(
                    "shared copy: opened this person's own copy instead")
                return 0
        except Exception:                                 # noqa: BLE001
            logging.getLogger(__name__).debug("ignored", exc_info=True)
    from . import oldnames         # files saved under the old name
    oldnames.install()             # convert as they open (once each)
    try:                                     # which build (0.12.30 N4)
        import fitz
        from PySide6 import __version__ as qt_v
        from . import __version__
        logging.getLogger("quantisheet").info(
            "QuantiSheet %s starting (%s; Python %s; PyMuPDF %s; Qt %s)",
            __version__, "installed" if getattr(sys, "frozen", False)
            else "source", sys.version.split()[0],
            getattr(fitz, "VersionBind", "?"), qt_v)
    except Exception:                                     # noqa: BLE001
        logging.getLogger("quantisheet").info("QuantiSheet starting")
    app = QApplication(argv)
    try:                                    # Venice #18: screen-reader names
        from . import a11y
        a11y.install(app)
    except Exception:                                     # noqa: BLE001
        logging.getLogger("quantisheet").warning("a11y names off",
                                                 exc_info=True)
    from . import shellverbs                # Nov 3: Explorer right-click
    verb = shellverbs.parse(argv)
    if verb and verb[0] == shellverbs.REDUCE:
        from PySide6.QtWidgets import QMessageBox
        try:
            out, a, b = shellverbs.reduce(verb[1])
            QMessageBox.information(
                None, "Reduce Size",
                f"Saved {os.path.basename(out)}\n{shellverbs.size_text(a)} "
                f"-> {shellverbs.size_text(b)}" +
                ("" if b < a else "\n(It couldn't be made smaller.)"))
        except Exception as e:                    # noqa: BLE001
            QMessageBox.warning(None, "Reduce Size",
                                f"{os.path.basename(verb[1])}: {e}")
        return 0
    files = [a for a in argv[1:] if a.lower().endswith((".pdf", ".qstools"))
             and os.path.exists(a)]
    new_window = "--new-window" in argv
    if not os.environ.get("QUANTISHEET_SMOKE") and not verb and \
            not new_window:
        try:                # already running (or starting): it comes forward
            from . import singleinstance
            first = singleinstance.claim()
            if (files or not first) and singleinstance.bring_forward(
                    files, wait_s=0.0 if first else 45.0):
                logging.getLogger("quantisheet").info(
                    "handed %d file(s) to the running QuantiSheet; it came "
                    "forward", len(files))
                return 0
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
    app.setApplicationName("QuantiSheet")
    _set_icon(app)
    from . import filedialogs
    filedialogs.install()
    from . import betalicense
    # the splash goes up first thing - unless a license prompt is coming,
    # which it must never cover
    splash = None if betalicense.required() else _show_splash(app)
    _mark("window system")
    from . import theme
    theme.apply(app)
    theme.follow_system(app)
    try:                       # every dialog fits the screen (Oct 22)
        from . import dialog_fit
        dialog_fit.install(app)
    except Exception:                                     # noqa: BLE001
        logging.getLogger(__name__).debug("dialog fit", exc_info=True)
    _mark("theme")
    try:
        from . import costbook
        costbook.install_shipped()
    except Exception:
        logging.getLogger("quantisheet").warning("cost books not installed",
                                               exc_info=True)
    _mark("cost books")
    if os.environ.get("QUANTISHEET_SMOKE"):
        return _smoke(app, os.environ["QUANTISHEET_SMOKE"])
    if not betalicense.gate():
        return 0
    from . import onboard
    if not onboard.signed_in():
        if splash is not None:          # the splash stays on top: close it
            splash.close()
            splash = None
        if not onboard.gate():
            return 0
    if splash is None:
        splash = _show_splash(app)
    _beta_warn = betalicense.current() if betalicense.required() else None
    _mark("license")
    from .main_window import MainWindow
    _mark("program code loaded")
    w = MainWindow()
    _mark("main window built")
    w.show_restored()
    if splash is not None:
        splash.finish(w)
    app.processEvents()
    _mark("window shown")
    try:                    # the Store version beside an old setup copy
        from . import packaged
        if packaged.is_packaged():
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: packaged.offer_remove_old(w))
    except Exception:                                    # noqa: BLE001
        logging.getLogger("quantisheet").debug("ignored", exc_info=True)
    logging.getLogger("quantisheet").info(
        "start-up: " + ", ".join(f"{n} {s}s" for n, s in _MARKS))
    out = os.environ.get("QUANTISHEET_TIMING")
    if out:                         # tools/time_launch.py: report and quit
        import json
        with open(out, "w", encoding="utf-8") as f:
            json.dump(_MARKS, f)
        w.close()
        return 0
    try:                            # a hard crash last time: say so, once
        from . import crashreport
        cf = getattr(_setup_logging, "crash_file", None)
        prev = crashreport.check_previous_run(cf.name) if cf else None
        if prev:
            crashreport._notify(prev, previous=True,
                                kind=crashreport.last_kind[0])
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    try:                            # Nov 3: active time per job and sheet
        from . import timelog
        timelog.install(app, w)
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    try:                            # a frozen window says what it was doing
        from . import freeze_watch
        freeze_watch.install(app, getattr(_setup_logging, "crash_file", None))
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    if betalicense.read_only():
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(w, "QuantiSheet License",
                                betalicense.READ_ONLY_MESSAGE)
    elif _beta_warn and betalicense.days_left(_beta_warn) <= \
            betalicense.WARN_DAYS:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(
            w, "QuantiSheet License",
            f"Your beta license ends in "
            f"{max(0, betalicense.days_left(_beta_warn))} day(s), on "
            f"{_beta_warn['x']}. Ask for a new key to keep testing.")
    for f in files:
        w.open_path(f)
    if verb:
        shellverbs.run_in_window(w, *verb)
    if not os.environ.get("QUANTISHEET_SMOKE"):
        try:                # the weekly copy of QuantiSheet's data (QS-006)
            from . import databackup

            def _weekly():
                try:
                    databackup.weekly()
                except Exception:                         # noqa: BLE001
                    logging.getLogger("quantisheet").warning(
                        "weekly data backup failed", exc_info=True)
            t = threading.Timer(90, _weekly)
            t.daemon = True
            t.start()
            warn = databackup.data_location_warning()
            if warn:
                logging.getLogger("quantisheet").warning(warn)
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
    if not verb and not os.environ.get("QUANTISHEET_SMOKE"):
        try:                # first run: who uses this copy, then the tour;
            # after an update: the one-time "ribbon changed" card (even when
            # QuantiSheet was opened from a file)
            from PySide6.QtCore import QTimer
            from . import quickaccess
            if quickaccess.needs_upgrade_card() or \
                    (not files and quickaccess.needs_welcome()):
                QTimer.singleShot(1200, lambda: quickaccess.first_run(w))
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
    try:                            # later files open in this window
        from . import singleinstance

        def take(paths, w=w):
            for p in paths:
                w.open_path(p)
            w.showNormal() if w.isMinimized() else None
            w.raise_()
            w.activateWindow()
        w._single_instance = singleinstance.listen(take)
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    try:                    # the printer's helper, if you have it turned on
        from . import printhelper
        threading.Thread(target=printhelper.ensure_running,
                         daemon=True).start()
    except Exception:                                     # noqa: BLE001
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    return app.exec()


_SMOKE_DIRS = []        # the build check's throwaway folders, removed at exit


def _remove_smoke_dirs():
    """Delete the build check's temp folders when it quits (each check
    used to leave one behind). Logs are closed first so Windows lets go."""
    import shutil
    logging.shutdown()
    f = getattr(_setup_logging, "crash_file", None)
    if f is not None:
        try:
            f.close()
        except OSError:
            pass
    for d in _SMOKE_DIRS:
        shutil.rmtree(d, ignore_errors=True)


def _private_settings():
    """Settings, recent files and the price database in a throwaway
    folder (the installer's build check opened a practice drawing with
    the real settings, so "smoke.pdf" showed up in everyone's Recent)."""
    import tempfile
    from . import settings
    tmp = tempfile.mkdtemp(prefix="quantisheet-smoke-")
    _SMOKE_DIRS.append(tmp)
    settings.DIR = os.path.join(tmp, "cfg")
    settings.PATH = os.path.join(settings.DIR, "settings.json")
    settings._cache = None
    os.makedirs(settings.DIR, exist_ok=True)


def _smoke(app, out_path):
    """Installer build check: load every heavy library, open a drawing in
    the real window, write what happened to `out_path`, and quit."""
    import json
    import tempfile
    import time
    import traceback
    res = {"frozen": bool(getattr(sys, "frozen", False)), "checks": {}}

    def step(name, fn):
        t = time.time()
        try:
            v = fn()
            res["checks"][name] = {"ok": True, "value": v,
                                   "s": round(time.time() - t, 2)}
        except Exception:
            res["checks"][name] = {"ok": False,
                                   "error": traceback.format_exc()[-800:]}
    for mod in ("fitz", "numpy", "cv2", "pyhanko.sign", "ezdxf",
                "websockets", "PIL.Image",
                "cryptography.hazmat.primitives.asymmetric.ed25519"):
        step("import " + mod, lambda m=mod: bool(__import__(m)))
    from . import betalicense
    step("license required", betalicense.required)
    step("public key present", lambda: len(betalicense.public_key_text()))
    step("license dialog builds",
         lambda: bool(betalicense.LicenseDialog().close() is not None))
    holder = {}

    def window():
        from .main_window import MainWindow
        w = MainWindow()
        w.show()
        holder["w"] = w
        return w.windowTitle()
    step("main window", window)

    def open_plan():
        from . import practice
        path = practice.make(os.path.join(tempfile.mkdtemp(prefix="quantisheet-smoke-"),
                                          "smoke.pdf"))
        _SMOKE_DIRS.append(os.path.dirname(path))
        holder["w"].open_path(path)
        for _ in range(20):
            app.processEvents()
            time.sleep(0.05)
        v = holder["w"]._view
        return {"pages": v.doc.page_count}
    step("open practice drawings", open_plan)

    def autorooms():
        from . import autotakeoff
        v = holder["w"]._view
        found, _ = autotakeoff.all_rooms(v.doc[0], {"ppu": 18.0,
                                                     "unit": "ft"})
        return len(found)
    step("auto rooms", autorooms)

    def drawing_process():
        """The Stage 4 drawing process starts inside the built program and
        draws a page (a frozen exe needs freeze_support for this)."""
        from . import render_worker
        v = holder["w"]._view
        got = {}
        rid = render_worker.get().render(
            v._path, 0, 1.0, None, True, None,
            lambda m: got.setdefault("m", m))
        if rid is None:
            raise RuntimeError("drawing process did not start")
        end = time.time() + 30
        while "m" not in got and time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        m = got.get("m")
        if not m or m[0] != "img" or not m[5]:
            raise RuntimeError(f"no picture back: {m and m[:3]}")
        return f"{m[5]}x{m[6]} px"
    step("drawing process", drawing_process)

    def generate_set():
        """Generate Set builds its ten sheets with Modulor inside the
        built program."""
        from . import genset_ui
        out = os.path.join(tempfile.mkdtemp(prefix="quantisheet-smoke-"),
                           "smoke_genset.pdf")
        r = genset_ui.generate({"brief": "3 bed 2 bath house 1600 sf",
                                "form": {"name": "Smoke"}}, out,
                               use_ai=False)
        return f"{r['pages']} sheets, Modulor {r['modulor']}"
    step("generate set", generate_set)
    res["ok"] = all(c["ok"] for c in res["checks"].values())
    import atexit
    atexit.register(_remove_smoke_dirs)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, default=str)
    try:
        holder["w"]._view.dirty = False
        holder["w"].close()
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    return 0 if res["ok"] else 1




def splash_version_text():
    from . import __version__
    return f"Version {__version__}"


def _stamp_version(pm):
    """Write the version under the tagline on the splash (Jon, Oct 19).
    Placed and sized as a share of the picture, so it lands in the same
    spot at any resolution."""
    from PySide6.QtGui import QColor, QFont, QPainter
    w, h = pm.width(), pm.height()
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.TextAntialiasing, True)
        f = QFont("Segoe UI")
        f.setPixelSize(max(10, round(h * 0.024)))
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#5f6470"))
        p.drawText(round(w * 0.065), round(h * 0.662), splash_version_text())
    finally:
        p.end()
    return pm


def splash_company():
    """(name, logo path or "") of the company saved on this computer for
    proposals - shown on the splash. Nobody else's company is built into
    the program (Jon, Nov 3: only his copy shows his company)."""
    try:
        from . import settings
        c = settings.get("company") or {}
    except Exception:
        return "", ""
    name = str(c.get("name", "") or "").strip()[:60]
    logo = str(c.get("logo", "") or "").strip()
    if logo and not os.path.isfile(logo):
        logo = ""
    return name, logo


def _stamp_company(pm, name=None, logo=None):
    """The company's logo above the name and a "by <company>" label under
    it, in the spaces the splash leaves for them. Nothing when no company
    is saved. Placed as shares of the picture, like the version."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, \
        QPainter
    if name is None:
        name, logo = splash_company()
    if not name and not logo:
        return pm
    w, h = pm.width(), pm.height()
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if logo:
            img = QImage(logo)
            if not img.isNull():
                box = QRectF(w * 0.06, h * 0.091, w * 0.30, h * 0.137)
                s = min(box.width() / img.width(), box.height() / img.height())
                p.drawImage(QRectF(box.x(), box.y(), img.width() * s,
                                   img.height() * s), img)
        if name:
            f = QFont("Segoe UI")
            f.setPixelSize(max(10, round(h * 0.0243)))
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            text = f"by {name}"
            tw = QFontMetricsF(f).horizontalAdvance(text)
            r = QRectF(w * 0.065, h * 0.437, tw + w * 0.025, h * 0.049)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#e3f3ea"))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.setPen(QColor("#1f7a4c"))
            p.drawText(r, Qt.AlignCenter, text)
    finally:
        p.end()
    return pm


def _show_splash(app):
    """Startup splash (splash.png next to the app, or bundled)."""
    from PySide6.QtGui import QPixmap
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, "splash.png")
    if not os.path.isfile(path):
        return None
    pm = QPixmap(path)
    if pm.isNull():
        return None
    try:
        _stamp_version(pm)
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    try:
        _stamp_company(pm)
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    splash = QSplashScreen(pm)
    splash.show()
    app.processEvents()
    return splash

def _set_icon(app):
    """Window and taskbar icon (icon.png next to the app, or bundled)."""
    import os
    import sys
    from PySide6.QtGui import QIcon
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    # the .ico holds hand-made 16-256 px images, which stay sharp on the
    # taskbar; the 1024 px PNG is the fallback
    icon = QIcon()
    for name in ("icon.ico", "icon.png"):
        path = os.path.join(base, name)
        if os.path.exists(path):
            icon = QIcon(path)
            if not icon.isNull():
                break
    if not icon.isNull():
        app.setWindowIcon(icon)
        for w in app.topLevelWidgets():
            w.setWindowIcon(icon)
    if sys.platform == "win32":
        try:      # own taskbar button/icon instead of python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "QuantiSheet.App")
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)


if __name__ == "__main__":
    sys.exit(run())
