"""Weekly Owner Report window (Project > Weekly Owner Report…).

Left: the job's reports, newest first, and New Report (carries last
week's). Tabs:
  Page 1   - report #, week ending, job no./name, the trade boxes as
             printed, the progress bullets (include tick, source, order,
             Draft from Daily Logs, AI Draft), weather days.
  Photos   - add (or drop) photos, pull the week's Daily Log photos, order,
             rotate, include, caption and location; the plan sheet, pins
             on the plan (plan_picker.PlanPicker) and before/after pairs.
  Logs     - RFI / submittal / change order logs attached or not, as-of
             dates; weather threshold and re-pull; forecast table or an
             attached page.
  Add-ons  - every optional section, all off by default; owner decisions;
             the work areas drawn on the plan sheet.
  Export   - photo quality with the estimated file size, Preview, Export
             PDF, Mark as Sent.
The logic is in owner_report.py; slow work (weather, AI, export) runs off
the GUI thread. Every change saves the report."""
import copy
import os
import tempfile

from PySide6.QtCore import QDate, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QAbstractSpinBox,
                               QCheckBox, QComboBox,
                               QDateEdit, QDialog, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox,
                               QSplitter,
                               QTableWidget, QTabWidget, QVBoxLayout,
                               QWidget)

from . import owner_report as orp
from ..dmoney import c2 as _c2

OPTION_LABELS = [
    ("captions", "Photo captions (number, date taken, location)"),
    ("decisions", "Owner decisions needed (page after page 1)"),
    ("schedule", "Schedule status (% complete, days used, milestones, "
                 "recovery)"),
    ("lookahead", "Two-week look-ahead (work and submittals due)"),
    ("weather_gap", "Explain impacted vs claimed weather days"),
    ("counts", "Open / Overdue counts in the LOGS table"),
    ("open_only", "Logs list open items only"),
    ("blank_dates", "Print 01/01/1900 dates as blank"),
    ("manpower", "Manpower this week (from Daily Logs)"),
    ("safety", "Safety line"),
    ("key_plan", "Photo key plan (pins on a plan sheet)"),
    ("work_areas", "Work areas shaded on a plan"),
    ("before_after", "Before / after photo pairs"),
    ("co_log", "Change order log"),
    ("draft_from_logs", "Draft progress from Daily Logs on new reports"),
]
# G30: what the export builds - the form, or the form with the project pack
# (owner_report_auto), the short weekly update or the monthly appendix
REPORT_PRESETS = [("", "Weekly owner report (the form)"),
                  ("full", "Full report with the project pack"),
                  ("weekly", "Weekly update - short (with the pack)"),
                  ("monthly", "Monthly appendix (with the pack)")]
PIN_MARK = "\u25C9 "              # shown before a pinned photo's label
PRESETS = [("email", "Email (recommended)"), ("print", "Print quality"),
           ("small", "Small file"), ("original", "Original photos")]


def _weather_source():
    try:
        from . import weather
        return weather.source_label()
    except Exception:                               # noqa: BLE001
        return "Open-Meteo"


def _num_ui(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _qd(iso):
    d = orp._day(iso)
    return QDate(d.year, d.month, d.day) if d else QDate.currentDate()


def _iso(q):
    return f"{q.year():04d}-{q.month():02d}-{q.day():02d}"


def _mb(n):
    return f"{n / 1e6:.1f} MB"


class _Job(QThread):
    """Run fn() off the GUI thread; done/failed are delivered to bound
    methods of the window (queued onto the GUI thread) as (job, result) so
    each job's result reaches its own handler (job.on_done / on_failed),
    even with two jobs running."""
    done = Signal(object)
    failed = Signal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.on_done = self.on_failed = None
        self.kind, self.over = None, False

    def run(self):
        try:
            out = self.fn()
        except Exception as e:                      # noqa: BLE001
            self.failed.emit((self, str(e) or e.__class__.__name__))
            return
        self.done.emit((self, out))


class OwnerReportWindow(QDialog):
    def __init__(self, store, parent=None, online=True, ask=None):
        super().__init__(parent)
        self.store, self.online, self.ask = store, online, ask
        self.main = parent
        self.rep = None
        self._loading = False
        self._jobs = []
        self.setWindowTitle(f"Weekly Owner Report - {store.name}")
        self.resize(1180, 760)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        root = QHBoxLayout(self)
        split = QSplitter()
        root.addWidget(split)
        # -- the reports
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>Reports</b>"))
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._pick)
        lv.addWidget(self.list, 1)
        b = QPushButton("New Report")
        b.setObjectName("primary")
        b.setToolTip("Next week's report: carries last week's trades, "
                     "progress and open decisions, then fills the logs, "
                     "weather and Daily Log photos")
        b.clicked.connect(lambda: self.new_report())
        lv.addWidget(b)
        left.setMinimumWidth(190)
        split.addWidget(left)
        # -- the tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._page1_tab(), "Page 1")
        self.tabs.addTab(self._photos_tab(), "Photos")
        self.tabs.addTab(self._logs_tab(), "Logs && Weather")
        self.tabs.addTab(self._addons_tab(), "Add-ons")
        self.tabs.addTab(self._export_tab(), "Export")
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.save)
        self._fill_list()
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._enable(False)

    # ================================================================ tabs
    def _page1_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QGridLayout()
        self.no = QLineEdit()
        self.no.setMaximumWidth(70)
        self.we = QDateEdit()
        self.we.setCalendarPopup(True)
        self.we.setDisplayFormat("MM/dd/yyyy")
        self.job_no = QLineEdit()
        self.job_name = QLineEdit()
        for i, (lab, wid) in enumerate((("Report #", self.no),
                                        ("Date (week ending)", self.we),
                                        ("Job number", self.job_no),
                                        ("Job name", self.job_name))):
            f.addWidget(QLabel(lab), i // 2, (i % 2) * 2)
            f.addWidget(wid, i // 2, (i % 2) * 2 + 1)
        v.addLayout(f)
        for wid in (self.no, self.job_no, self.job_name):
            wid.textEdited.connect(self._changed)
        self.we.dateChanged.connect(self._changed)
        box = QGroupBox("Work in progress")
        self.trade_grid = QGridLayout(box)
        self.trade_boxes = {}
        v.addWidget(box)
        pg = QGroupBox("Current progress (unticked lines don't print; grey"
                       " = carried from last week - update them)")
        pv = QVBoxLayout(pg)
        self.bullets = QListWidget()
        self.bullets.setDragDropMode(QAbstractItemView.InternalMove)
        self.bullets.model().rowsMoved.connect(self._changed)
        self.bullets.itemChanged.connect(self._changed)
        pv.addWidget(self.bullets, 1)
        h = QHBoxLayout()
        for text, fn in (("+ Line", self.add_bullet),
                         ("Remove", self.remove_bullet),
                         ("Draft from Daily Logs", self.draft_logs),
                         ("AI Draft…", lambda: self.ai_draft())):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            h.addWidget(b)
            if text.startswith("AI"):
                b.setToolTip("The local AI rewrites the week's Daily Log "
                             "entries for the owner - only what was "
                             "logged, each line keeps its log number")
                self.ai_btn = b
        h.addStretch(1)
        pv.addLayout(h)
        v.addWidget(pg, 1)
        wf = QHBoxLayout()
        self.impacted = QSpinBox()
        self.claimed = QSpinBox()
        for s in (self.impacted, self.claimed):
            s.setRange(0, 9999)
            s.valueChanged.connect(self._changed)
        # with a Rain days list (Logs tab) these are its totals, read-only:
        # page 1, the weather log and the gap line all count that list
        wf.addWidget(QLabel("Impacted weather days"))
        wf.addWidget(self.impacted)
        wf.addWidget(QLabel("Claimed weather days"))
        wf.addWidget(self.claimed)
        wf.addStretch(1)
        v.addLayout(wf)
        return w

    def _photos_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        for text, fn in (("Add Photos…", lambda: self.add_photos()),
                         ("Pull This Week's Daily Log Photos",
                          self.pull_log_photos),
                         ("Rotate", self.rotate_photo),
                         ("Remove", self.remove_photo)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            h.addWidget(b)
        h.addStretch(1)
        self.photo_count = QLabel()
        self.photo_count.setObjectName("muted")
        h.addWidget(self.photo_count)
        v.addLayout(h)
        self.photos = QListWidget()
        self.photos.setViewMode(QListWidget.IconMode)
        self.photos.setIconSize(QSize(160, 120))
        self.photos.setResizeMode(QListWidget.Adjust)
        self.photos.setMovement(QListWidget.Snap)
        self.photos.setDragDropMode(QAbstractItemView.InternalMove)
        self.photos.setSpacing(6)
        self.photos.model().rowsMoved.connect(self._photos_reordered)
        self.photos.itemChanged.connect(self._photo_ticked)
        self.photos.currentRowChanged.connect(self._show_photo)
        v.addWidget(self.photos, 1)
        f = QFormLayout()
        self.caption = QLineEdit()
        self.caption.setPlaceholderText("Shown with captions on (Add-ons)")
        self.location = QLineEdit()
        self.location.setPlaceholderText("Area / room - also used to pair "
                                          "before/after photos")
        self.caption.textEdited.connect(self._photo_text)
        self.location.textEdited.connect(self._photo_text)
        self.view_dir = QComboBox()
        self.view_dir.addItem("-", "")
        for d in orp.VIEW_DIRS:
            self.view_dir.addItem(d, d)
        self.view_dir.setToolTip("The way the camera looked (up the plan "
                                 "sheet = N) - an arrow at the photo's pin "
                                 "on the key plan")
        self.view_dir.currentIndexChanged.connect(self._photo_view)
        f.addRow("Caption", self.caption)
        f.addRow("Location", self.location)
        f.addRow("View (pinned photos)", self.view_dir)
        v.addLayout(f)
        h = QHBoxLayout()
        b = QPushButton("Plan Sheet…")
        b.setToolTip("The plan sheet (PDF and page) for the photo key plan "
                     "and the work areas - kept with the project and "
                     "carried to next week's report")
        b.clicked.connect(lambda: self.choose_plan())
        h.addWidget(b)
        b = QPushButton("Pin on Plan…")
        b.setToolTip("Click on the plan where the selected photo was taken "
                     "(Add-ons: Photo key plan)")
        b.clicked.connect(lambda: self.pin_on_plan())
        h.addWidget(b)
        b = QPushButton("Pair Before/After…")
        b.setToolTip("Match this week's photos to last week's taken at the "
                     "same spot (pins close together, or the same location)"
                     " - Add-ons: Before / after photo pairs")
        b.clicked.connect(lambda: self.pair_before_after())
        h.addWidget(b)
        self.plan_info = QLabel()
        self.plan_info.setObjectName("muted")
        h.addWidget(self.plan_info, 1)
        v.addLayout(h)
        hint = QLabel("Drag photos to change the print order; untick to "
                      "leave one out. Photos fit their frame automatically "
                      "(upright from the camera's orientation).")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.setAcceptDrops(True)
        return w

    def _logs_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Logs attached to the report")
        gl = QGridLayout(g)
        self.log_on, self.log_asof = {}, {}
        for i, (k, lab) in enumerate((("rfi", "RFI log"),
                                      ("submittal", "Submittal log"),
                                      ("co", "Change order log (Add-ons)"))):
            cb = QCheckBox(lab)
            cb.toggled.connect(self._changed)
            d = QDateEdit()
            d.setCalendarPopup(True)
            d.setDisplayFormat("MM/dd/yyyy")
            d.dateChanged.connect(self._changed)
            gl.addWidget(cb, i, 0)
            gl.addWidget(QLabel("As of"), i, 1)
            gl.addWidget(d, i, 2)
            self.log_on[k], self.log_asof[k] = cb, d
        v.addWidget(g)
        wg = QGroupBox("Weather")
        wf = QFormLayout(wg)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.05, 5.0)
        self.threshold.setSingleStep(0.05)
        self.threshold.setSuffix(" in. of rain on a workday")
        self.threshold.valueChanged.connect(self._changed)
        wf.addRow("A weather day is", self.threshold)
        self.weather_info = QLabel()
        self.weather_info.setWordWrap(True)
        wf.addRow(self.weather_info)
        h = QHBoxLayout()
        self.weather_source = QLabel("Weather source: " + _weather_source())
        self.weather_source.setWordWrap(True)
        h.addWidget(self.weather_source, 1)
        b = QPushButton("API Key…")
        b.setToolTip("Use an Open-Meteo commercial plan (API key) instead "
                     "of the free, non-commercial service")
        b.clicked.connect(lambda: self.set_weather_key())
        h.addWidget(b)
        wf.addRow(h)
        self.gap_note = QLineEdit()
        self.gap_note.setPlaceholderText("Optional: your own explanation of "
                                         "impacted vs claimed days")
        self.gap_note.textEdited.connect(self._changed)
        wf.addRow("Weather note", self.gap_note)
        self.days = QTableWidget(0, 3)
        self.days.setHorizontalHeaderLabels(["Date", "Rain (in.)",
                                             "Claimed"])
        self.days.setToolTip("Type or correct each day's rain from "
                             "Wunderground; untick Claimed for a day you "
                             "won't claim. Page 1's counts follow this.")
        self.days.itemChanged.connect(self._day_edited)
        self.days.setMinimumHeight(160)
        wf.addRow("Rain days", self.days)
        h = QHBoxLayout()
        b = QPushButton("+ Day")
        b.clicked.connect(lambda _c=False: self.add_day())
        h.addWidget(b)
        b = QPushButton("Fill From Weather History")
        b.setToolTip("A starting point: rain history since the job started "
                     "(Open-Meteo). Rain you typed and days you changed are "
                     "kept.")
        b.clicked.connect(lambda: self.update_weather())
        h.addWidget(b)
        h.addStretch(1)
        wf.addRow(h)
        v.addWidget(wg)
        fg = QGroupBox("10-day forecast page")
        fl = QVBoxLayout(fg)
        self.forecast_mode = QComboBox()
        self.forecast_mode.addItem("Your Wunderground screenshot (or a PDF "
                                   "page)", "attach")
        self.forecast_mode.addItem("A generated 10-day table", "table")
        self.forecast_mode.currentIndexChanged.connect(self._forecast_mode)
        fl.addWidget(self.forecast_mode)
        h = QHBoxLayout()
        b = QPushButton("Open Wunderground")
        b.setToolTip("Opens this job's Wunderground 10-day page (you paste "
                     "the link once per job)")
        b.clicked.connect(lambda: self.open_wunderground())
        h.addWidget(b)
        b = QPushButton("Paste Forecast Screenshot")
        b.setObjectName("primary")
        b.setToolTip("Take the screenshot (Windows + Shift + S), then click "
                     "here")
        b.clicked.connect(lambda: self.paste_forecast())
        h.addWidget(b)
        b = QPushButton("Pick File…")
        b.clicked.connect(lambda: self.pick_forecast())
        h.addWidget(b)
        h.addStretch(1)
        fl.addLayout(h)
        self.forecast_info = QLabel()
        self.forecast_info.setObjectName("muted")
        fl.addWidget(self.forecast_info)
        v.addWidget(fg)
        v.addStretch(1)
        return w

    def _addons_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        note = QLabel("All off = the report looks exactly like your "
                      "current form. Turn on what this owner wants.")
        note.setObjectName("muted")
        v.addWidget(note)
        g = QGridLayout()
        self.opt = {}
        for i, (k, lab) in enumerate(OPTION_LABELS):
            cb = QCheckBox(lab)
            cb.toggled.connect(self._changed)
            g.addWidget(cb, i // 2, i % 2)
            self.opt[k] = cb
        v.addLayout(g)
        h = QHBoxLayout()
        b = QPushButton("Plan Sheet…")
        b.clicked.connect(lambda: self.choose_plan())
        h.addWidget(b)
        b = QPushButton("Work Areas…")
        b.setToolTip("Draw this week's work areas on the plan sheet "
                     "(Add-on: Work areas shaded on a plan)")
        b.clicked.connect(lambda: self.edit_work_areas())
        h.addWidget(b)
        self.areas_info = QLabel()
        self.areas_info.setObjectName("muted")
        h.addWidget(self.areas_info, 1)
        v.addLayout(h)
        h = QHBoxLayout()
        h.addWidget(QLabel("Photos per page"))
        self.per_page = QComboBox()
        self.per_page.addItem("4 (as the form)", 4)
        self.per_page.addItem("6", 6)
        self.per_page.addItem("3 (one large)", 3)
        self.per_page.addItem("2 (large)", 2)
        self.per_page.currentIndexChanged.connect(self._changed)
        h.addWidget(self.per_page)
        h.addWidget(QLabel("Look-ahead"))
        self.la_weeks = QComboBox()
        self.la_weeks.addItem("2 weeks", 2)
        self.la_weeks.addItem("3 weeks", 3)
        self.la_weeks.currentIndexChanged.connect(self._changed)
        h.addWidget(self.la_weeks)
        h.addStretch(1)
        v.addLayout(h)
        dg = QGroupBox("Owner decisions needed (with the Add-on on)")
        dv = QVBoxLayout(dg)
        self.dec = QTableWidget(0, 5)
        self.dec.setHorizontalHeaderLabels(["Decision needed", "Needed by "
                                            "(MM/DD/YYYY)", "If late",
                                            "Ref", "Done"])
        self.dec.horizontalHeader().setStretchLastSection(False)
        self.dec.setColumnWidth(0, 300)
        self.dec.itemChanged.connect(self._changed)
        dv.addWidget(self.dec)
        h = QHBoxLayout()
        b = QPushButton("+ Decision")
        b.clicked.connect(self.add_decision)
        h.addWidget(b)
        b = QPushButton("Propose from Project Data")
        b.setToolTip("Overdue RFIs, potential and pending changes, critical "
                     "submittals, open weather notices and the owner's open "
                     "issues, with the effect of a late answer. Rows you "
                     "typed stay; edit before export.")
        b.clicked.connect(self.propose_actions)
        h.addWidget(b)
        h.addStretch(1)
        dv.addLayout(h)
        v.addWidget(dg, 1)
        sgp = QGroupBox("Executive summary (project pack; blank = drafted "
                        "at export)")
        sv = QVBoxLayout(sgp)
        self.summary = QPlainTextEdit()
        self.summary.setPlaceholderText(
            "Draft it from the project data, then edit. Printed as typed.")
        self.summary.setMaximumHeight(90)
        self.summary.textChanged.connect(self._changed)
        sv.addWidget(self.summary)
        h = QHBoxLayout()
        b = QPushButton("Draft from Project Data")
        b.setToolTip("Rule-based draft from the schedule, logs, changes and "
                     "weather as of the report date (no AI, works offline)")
        b.clicked.connect(self.draft_summary)
        h.addWidget(b)
        h.addStretch(1)
        sv.addLayout(h)
        v.addWidget(sgp)
        lg = QGroupBox("Site logistics (project pack; carried to next "
                       "week's report)")
        lv = QVBoxLayout(lg)
        self.logistics = QPlainTextEdit()
        self.logistics.setPlaceholderText("One note a line: entrance, haul "
                                          "route, laydown, parking, hours")
        self.logistics.setMaximumHeight(60)
        self.logistics.textChanged.connect(self._changed)
        lv.addWidget(self.logistics)
        v.addWidget(lg)
        sg = QHBoxLayout()
        sg.addWidget(QLabel("Safety line"))
        self.safety = QLineEdit()
        self.safety.setPlaceholderText("Blank = first safety note from the "
                                       "week's Daily Logs")
        self.safety.textEdited.connect(self._changed)
        sg.addWidget(self.safety, 1)
        v.addLayout(sg)
        return w

    def _export_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        f = QFormLayout()
        self.preset = QComboBox()
        for k, lab in PRESETS:
            self.preset.addItem(lab, k)
        self.preset.currentIndexChanged.connect(self._changed)
        self.report_preset = QComboBox()
        for k, lab in REPORT_PRESETS:
            self.report_preset.addItem(lab, k)
        self.report_preset.setToolTip(
            "Weekly: page 1, this week's detail and the photos (8-10 "
            "pages). Monthly: the dashboard, schedule, weather, budget, "
            "changes, aging, risks and the logs, without page 1 or photos.")
        self.report_preset.currentIndexChanged.connect(self._changed)
        f.addRow("Report", self.report_preset)
        f.addRow("Photo quality", self.preset)
        self.size = QLabel()
        f.addRow("Estimated size", self.size)
        v.addLayout(f)
        h = QHBoxLayout()
        b = QPushButton("Preview")
        b.clicked.connect(lambda: self.preview())
        h.addWidget(b)
        b = QPushButton("Export PDF…")
        b.setObjectName("primary")
        b.clicked.connect(lambda: self.export())
        h.addWidget(b)
        self.sent_btn = QPushButton("Mark as Sent")
        self.sent_btn.clicked.connect(self.mark_sent)
        h.addWidget(self.sent_btn)
        h.addStretch(1)
        v.addLayout(h)
        self.export_info = QLabel()
        self.export_info.setWordWrap(True)
        v.addWidget(self.export_info)
        b = QPushButton("Company Template…")
        b.setToolTip("Logo, company name and address, trade list")
        b.clicked.connect(self.edit_template)
        v.addWidget(b, 0, Qt.AlignLeft)
        v.addStretch(1)
        return w

    # ================================================================ list
    def _fill_list(self, select=None):
        self.list.blockSignals(True)
        self.list.clear()
        for r in reversed(orp.reports(self.store)):
            it = QListWidgetItem(f"#{r.get('report_no', '')}  "
                                 f"{orp.mdy(r.get('week_ending'))}  "
                                 f"{r.get('status', 'Draft')}")
            it.setData(Qt.UserRole, r["_id"])
            self.list.addItem(it)
            if select and r["_id"] == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)

    def _pick(self, cur, _prev=None):
        if cur is None:
            return
        self.save()
        rec = self.store.get(orp.COLL, cur.data(Qt.UserRole))
        if rec:
            self.load(rec)

    def _enable(self, on):
        self.tabs.setEnabled(on)

    def new_report(self, wait=False):
        if self._busy("new"):
            return
        self.save()
        # built off the GUI thread, saved here (on the GUI thread): saving
        # fires the store's listeners, which touch Project Center widgets
        self._run(lambda: orp.new_report(self.store, online=self.online,
                                         save_it=False),
                  self._new_done, "Making the report…", wait, kind="new")

    def _new_done(self, rep):
        orp.save(self.store, rep)
        self._fill_list(select=rep["_id"])
        self.load(rep)
        self._toast(f"Report #{rep['report_no']} started")

    # ================================================================ load
    def load(self, rep):
        self.rep = rep
        self._loading = True
        self._enable(True)
        t = orp.template_for(rep)
        self.no.setText(str(rep.get("report_no") or ""))
        self.we.setDate(_qd(rep.get("week_ending")))
        hd = rep.get("header") or {}
        self.job_no.setText(hd.get("job_no") or "")
        self.job_name.setText(hd.get("job_name") or "")
        # trades: the printed 4 columns
        while self.trade_grid.count():
            it = self.trade_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.trade_boxes = {}
        on = set(rep.get("trades") or [])
        for c, col in enumerate(orp.trade_list(t)):
            for r, name in enumerate(col):
                cb = QCheckBox(name)
                cb.setChecked(name in on)
                src = (rep.get("trades_src") or {}).get(name)
                if src:
                    cb.setToolTip(f"Ticked from {src}")
                cb.toggled.connect(lambda v, n=name: self._trade(n, v))
                self.trade_grid.addWidget(cb, r, c)
                self.trade_boxes[name] = cb
        self._fill_bullets()
        w = rep.get("weather") or {}
        self._weather_boxes()
        self.threshold.setValue(float(w.get("threshold_in") or 0.5))
        self.gap_note.setText(w.get("gap_note") or "")
        self._weather_info()
        self._fill_days()
        for k, cb in self.log_on.items():
            lg = (rep.get("logs") or {}).get(k) or {}
            cb.setChecked(lg.get("attached", True))
            self.log_asof[k].setDate(_qd(lg.get("as_of") or rep.get("date")))
        fm = (rep.get("forecast") or {}).get("mode") or "attach"
        self.forecast_mode.setCurrentIndex(max(
            0, self.forecast_mode.findData(fm)))
        self._forecast_info()
        opts = orp.options(rep)
        for k, cb in self.opt.items():
            cb.setChecked(bool(opts.get(k)))
        self.per_page.setCurrentIndex(max(0, self.per_page.findData(
            int(opts.get("photos_per_page") or 4))))
        self.preset.setCurrentIndex(max(0, self.preset.findData(
            opts.get("size_preset") or "email")))
        rp = str(opts.get("report_preset") or "")
        if not rp and opts.get("auto_pack"):
            rp = "full"
        self.report_preset.setCurrentIndex(max(
            0, self.report_preset.findData(rp)))
        self.summary.setPlainText(rep.get("summary_text") or "")
        self.logistics.setPlainText(rep.get("logistics") or "")
        self.la_weeks.setCurrentIndex(max(0, self.la_weeks.findData(
            3 if int(_num_ui(opts.get("lookahead_weeks"))) == 3 else 2)))
        self._fill_decisions()
        self.safety.setText(rep.get("safety") or "")
        self._fill_photos()
        self._loading = False
        self._refresh_export()

    def _fill_bullets(self):
        self.bullets.blockSignals(True)
        self.bullets.clear()
        for b in self.rep.get("progress") or []:
            it = QListWidgetItem(b.get("text") or "")
            it.setFlags(it.flags() | Qt.ItemIsEditable |
                        Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            it.setCheckState(Qt.Checked if b.get("include", True)
                             else Qt.Unchecked)
            src = b.get("src") or "typed"
            it.setData(Qt.UserRole, src)
            it.setToolTip(f"From {src}")
            if src == "carried":
                it.setForeground(Qt.gray)
            self.bullets.addItem(it)
        self.bullets.blockSignals(False)

    def _fill_decisions(self):
        self.dec.blockSignals(True)
        self.dec.setRowCount(0)
        from PySide6.QtWidgets import QTableWidgetItem
        for d in self.rep.get("decisions") or []:
            r = self.dec.rowCount()
            self.dec.insertRow(r)
            for c, k in enumerate(("text", "due", "impact", "ref")):
                v = d.get(k) or ""
                if k == "due" and v:
                    v = orp.mdy(v)
                self.dec.setItem(r, c, QTableWidgetItem(v))
            done = QTableWidgetItem()
            done.setFlags(done.flags() | Qt.ItemIsUserCheckable)
            done.setCheckState(Qt.Checked if d.get("done") else Qt.Unchecked)
            self.dec.setItem(r, 4, done)
        self.dec.blockSignals(False)

    def _fill_photos(self):
        self.photos.blockSignals(True)
        self.photos.clear()
        for ph in sorted(self.rep.get("photos") or [],
                         key=lambda p: p.get("order") or 0):
            it = QListWidgetItem(self._photo_label(ph))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable |
                        Qt.ItemIsDragEnabled)
            it.setCheckState(Qt.Checked if ph.get("include", True)
                             else Qt.Unchecked)
            it.setData(Qt.UserRole, orp._photo_key(ph.get("ref")))
            it.setIcon(self._thumb(ph))
            if ph.get("pin"):
                it.setToolTip("Pinned on the key plan")
            self.photos.addItem(it)
        self.photos.blockSignals(False)
        n = len(orp.printed_photos(self.rep))
        per = orp.photos_a_page(
            orp.options(self.rep).get("photos_per_page"))
        self.photo_count.setText(f"{n} photo(s) print on "
                                 f"{-(-n // per)} page(s)")
        self._plan_info()

    def _plan_info(self):
        kp = (self.rep or {}).get("key_plan") or {}
        sheet = kp.get("sheet")
        if not sheet:
            self.plan_info.setText("No plan sheet yet")
        else:
            name = sheet.get("name") if isinstance(sheet, dict) else \
                os.path.basename(str(sheet))
            pins = sum(1 for p in orp.printed_photos(self.rep)
                       if p.get("pin"))
            self.plan_info.setText(f"Plan: {name}, page "
                                   f"{int(kp.get('page') or 0) + 1} - "
                                   f"{pins} photo(s) pinned")
        n = sum(1 for a in (self.rep or {}).get("work_areas") or []
                if len(a.get("pts") or []) >= 3)
        self.areas_info.setText(f"{n} work area(s)" if n else
                                "No work areas yet")

    def _photo_label(self, ph):
        t = orp._taken_text(ph) if hasattr(orp, "_taken_text") else ""
        text = (orp.photo_location(self.rep or {}, ph) or ph.get("caption")
                or "")[:24] or t
        if ph.get("pin"):
            text = PIN_MARK + text
        if ph.get("pair_with"):
            text += " (+before)"
        return text

    def _thumb(self, ph):
        try:
            path = self.store.attachment_path(ph["ref"])
        except Exception:                           # noqa: BLE001
            return QIcon()
        pm = QPixmap(path)
        if pm.isNull():
            return QIcon()
        if ph.get("rotate"):
            from PySide6.QtGui import QTransform
            pm = pm.transformed(QTransform().rotate(ph["rotate"]))
        return QIcon(pm.scaled(160, 120, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation))

    # ================================================================ edits
    def _changed(self, *_):
        if self._loading or self.rep is None:
            return
        self._read()
        self._save_timer.start()
        self._refresh_export()

    def _read(self):
        r = self.rep
        r["report_no"] = self.no.text().strip()
        r["week_ending"] = r["date"] = _iso(self.we.date())
        r.setdefault("header", {}).update(job_no=self.job_no.text(),
                                          job_name=self.job_name.text())
        bl = []
        for i in range(self.bullets.count()):
            it = self.bullets.item(i)
            if it.text().strip():
                bl.append({"text": it.text().strip(),
                           "include": it.checkState() == Qt.Checked,
                           "src": it.data(Qt.UserRole) or "typed"})
        r["progress"] = bl
        w = r.setdefault("weather", {})
        if w.get("days"):                   # the list's totals, one source
            imp, cl = orp.weather_counts(r)
        else:                               # no list: the typed totals
            imp, cl = self.impacted.value(), self.claimed.value()
        w.update(impacted=imp, claimed=cl,
                 threshold_in=_c2(self.threshold.value()),
                 gap_note=self.gap_note.text())
        for k, cb in self.log_on.items():
            r.setdefault("logs", {}).setdefault(k, {}).update(
                attached=cb.isChecked(), as_of=_iso(self.log_asof[k].date()))
        opts = r.setdefault("options", {})
        for k, cb in self.opt.items():
            opts[k] = cb.isChecked()
        opts["photos_per_page"] = self.per_page.currentData()
        opts["size_preset"] = self.preset.currentData()
        rp = self.report_preset.currentData() or ""
        opts["report_preset"] = "" if rp == "full" else rp
        if rp:                       # the pack drawn from the project data
            opts["owner_pack"] = opts["auto_pack"] = True
        else:
            opts["auto_pack"] = False
        r["summary_text"] = self.summary.toPlainText().strip()
        r["logistics"] = self.logistics.toPlainText().strip()
        opts["lookahead_weeks"] = self.la_weeks.currentData() or 2
        decs = []
        for row in range(self.dec.rowCount()):
            get = lambda c: (self.dec.item(row, c).text().strip()  # noqa
                             if self.dec.item(row, c) else "")
            if not get(0):
                continue
            due = get(1)
            try:
                import datetime as _dt
                due = _dt.datetime.strptime(due, "%m/%d/%Y").date() \
                    .isoformat() if due else ""
            except ValueError:
                pass
            done = self.dec.item(row, 4)
            decs.append({"text": get(0), "due": due, "impact": get(2),
                         "ref": get(3), "done": bool(
                             done and done.checkState() == Qt.Checked)})
        r["decisions"] = decs
        r["safety"] = self.safety.text()

    def _trade(self, name, on):
        if self._loading or self.rep is None:
            return
        orp.set_trade(self.rep, name, on)
        self._save_timer.start()

    def add_bullet(self):
        it = QListWidgetItem("New line - type the work done")
        it.setFlags(it.flags() | Qt.ItemIsEditable | Qt.ItemIsUserCheckable
                    | Qt.ItemIsDragEnabled)
        it.setCheckState(Qt.Checked)
        it.setData(Qt.UserRole, "typed")
        self.bullets.addItem(it)
        self.bullets.editItem(it)
        self._changed()

    def remove_bullet(self):
        r = self.bullets.currentRow()
        if r >= 0:
            self.bullets.takeItem(r)
            self._changed()

    def draft_logs(self):
        if self.rep is None:
            return
        self._read()
        orp.draft_from_daily_logs(self.store, self.rep)
        self.save()
        self.load(self.rep)
        n = sum(1 for b in self.rep.get("progress") or []
                if str(b.get("src", "")).startswith("DL"))
        self._toast(f"{n} line(s) from this week's Daily Logs")

    def ai_draft(self, wait=False):
        if self.rep is None or self._busy("ai"):
            return
        self._read()
        rep = copy.deepcopy(self.rep)
        self.ai_btn.setEnabled(False)
        self.ai_btn.setText("AI working…")

        def run():
            orp.ai_draft_progress(self.store, rep, ask=self.ask)
            return rep
        self._run(run, self._ai_done, None, wait, self._ai_failed,
                  kind="ai")

    def _ai_done(self, rep):
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("AI Draft…")
        rep = self._fold("ai", rep)
        fb = (rep.get("ai") or {}).get("fallback")
        self._toast("AI couldn't run - drafted from the logs as written ("
                    f"{fb})" if fb else "AI draft ready - check every line")

    def _ai_failed(self, msg):
        self.ai_btn.setEnabled(True)
        self.ai_btn.setText("AI Draft…")
        QMessageBox.warning(self, "AI Draft", msg)

    def add_decision(self):
        from PySide6.QtWidgets import QTableWidgetItem
        r = self.dec.rowCount()
        self.dec.insertRow(r)
        done = QTableWidgetItem()
        done.setFlags(done.flags() | Qt.ItemIsUserCheckable)
        done.setCheckState(Qt.Unchecked)
        self.dec.setItem(r, 4, done)
        self.dec.setCurrentCell(r, 0)
        self.dec.editItem(self.dec.item(r, 0) or QTableWidgetItem())

    # ---------------------------------------------------------------- photos
    def draft_summary(self):
        """G04: the executive summary drafted by rules from the project
        data as of the report date, into the box for the PM to edit."""
        if self.rep is None:
            return
        from . import owner_report_auto as ora
        self._read()
        txt = " ".join(ora.draft_summary(self.store, self.rep, short=True))
        self.summary.setPlainText(txt)
        self._changed()

    def propose_actions(self):
        """G05: owner actions proposed from the project data, added to
        the decisions table (rows already there stay as typed)."""
        if self.rep is None:
            return
        from . import owner_report_auto as ora
        self._read()
        n = ora.merge_decisions(self.rep,
                                ora.propose_decisions(self.store, self.rep))
        self._fill_decisions()
        self._changed()
        self._toast(f"{n} owner action(s) proposed - edit before export"
                    if n else "No new owner actions from the project data")

    def add_photos(self, paths=None):
        if self.rep is None:
            return []
        if paths is None:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Add Photos", "",
                "Photos (*.jpg *.jpeg *.png *.heic *.tif *.tiff)")
        if not paths:
            return []
        self._read()
        added = orp.add_photos(self.store, self.rep, list(paths))
        self.save()
        self._fill_photos()
        self._refresh_export()
        return added

    def pull_log_photos(self):
        if self.rep is None:
            return []
        self._read()
        added = orp.photos_from_daily_logs(self.store, self.rep) or []
        self.save()
        self._fill_photos()
        self._refresh_export()
        self._toast(f"{len(added)} photo(s) from this week's Daily Logs")
        return added

    def _photo(self, row):
        it = self.photos.item(row)
        if it is None:
            return None
        key = it.data(Qt.UserRole)
        return next((p for p in self.rep.get("photos") or []
                     if orp._photo_key(p.get("ref")) == key), None)

    def _photos_reordered(self, *_):
        for i in range(self.photos.count()):
            ph = self._photo(i)
            if ph:
                ph["order"] = i + 1
        self._save_timer.start()

    def _photo_ticked(self, it):
        ph = self._photo(self.photos.row(it))
        if ph is not None:
            ph["include"] = it.checkState() == Qt.Checked
            self._save_timer.start()
            self._refresh_export()

    def _show_photo(self, row):
        ph = self._photo(row)
        self._loading = True
        self.caption.setText((ph or {}).get("caption") or "")
        self.location.setText((ph or {}).get("location") or "")
        pin = (ph or {}).get("pin") or {}
        self.view_dir.setCurrentIndex(max(0, self.view_dir.findData(
            str(pin.get("view") or "").upper())))
        self.view_dir.setEnabled(bool(pin))
        self._loading = False

    def _photo_view(self, *_):
        ph = self._photo(self.photos.currentRow())
        if ph is None or self._loading or not ph.get("pin"):
            return
        v = self.view_dir.currentData() or ""
        if v:
            ph["pin"]["view"] = v
        else:
            ph["pin"].pop("view", None)
        self._save_timer.start()

    def _photo_text(self, *_):
        ph = self._photo(self.photos.currentRow())
        if ph is None or self._loading:
            return
        ph["caption"] = self.caption.text()
        ph["location"] = self.location.text()
        self._save_timer.start()

    def rotate_photo(self):
        row = self.photos.currentRow()
        ph = self._photo(row)
        if ph is None:
            return
        ph["rotate"] = (int(ph.get("rotate") or 0) + 90) % 360
        self.photos.item(row).setIcon(self._thumb(ph))
        self._save_timer.start()

    # ---------------------------------------------------------------- plan
    def choose_plan(self, path=None, page=None):
        """Pick the plan sheet (a PDF and a page) for the key plan and the
        work areas; the PDF is attached to the project so the report
        travels with it. Returns rep["key_plan"] or None."""
        if self.rep is None:
            return None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Plan Sheet", "",
                                                  "PDF (*.pdf)")
        if not path:
            return None
        import fitz
        try:
            with fitz.open(path) as d:
                n = d.page_count
        except Exception as e:                      # noqa: BLE001
            QMessageBox.warning(self, "Plan Sheet",
                                f"Can't open that PDF: {e}")
            return None
        if n < 1:
            return None
        if page is None:
            page = 0
            if n > 1:
                from PySide6.QtWidgets import QInputDialog
                v, ok = QInputDialog.getInt(self, "Plan Sheet",
                                            f"Page (1 - {n}):", 1, 1, n)
                if not ok:
                    return None
                page = v - 1
        page = max(0, min(n - 1, int(page)))
        self._read()
        ref = self.store.attach(path)
        old = self.rep.get("key_plan") or {}
        same = orp._sheet_key(old.get("sheet")) == orp._sheet_key(ref) and \
            int(old.get("page") or 0) == page
        self.rep["key_plan"] = {"sheet": ref, "page": page,
                                "clip": old.get("clip") if same else None}
        self.store.set_setting("owner_report_key_plan",
                               copy.deepcopy(self.rep["key_plan"]))
        self.save()
        self._plan_info()
        self._toast(f"Plan sheet: {ref.get('name')}, page {page + 1}")
        return self.rep["key_plan"]

    def _need_plan(self):
        if (self.rep.get("key_plan") or {}).get("sheet"):
            return True
        last = self.store.setting("owner_report_key_plan")
        if last and last.get("sheet"):       # the project's last plan sheet
            self.rep["key_plan"] = copy.deepcopy(last)
            return True
        return bool(self.choose_plan())

    def plan_picker(self, mode, photo=None):
        """The PlanPicker for this report (pins or work areas); changes
        save as they're made."""
        from .plan_picker import PlanPicker
        if self.rep is None or not self._need_plan():
            return None
        self._read()
        try:
            return PlanPicker(self.store, lambda: self.rep, mode, photo,
                              self, changed=self._plan_changed)
        except Exception as e:                      # noqa: BLE001
            QMessageBox.warning(self, "Plan Sheet",
                                f"Can't open the plan sheet: {e}")
            return None

    def _plan_changed(self):
        self._save_timer.start()
        self._plan_info()

    def _plan_done(self):
        self.save()
        row = self.photos.currentRow()
        self._fill_photos()
        if 0 <= row < self.photos.count():
            self.photos.setCurrentRow(row)
        self._refresh_export()

    def pin_on_plan(self):
        if self.rep is None:
            return None
        d = self.plan_picker("pin", self._photo(self.photos.currentRow()))
        if d is None:
            return None
        if not self.opt["key_plan"].isChecked():
            self.opt["key_plan"].setChecked(True)
        d.exec()
        self._plan_done()
        return d

    def edit_work_areas(self):
        if self.rep is None:
            return None
        d = self.plan_picker("areas")
        if d is None:
            return None
        if not self.opt["work_areas"].isChecked():
            self.opt["work_areas"].setChecked(True)
        d.exec()
        self._plan_done()
        return d

    def pair_before_after(self):
        """Suggested before/after pairs, each with a tick; the ticked ones
        are kept (orp.accept_pairs). Returns the dialog."""
        if self.rep is None:
            return None
        self._read()
        pairs = orp.suggest_pairs(self.rep)
        if not pairs:
            QMessageBox.information(
                self, "Before / After",
                "No pairs found. Pairs need last week's photos (New Report "
                "carries them) pinned close to this week's on the same "
                "plan, or with the same Location.")
            return None
        d = PairDialog(self, pairs)
        if d.exec():
            self.apply_pairs(d.chosen())
        return d

    def apply_pairs(self, pairs):
        orp.accept_pairs(self.rep, pairs)
        if pairs and not self.opt["before_after"].isChecked():
            self.opt["before_after"].setChecked(True)
        self.save()
        self._fill_photos()
        self._refresh_export()
        self._toast(f"{len(pairs)} before/after pair(s)")

    def remove_photo(self):
        row = self.photos.currentRow()
        ph = self._photo(row)
        if ph is None:
            return
        self.rep["photos"].remove(ph)
        self._photos_reordered()
        self._fill_photos()
        self._refresh_export()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if os.path.splitext(u.toLocalFile())[1].lower() in
                 (".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff")]
        if paths:
            self.add_photos(paths)
            self.tabs.setCurrentIndex(1)
            e.acceptProposedAction()

    # ---------------------------------------------------------------- weather
    def _weather_boxes(self):
        """Page 1's impacted / claimed boxes: the Rain days list's totals
        (read-only) when there is a list, else typed totals."""
        w = (self.rep or {}).get("weather") or {}
        listed = bool(w.get("days"))
        imp, cl = orp.weather_counts(self.rep or {})
        was = self._loading
        self._loading = True
        for box, v in ((self.impacted, imp), (self.claimed, cl)):
            box.setValue(v)
            box.setReadOnly(listed)
            sym = QAbstractSpinBox.ButtonSymbols
            box.setButtonSymbols(sym.NoButtons if listed
                                 else sym.UpDownArrows)
            box.setToolTip("Totals of the Rain days list (Logs tab) - "
                           "change a day there; page 1, the weather log "
                           "and the gap line all count that list."
                           if listed else
                           "No Rain days list yet: the number typed here "
                           "prints on page 1.")
        self._loading = was

    def _weather_info(self):
        w = (self.rep or {}).get("weather") or {}
        days = w.get("days") or []
        self.weather_source.setText(
            "Weather source: " + _weather_source())
        if not days:
            self.weather_info.setText("No rain history yet - Update "
                                      "Weather.")
            return
        imp, cl = orp.weather_counts(self.rep)
        self.weather_info.setText(
            f"Rain history {orp.mdy(days[0].get('date'))} - "
            f"{orp.mdy(days[-1].get('date'))}: {len(days)} days; page 1 "
            f"and the log page show {imp} impacted, {cl} claimed.")

    def set_weather_key(self, key=None):
        """The Open-Meteo commercial API key (Settings "weather_api_key").
        Set, the weather goes to the customer servers with the key; blank,
        back to the free (non-commercial) servers."""
        from .. import secretstore           # DPAPI (threat model T-014)
        if key is None:
            from PySide6.QtWidgets import QInputDialog
            key, ok = QInputDialog.getText(
                self, "Weather Source",
                "Open-Meteo commercial API key (blank = the free, "
                "non-commercial service):", QLineEdit.EchoMode.Password,
                secretstore.get_secret("weather_api_key") or "")
            if not ok:
                return
        secretstore.set_secret("weather_api_key", (key or "").strip())
        self._weather_info()

    def update_weather(self, wait=False):
        if self.rep is None or self._busy("weather"):
            return
        self._read()
        rep = copy.deepcopy(self.rep)
        before = copy.deepcopy(rep.get("weather") or {})

        def run():
            orp.fill_weather(self.store, rep, online=self.online)
            orp.fill_forecast(self.store, rep, online=self.online)
            return rep
        self._run(run, self._weather_done, "Getting weather…", wait,
                  kind="weather", before=before)

    def _weather_done(self, rep, before=None):
        self._fold("weather", rep, before)
        self._toast("Weather and forecast updated")

    def _forecast_mode(self, *_):
        if self._loading or self.rep is None:
            return
        fc = self.rep.setdefault("forecast", {})
        fc["mode"] = self.forecast_mode.currentData()
        self._forecast_info()
        self._save_timer.start()

    def _forecast_info(self):
        fc = (self.rep or {}).get("forecast") or {}
        if fc.get("mode") == "attach":
            self.forecast_info.setText(
                f"Screenshot attached (as of {orp.mdy(fc.get('as_of'))})."
                if fc.get("attach_ref") else
                "No screenshot yet: Open Wunderground, take a screenshot "
                "(Windows + Shift + S), then Paste Forecast Screenshot.")
        else:
            self.forecast_info.setText(
                f"{len(fc.get('rows') or [])} forecast days (Open-Meteo)."
                if fc.get("rows") else "No forecast yet - Fill From "
                "Weather History also gets the forecast.")

    def open_wunderground(self, url=None):
        """The job's Wunderground page (asked once, kept in the project's
        settings)."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from ..main_window import link_scheme
        from_store = not url
        url = url or self.store.setting("wunderground_url") or ""
        typed = False
        if not url:
            url, ok = QInputDialog.getText(
                self, "Wunderground", "Paste this job's Wunderground 10-day "
                "forecast link (from your browser's address bar):")
            url = url.strip() if ok else ""
            if not url:
                return None
            if not url.lower().startswith(("http://", "https://")):
                url = "https://" + url
            typed = True
        # the stored link comes from the project's settings (shared, synced):
        # open only a web address, never file:, a program's own scheme or a
        # share - the same check as links in PDFs
        if link_scheme(url) not in ("http", "https"):
            QMessageBox.warning(
                self, "Wunderground", "That isn't a web address (http or "
                "https), so it wasn't opened. Paste the forecast link from "
                "your browser's address bar.")
            if from_store and not typed:     # ask again next time
                self.store.set_setting("wunderground_url", "")
            return None
        if typed:
            self.store.set_setting("wunderground_url", url)
        if not os.environ.get("QUANTISHEET_NO_OPEN"):
            QDesktopServices.openUrl(QUrl(url))
        return url

    def _set_forecast_file(self, path):
        fc = self.rep.setdefault("forecast", {})
        fc["attach_ref"] = self.store.attach(path)
        fc["mode"] = "attach"
        fc["as_of"] = _iso(QDate.currentDate())
        self._loading = True
        self.forecast_mode.setCurrentIndex(self.forecast_mode.findData(
            "attach"))
        self._loading = False
        self.save()
        self._forecast_info()
        self._refresh_export()

    def paste_forecast(self, image=None):
        """The screenshot on the clipboard becomes the forecast page."""
        if self.rep is None:
            return None
        from PySide6.QtWidgets import QApplication
        img = image if image is not None else \
            QApplication.clipboard().image()
        if img is None or img.isNull():
            QMessageBox.information(
                self, "Paste Forecast Screenshot",
                "There's no picture on the clipboard. Take the screenshot "
                "with Windows + Shift + S first, then click Paste.")
            return None
        path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),
                            f"forecast {_iso(QDate.currentDate())}.png")
        img.save(path, "PNG")
        self._set_forecast_file(path)
        self._toast("Forecast screenshot added")
        return path

    def pick_forecast(self, path=None):
        if self.rep is None:
            return None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Forecast Page", "",
                "Image or PDF (*.png *.jpg *.jpeg *.pdf)")
        if path:
            self._set_forecast_file(path)
        return path

    # ---------------------------------------------------------------- rain days
    def _fill_days(self):
        from PySide6.QtWidgets import QTableWidgetItem
        self.days.blockSignals(True)
        self.days.setRowCount(0)
        for d in reversed((self.rep.get("weather") or {}).get("days") or []):
            r = self.days.rowCount()
            self.days.insertRow(r)
            it = QTableWidgetItem(orp.mdy(d.get("date")))
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            it.setData(Qt.UserRole, d.get("date"))
            self.days.setItem(r, 0, it)
            rain = d.get("rain_in")
            ri = QTableWidgetItem("" if rain is None else f"{_c2(float(rain)):.2f}")
            if d.get("source") == "typed":
                dl = d.get("download_in")
                ri.setToolTip("Typed" + ("" if dl is None else
                                         f" (download {_c2(float(dl)):.2f} in)"))
            self.days.setItem(r, 1, ri)
            c = QTableWidgetItem()
            c.setFlags(c.flags() | Qt.ItemIsUserCheckable)
            c.setCheckState(Qt.Checked if d.get("claimed") else Qt.Unchecked)
            self.days.setItem(r, 2, c)
        self.days.blockSignals(False)

    def _day_edited(self, it):
        if self._loading or self.rep is None:
            return
        w = self.rep.setdefault("weather", {})
        date_iso = self.days.item(it.row(), 0).data(Qt.UserRole)
        day = next((d for d in w.get("days") or []
                    if d.get("date") == date_iso), None)
        if day is None:
            return
        if it.column() == 1:
            try:
                day["rain_in"] = _c2(float(it.text() or 0))
            except ValueError:
                return
            day["tracked"] = day["rain_in"] >= float(
                w.get("threshold_in") or 0.5)
            day["source"] = "typed"         # a re-pull keeps this amount
        elif it.column() == 2:
            day["claimed"] = it.checkState() == Qt.Checked
        day["edited"] = True
        self._weather_totals()

    def _weather_totals(self):
        w = self.rep.setdefault("weather", {})
        w["impacted"], w["claimed"] = orp.weather_counts(self.rep)
        self._weather_boxes()
        self._weather_info()
        self._save_timer.start()

    def add_day(self, iso=None, rain=0.0):
        from PySide6.QtWidgets import QInputDialog
        if self.rep is None:
            return
        if iso is None:
            text, ok = QInputDialog.getText(self, "Rain Day",
                                            "Date (MM/DD/YYYY):")
            if not ok or not text.strip():
                return
            import datetime as _dt
            try:
                iso = _dt.datetime.strptime(text.strip(), "%m/%d/%Y") \
                    .date().isoformat()
            except ValueError:
                QMessageBox.warning(self, "Rain Day", "Type the date as "
                                    "MM/DD/YYYY.")
                return
        w = self.rep.setdefault("weather", {})
        days = w.setdefault("days", [])
        if not any(d.get("date") == iso for d in days):
            import datetime as _dt
            wd = _dt.date.fromisoformat(iso).weekday() < 5
            thr = float(w.get("threshold_in") or 0.5)
            days.append({"date": iso, "rain_in": float(rain),
                         "tracked": float(rain) >= thr,
                         "claimed": wd and float(rain) >= thr,
                         "note": "", "edited": True, "source": "typed"})
            days.sort(key=lambda d: d.get("date") or "")
        self._fill_days()
        self._weather_totals()

    # ---------------------------------------------------------------- export
    def _refresh_export(self):
        if self.rep is None:
            self.size.setText("")
            return
        try:
            n = orp.estimate_size(self.store, self.rep,
                                  self.preset.currentData())
        except Exception as e:                      # noqa: BLE001
            self.size.setText(f"(can't estimate: {e})")
            return
        warn = n > 5_000_000
        self.size.setText(
            f"<b style='color:{'#b9770e' if warn else 'inherit'}'>about "
            f"{_mb(n)}</b>" + (" - over 5 MB, too big for most email; "
                               "pick Email or Small" if warn else ""))
        ex = self.rep.get("exported") or []
        self.export_info.setText(
            (f"Last exported {ex[-1]['at'][:16].replace('T', ' ')}: "
             f"{ex[-1]['path']} ({_mb(ex[-1]['bytes'])})" if ex else
             "Not exported yet.") + f"  Status: {self.rep.get('status')}")
        self.sent_btn.setText("Mark as Draft" if self.rep.get("status") ==
                              "Sent" else "Mark as Sent")

    def preview(self, wait=False):
        if self.rep is None:
            return
        self._read()
        self.save()
        rep = copy.deepcopy(self.rep)
        path = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),
                            orp.file_name(rep))

        def run():
            orp.build_pdf(self.store, rep, path)
            return path
        self._run(run, self._open_pdf, "Building the preview…", wait)

    def export(self, folder=None, wait=False):
        if self.rep is None or self._busy("export"):
            return
        self._read()
        self.save()
        rep = copy.deepcopy(self.rep)

        def run():
            res = orp.export(self.store, rep, folder, save_it=False)
            res["_rep"] = rep
            return res
        self._run(run, self._export_done, "Exporting…", wait,
                  kind="export")

    def _export_done(self, res):
        self._fold("export", res.pop("_rep"))
        self._fill_list(select=self.rep["_id"])
        self._refresh_export()
        self._toast(f"Saved {os.path.basename(res['path'])} "
                    f"({_mb(res['bytes'])}, {res['pages']} pages)")
        self._open_pdf(res["path"])
        self.last_export = res

    def _open_pdf(self, path):
        self.last_pdf = path
        if self.main is not None and hasattr(self.main, "open_path") and \
                not os.environ.get("QUANTISHEET_NO_OPEN"):
            self.main.open_path(path)

    def mark_sent(self):
        if self.rep is None:
            return
        orp.mark_sent(self.store, self.rep,
                      self.rep.get("status") != "Sent")
        self._fill_list(select=self.rep["_id"])
        self._refresh_export()

    def edit_template(self):
        TemplateDialog(self).exec()
        if self.rep is not None:
            self.load(self.rep)

    # ---------------------------------------------------------------- plumbing
    def save(self):
        self._save_timer.stop()
        if self.rep is None or self._loading:
            return
        if any(j.isRunning() for j in self._jobs):
            self._save_timer.start()        # after the background job
            return
        saved = orp.save(self.store, self.rep)
        if isinstance(saved, dict) and saved.get("_id"):
            self.rep = saved
        cur = self.list.currentItem()
        if cur is not None:
            cur.setText(f"#{self.rep.get('report_no', '')}  "
                        f"{orp.mdy(self.rep.get('week_ending'))}  "
                        f"{self.rep.get('status', 'Draft')}")

    def _busy(self, kind):
        """A job of this kind is already running (one at a time each)."""
        return any(j.kind == kind and not j.over for j in self._jobs)

    def _fold(self, kind, done, before=None):
        """A job's report back into the live one - only the fields the job
        owns (orp.JOB_FIELDS), so what the PM typed while it ran stays -
        then saved. The job's report is no longer open: folded into its
        stored record instead. Returns the report folded into."""
        rid = done.get("_id")
        if self.rep is not None and (rid is None or
                                     self.rep.get("_id") == rid):
            self._read()
            orp.merge_job_result(self.store, self.rep, kind, done, before)
            self.save()                     # (waits for a job still running)
            self.load(self.rep)
            return self.rep
        rec = self.store.get(orp.COLL, rid) if rid else None
        if rec is None:
            return done
        orp.merge_job_result(self.store, rec, kind, done, before)
        orp.save(self.store, rec)
        return rec

    def _run(self, fn, done, busy=None, wait=False, failed=None, kind=None,
             before=None):
        """fn() in the background; done(result) back on the GUI thread -
        this job's own done / failed, never another job's."""
        job = _Job(fn)
        job.kind = kind
        if before is not None:
            job.on_done = lambda out: done(out, before)
        else:
            job.on_done = done
        job.on_failed = failed or self._failed
        self._jobs.append(job)
        job.done.connect(self._job_done)
        job.failed.connect(self._job_failed)
        if busy:
            self.setCursor(Qt.BusyCursor)
            self._toast(busy)
        job.start()
        if wait:
            from PySide6.QtWidgets import QApplication
            job.wait()
            for _ in range(5):
                QApplication.processEvents()
        return job

    def _job_done(self, payload):
        job, out = payload
        self._job_over(job)
        job.on_done(out)

    def _job_failed(self, payload):
        job, msg = payload
        self._job_over(job)
        job.on_failed(msg)

    def _job_over(self, job):
        job.over = True                     # its kind may run again
        self._jobs = [j for j in self._jobs if j.isRunning()]
        if not any(not j.over for j in self._jobs):
            self.unsetCursor()

    def _failed(self, msg):
        QMessageBox.warning(self, "Weekly Owner Report", msg)

    def _toast(self, text):
        self.setWindowTitle(f"Weekly Owner Report - {self.store.name}  "
                            f"·  {text}")

    def closeEvent(self, e):
        self.save()
        for j in self._jobs:
            j.wait(30000)
        super().closeEvent(e)


class PairDialog(QDialog):
    """Suggested before/after pairs with ticks (all ticked)."""

    def __init__(self, win, pairs):
        super().__init__(win)
        self.setWindowTitle("Pair Before / After Photos")
        self.pairs = list(pairs)
        self.ok = False
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Untick a pair that isn't the same spot:"))
        self.list = QListWidget()
        self.list.setIconSize(QSize(96, 72))
        for after, before in self.pairs:
            loc = orp.photo_location(win.rep, after) or \
                after.get("caption") or (after.get("ref") or {}).get(
                    "name", "")
            bl = before.get("location") or before.get("caption") or \
                (before.get("ref") or {}).get("name", "")
            how = "pins close together" if after.get("pin") and \
                before.get("pin") else "same location"
            it = QListWidgetItem(f"This week: {loc}   <-   last week: {bl}"
                                 f"   ({how})")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setIcon(win._thumb(after))
            self.list.addItem(it)
        v.addWidget(self.list, 1)
        h = QHBoxLayout()
        h.addStretch(1)
        b = QPushButton("Keep Ticked Pairs")
        b.setObjectName("primary")
        b.clicked.connect(self._keep)
        h.addWidget(b)
        b = QPushButton("Cancel")
        b.clicked.connect(self.reject)
        h.addWidget(b)
        v.addLayout(h)
        self.resize(640, 420)

    def chosen(self):
        return [p for i, p in enumerate(self.pairs)
                if self.list.item(i).checkState() == Qt.Checked]

    def _keep(self):
        self.ok = True
        self.accept()


class TemplateDialog(QDialog):
    """The company template: logo, company block, title, trades."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Owner Report - Company Template")
        self.t = orp.load_template()
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit((self.t.get("company") or {}).get("name", ""))
        self.lines = QLineEdit(" | ".join((self.t.get("company") or {})
                                          .get("lines", [])))
        self.lines.setPlaceholderText("Address | City, ST zip | Phone")
        self.title = QLineEdit(self.t.get("title") or "")
        self.logo = QLabel(os.path.basename(self.t.get("logo") or "") or
                           "(none)")
        lb = QPushButton("Logo…")
        lb.clicked.connect(self._logo)
        hl = QHBoxLayout()
        hl.addWidget(self.logo, 1)
        hl.addWidget(lb)
        f.addRow("Company name", self.name)
        f.addRow("Address lines", self.lines)
        f.addRow("Report title", self.title)
        f.addRow("Logo", hl)
        v.addLayout(f)
        v.addWidget(QLabel("Trades (4 columns, one per line, a blank line "
                           "between columns):"))
        from PySide6.QtWidgets import QPlainTextEdit
        self.trades = QPlainTextEdit("\n\n".join(
            "\n".join(col) for col in orp.trade_list(self.t)))
        v.addWidget(self.trades, 1)
        h = QHBoxLayout()
        h.addStretch(1)
        ok = QPushButton("Save")
        ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        h.addWidget(ok)
        c = QPushButton("Cancel")
        c.clicked.connect(self.reject)
        h.addWidget(c)
        v.addLayout(h)

    def _logo(self):
        p, _ = QFileDialog.getOpenFileName(self, "Logo", "",
                                           "Images (*.png *.jpg *.jpeg)")
        if p:
            self.t["logo"] = p
            self.logo.setText(os.path.basename(p))

    def _save(self):
        self.t["company"] = {"name": self.name.text().strip(),
                             "lines": [s.strip() for s in
                                       self.lines.text().split("|")
                                       if s.strip()]}
        self.t["title"] = self.title.text().strip() or \
            "Project Progress Report"
        cols = [[s.strip() for s in block.splitlines() if s.strip()]
                for block in self.trades.toPlainText().split("\n\n")]
        cols = [c for c in cols if c][:4]
        if cols:
            self.t["trades"] = cols
        orp.save_template(self.t)
        self.accept()


def open_report(store, parent=None):
    w = OwnerReportWindow(store, parent)
    w.show()
    if parent is not None:
        parent._owner_report = w
    return w
