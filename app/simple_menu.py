"""Simple menus: a calmer ribbon built from one declarative tree.

Six tabs (Home, Takeoff, Markup & Review, Estimate, Reports, Project),
the File button (same File menu as before), and an All Tools tab whose
panel lists every command with a search box and a pin checkbox. Pinned
tools show on Home. "Show advanced tools" adds the less-used groups
(marked ADV below). The old ribbon is kept: the "Simple Menus" toggle on
the File menu (setting "simple_menus", default on) swaps between them.

Commands are found by name with MainWindow.command(), so nothing here
creates or changes an action - it only places existing ones. A name that
no longer exists is skipped and logged, and is still in All Tools.

Hook (main_window.py, after self._build_toolbar()):
    from . import simple_menu
    simple_menu.install(self)
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLineEdit,
                               QToolBar, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from . import icons, settings
from .ribbon import Ribbon, RibbonButton, RibbonGroup, all_actions, clean

log = logging.getLogger(__name__)
ADV = "adv"

# COMPETITOR-FEATURES v2 §6.1: Scale, Length, Area, Count, Cloud, Text,
# Compare, Unpriced Markups
DEFAULT_PINS = ["Calibrate (Set Scale)", "Length", "Area", "Count", "Cloud",
                "Text Box", "Compare", "Show Unpriced Markups"]
# (Nov 4: the same list as the quick bar - quickaccess.DEFAULT_PINS - and
# "Compare" is the one Compare window: Overlay / Changes / Text)
# never behind "advanced" (missed-scope tools)
NEVER_HIDDEN = ["Show Unpriced Markups", "Pre-bid Checklist",
                "Compare Revisions (Overlay)", "Check Takeoff",
                "Calibrate (Set Scale)"]

# (tab, group, [commands], flag)
TREE = [
    ("Home", "File", ["Open", "Save", "Print"], None),
    ("Home", "Edit", ["Undo", "Redo", "Find", "Command Search"], None),
    ("Home", "View", ["Select", "Marquee Zoom", "Fit Width", "Fit Page",
                      "Zoom In", "Zoom Out", "Previous View", "Snapshot",
                      "Field Mode"], None),
    ("Home", "Panels", ["Pages", "Bookmarks", "Quantities", "Markups List",
                        "Properties", "Tool Chest"], None),
    ("Takeoff", "Scale", ["Calibrate (Set Scale)", "Auto Scale (Read Sheets)",
                          "Show Scale", "Viewport (Scale Region)"], None),
    ("Takeoff", "Measure", ["Length", "Polylength", "Area", "Cutout (Deduct)",
                            "Volume"], None),
    ("Takeoff", "Count", ["Count", "Count Symbol", "Count Several Symbols",
                          "Try the Count Library", "Count by Label"], None),
    ("Takeoff", "Auto", ["Trace Length (Click a Line)", "Auto Area (Click a Room)",
                         "Trace Outline (Snap to Drawing)",
                         "Auto Takeoff Rooms on This Sheet",
                         "Auto Takeoff Walls & Doors on This Sheet",
                         "Walls by Role",
                         "Trade Takeoff (Pipe, Duct, Devices, Roof, Rebar, Earthwork)",
                         "Civil Takeoff (Trades)", "AI Takeoff (Whole Set)"], None),
    ("Takeoff", "Site", ["Aerial Photo Page"], None),
    ("Takeoff", "Check", ["Check Takeoff", "Show Unpriced Markups",
                          "Measurement Audit"], None),
    ("Takeoff", "Geometry", ["Angle", "Radius", "Diameter", "Viewports on This Page",
                             "Rooms: Use Tag Area When the Trace Differs"], ADV),
    ("Markup & Review", "Markup", ["Text Box", "Callout", "Cloud", "Rectangle",
                                   "Ellipse", "Arrow", "Line", "Highlight",
                                   "Sticky Note", "Stamp", "Layers"], None),
    ("Markup & Review", "Compare", ["Compare Revisions (Overlay)",
                                    "Quick Compare (Same Sheets)", "Revision Log",
                                    "Batch Slip Sheet"], None),
    ("Markup & Review", "RFIs", ["New RFI", "AI: Find RFIs & Questions",
                                 "RFI / Submittal Log"], None),
    ("Markup & Review", "Scope", ["Pre-bid Checklist"], None),
    ("Markup & Review", "More markup", ["Underline", "Strikeout", "Polyline",
                                        "Polygon", "Pen", "Date Stamp", "Legend",
                                        "Redact", "Markup Color", "Default Style",
                                        "Line Styles", "Hatch Patterns"], ADV),
    ("Markup & Review", "AI", ["AI: Summarize", "AI: Redline", "AI: Spec-Check",
                               "AI: Translate Markups", "Voice Commands"], ADV),
    ("Estimate", "Build", ["Assembly Library", "Take Off Into Assembly",
                           "Cost Books", "Price Database",
                           "Labor Rates & Crews", "Bid Build-up"], None),
    ("Estimate", "Lines", ["Add From Cost Book", "Quick $/SF Estimate",
                           "Model Estimate"],
     None),
    ("Estimate", "Quotes", ["Material & Sub Quotes", "Bid Tabs", "Bid Leveling",
                           "Scope Sheets"], None),
    ("Estimate", "Civil", ["Crew Estimate (Activities)", "Estimate From Takeoff (All Groups)",
                           "Equipment Rates", "Add From Activity Library",
                           "Indirects", "Haul Calculator",
                           "Owner Bid Schedule"], None),
    ("Estimate", "Versions", ["Bid Versions", "Save Bid Version"], None),
    ("Estimate", "Export", ["Export to CivilBid (Excel)"], None),
    ("Estimate", "Coded assemblies", ["Assembly Library (CivilBid codes)",
                                      "Bind Takeoff Group to Assembly",
                                      "Insert Assembly Line",
                                      "Bid Summary (Coded Assemblies)",
                                      "Revision Change Report"], ADV),
    ("Estimate", "Civil setup", ["Crews", "Labor Burden & Wages",
                                 "Import Prevailing Wages (Davis-Bacon)",
                                 "Start From Master Estimate", "Crew Schedule",
                                 "Resources (Hours by Class & Equipment)",
                                 "Import Owner Bid Schedule"], ADV),
    ("Reports", "Proposal", ["Create Proposal"], None),
    ("Reports", "Export", ["Export My Estimate",
                           "Export Estimate (CSV)", "Export Quantities (CSV)",
                           "Link Quantities to Excel",
                           "Export Assembly Estimate (Excel)",
                           "Export Priced Bid Schedule", "Export Cash Flow"], None),
    ("Reports", "Job cost", ["Job Cost Feedback (Bid vs Actual)",
                             "Civil Job Cost (Bid vs Actual)",
                             "Estimating Dashboard"], None),
    ("Project", "Project", ["Project Center", "Weekly Owner Report",
                            "Drawing Register", "Transmittals",
                            "Addenda", "Punch List"], None),
    ("Project", "Schedule", ["Scheduler (Gantt)",
                             "Build Schedule From Plans",
                             "New Schedule"], None),
    ("Project", "Billing", ["Contract & Billing", "Schedule of Values",
                            "Change Orders", "Pay Applications",
                            "Lien Waivers"], None),
    ("Project", "Field", ["Time Cards", "Production History",
                          "Cost to Complete (Forecast)", "Three-Phase Inspections"], None),
    ("Project", "More", ["Generate Set", "Company Directory", "Bid Invites Send As", "New Set From Files", "Open Set",
                         "Search Takeoff Across Jobs", "New Transmittal",
                         "New Punch Item", "Code Check", "New Submittal",
                         "Submittal Review Stamp",
                         "Change Order From Selected Markup"], ADV),
]
TABS = ["Home", "Takeoff", "Markup & Review", "Estimate", "Reports", "Project"]


# short names for long commands (the full name is the tooltip)
SHORT = {"Calibrate (Set Scale)": "Set Scale",
         "Auto Scale (Read Sheets)": "Auto Scale",
         "Viewport (Scale Region)": "Viewport",
         "Estimate From Takeoff (All Groups)": "From Takeoff",
         "Job Cost Feedback (Bid vs Actual)": "Job Cost",
         "Civil Job Cost (Bid vs Actual)": "Civil Job Cost",
         "Estimating Dashboard": "Dashboard",
         "Export Estimate (CSV)": "Estimate CSV",
         "Export My Estimate": "My Estimate",
         "Add From Cost Book": "From Cost Book",
         "Quick $/SF Estimate": "Quick $/SF",
         "Export Quantities (CSV)": "Quantities CSV",
         "Export Assembly Estimate (Excel)": "Estimate Excel",
         "Export to CivilBid (Excel)": "CivilBid",
         "Assembly Library (CivilBid codes)": "Coded Library",
         "Bind Takeoff Group to Assembly": "Bind Group",
         "Take Off Into Assembly": "Into Assembly",
         "Insert Assembly Line": "Insert Line",
         "Bid Summary (Coded Assemblies)": "Bid Summary",
         "Revision Change Report": "Change Report",
         "Show Unpriced Markups": "Unpriced",
         "Compare Revisions (Overlay)": "Overlay",
         "Quick Compare (Same Sheets)": "Quick Compare",
         "Build Schedule From Plans": "Schedule From Plans",
         "Scheduler (Gantt)": "Scheduler",
         "Weekly Owner Report": "Owner Report",
         "Crew Estimate (Activities)": "Crew Estimate",
         "Pay Applications": "Pay Apps",
         "Resources (Hours by Class & Equipment)": "Resources",
         "Import Prevailing Wages (Davis-Bacon)": "Prevailing Wages",
         "Cost to Complete (Forecast)": "Forecast",
         "Trade Takeoff (Pipe, Duct, Devices, Roof, Rebar, Earthwork)":
             "Trades",
         "Civil Takeoff (Trades)": "Civil Takeoff",
         "AI Takeoff (Whole Set)": "AI Takeoff",
         "Auto Takeoff Rooms on This Sheet": "All Rooms",
         "Auto Takeoff Walls & Doors on This Sheet": "Walls & Doors",
         "Trace Length (Click a Line)": "Trace",
         "Auto Area (Click a Room)": "Auto Area",
         "Trace Outline (Snap to Drawing)": "Trace Outline",
         "Count Several Symbols": "Several Symbols",
         "Try the Count Library": "Count Library"}


def short_label(a, limit=16):
    """A button label that fits: the short name, else the name without
    its "(…)", else two lines - never cut off mid-word."""
    full = clean(a.text())
    if full in SHORT:
        return SHORT[full]
    t = a.iconText() if a.iconText() and len(a.iconText()) <= limit \
        else full
    if len(t) > limit and "(" in t:
        t = t.split("(")[0].strip() or t
    if len(t) > limit and " " in t:
        mid = len(t) // 2
        cut = min((i for i, c in enumerate(t) if c == " "),
                  key=lambda i: abs(i - mid))
        t = t[:cut] + "\n" + t[cut + 1:]
    return t


def _key(text):
    return clean(text).replace("…", "").rstrip(". ").strip().lower()


class SimpleMenus:
    def __init__(self, win):
        self.win = win
        self.on = bool(settings.get("simple_menus", False))  # full ribbon by default (Jon)
        self.advanced = bool(settings.get("simple_show_advanced", False))
        self.missing = []
        self.toggle_action = QAction("Simple Menus", win)
        # View > Layout > Simple Menus is the one Ctrl+K lists (open item:
        # "Simple Menus" showed twice in command search)
        self.toggle_action.setProperty("palette_hide", True)
        self.toggle_action.setCheckable(True)
        self.toggle_action.setChecked(self.on)
        self.toggle_action.setToolTip("Turn the simple menus on or off "
                                      "(off goes back to the layout you "
                                      "had before)")
        self.toggle_action.triggered.connect(lambda c=False: self.set_on(c))
        from .ribbon import clean
        exit_a = next((a for a in win._file_menu.actions()
                       if clean(a.text()).lower() == "exit"), None)
        if exit_a is not None:           # Exit stays at the bottom of File
            win._file_menu.insertAction(exit_a, self.toggle_action)
        else:
            win._file_menu.addAction(self.toggle_action)
        self.holder = QToolBar("Simple Ribbon")
        self.holder.setObjectName("simple_ribbon_bar")
        self.holder.setMovable(False)
        self.holder.setFloatable(False)
        self.holder.toggleViewAction().setVisible(False)
        self.holder.setContextMenuPolicy(Qt.PreventContextMenu)
        self.holder.setStyleSheet("QToolBar { padding: 0; margin: 0; }")
        win.addToolBar(Qt.TopToolBarArea, self.holder)
        self.ribbon = None
        self._panel = None
        self.build()
        self.set_on(self.on)

    # ---- build
    def _all(self):
        """Every command the app has: menus, old ribbon, dock toggles."""
        seen, out = set(), []
        for _p, a in all_actions(self.win.menuBar()):
            if id(a) not in seen:
                seen.add(id(a))
                out.append(("menu", _p, a))
        old = getattr(self.win, "ribbon", None)
        if old is not None:
            for name, p in old.pages.items():
                for b in p.findChildren(RibbonButton):
                    a = b.defaultAction()
                    if a is not None and id(a) not in seen:
                        seen.add(id(a))
                        out.append(("ribbon", name, a))
        return out

    def _find(self, name):
        a = self.win.command(name)
        if a is None:
            k = _key(name)
            a = next((x for _s, _p, x in self._all() if _key(x.text()) == k), None)
        return a

    def build(self):
        old_rb = self.ribbon
        rb = Ribbon(self.win)
        rb.app_button.setMenu(self.win._file_menu)
        if hasattr(self.win, "_help_menu"):
            rb.help_button.setMenu(self.win._help_menu)
        rb.search_requested.connect(self.win.command_search)
        if hasattr(self.win, "set_theme"):
            rb.theme_picked.connect(self.win.set_theme)
        self.missing = []
        for tab in TABS:
            rb.page(tab)
        pins = settings.get("pinned_tools") or DEFAULT_PINS
        g = rb.page("Home").group("Pinned")
        g.setObjectName("pinned")
        for n in pins:
            a = self._find(n)
            if a is not None:
                g.large(a, short_label(a))
        for tab, title, names, flag in TREE:
            if flag == ADV and not self.advanced:
                continue
            g = rb.page(tab).group(title)
            acts = []
            for n in names:
                a = self._find(n)
                if a is None:
                    self.missing.append(n)
                    continue
                if a.icon().isNull():
                    tool = a.data() if isinstance(a.data(), str) else None
                    if tool and icons.has(tool):
                        a.setIcon(icons.icon(tool))
                acts.append(a)
            # first three big, the rest small (calm, like PlanSwift's ribbon)
            for a in acts[:3]:
                g.large(a, short_label(a))
            if acts[3:]:
                for i in range(3, len(acts), 3):
                    g.small(acts[i:i + 3])
        tools = rb.page("All Tools").group("All Tools")
        self.all_tools_action = QAction("All Tools…", self.win)
        self.all_tools_action.setIcon(icons.icon("find") if icons.has("find") else self.all_tools_action.icon())
        self.all_tools_action.triggered.connect(lambda: self.all_tools_panel().show())
        tools.large(self.all_tools_action, "All Tools")
        self.adv_action = QAction("Show Advanced Tools", self.win)
        self.adv_action.setCheckable(True)
        self.adv_action.setChecked(self.advanced)
        self.adv_action.triggered.connect(lambda c=False: self.set_advanced(c))
        tools.large(self.adv_action, "Advanced")
        tools.large(self.toggle_action, "Full Ribbon")
        if self.missing:
            log.warning("simple menus: no command named %s", ", ".join(self.missing))
        self.holder.clear()
        self.holder.addWidget(rb)
        self.ribbon = rb
        if old_rb is not None:
            old_rb.deleteLater()

    # ---- switches
    def set_on(self, on, _from_layouts=False):
        lay = getattr(self.win, "layouts", None)
        if lay is not None and not _from_layouts:     # View › Layout decides
            lay.set_layout("simple" if on else lay.before_simple)
            return
        self.on = bool(on)
        settings.set("simple_menus", self.on)
        self.toggle_action.setChecked(self.on)
        if _from_layouts:              # Layouts shows and hides the others
            self.holder.setVisible(self.on)
            return
        # hide before show: two bars side by side widen the window for good
        old = getattr(self.win, "_ribbon_bar", None)
        if self.on:
            if old is not None:
                old.hide()
            self.holder.show()
        else:
            self.holder.hide()
            if old is not None:
                old.show()

    def set_advanced(self, on):
        self.advanced = bool(on)
        settings.set("simple_show_advanced", self.advanced)
        self.build()

    def set_pinned(self, name, on):
        pins = list(settings.get("pinned_tools") or DEFAULT_PINS)
        k = _key(name)
        pins = [p for p in pins if _key(p) != k]
        if on:
            pins.append(name)
        settings.set("pinned_tools", pins)
        self.build()

    # ---- All Tools
    def all_tools_panel(self):
        if self._panel is None:
            self._panel = AllToolsPanel(self)
        self._panel.fill()
        return self._panel


class AllToolsPanel(QDialog):
    """Every command, grouped by where it lives, with search and pins.
    Double-click runs it."""

    def __init__(self, sm):
        super().__init__(sm.win)
        self.sm = sm
        self.setWindowTitle("All Tools")
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type to filter…")
        self.search.textChanged.connect(self._filter)
        row.addWidget(self.search)
        self.adv = QCheckBox("Show advanced tools on the ribbon")
        self.adv.setChecked(sm.advanced)
        self.adv.toggled.connect(sm.set_advanced)
        row.addWidget(self.adv)
        lay.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Command", "Pin", "Shortcut"])
        self.tree.setColumnWidth(0, 340)
        self.tree.itemDoubleClicked.connect(self._run)
        self.tree.itemChanged.connect(self._pin)
        lay.addWidget(self.tree)
        self.resize(620, 640)
        self._acts = []

    def fill(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        self._acts = []
        pins = {_key(p) for p in (settings.get("pinned_tools") or DEFAULT_PINS)}
        groups = {}
        for src, path, a in self.sm._all():
            top = path.split(" › ")[0] if src == "menu" else f"Ribbon: {path}"
            g = groups.get(top)
            if g is None:
                g = groups[top] = QTreeWidgetItem([top])
                self.tree.addTopLevelItem(g)
            it = QTreeWidgetItem([clean(a.text()), "", a.shortcut().toString()])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(1, Qt.Checked if _key(a.text()) in pins else Qt.Unchecked)
            it.setData(0, Qt.UserRole, len(self._acts))
            self._acts.append(a)
            g.addChild(it)
        self.tree.blockSignals(False)

    def actions_listed(self):
        return list(self._acts)

    def _filter(self, text):
        t = text.lower().strip()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            any_ = False
            for j in range(g.childCount()):
                c = g.child(j)
                hide = bool(t) and t not in c.text(0).lower()
                c.setHidden(hide)
                any_ |= not hide
            g.setHidden(not any_)
            g.setExpanded(bool(t))

    def _run(self, item, _col):
        i = item.data(0, Qt.UserRole)
        if i is not None and self._acts[i].isEnabled():
            self.hide()
            self._acts[i].trigger()

    def _pin(self, item, col):
        i = item.data(0, Qt.UserRole)
        if col == 1 and i is not None:
            self.sm.set_pinned(clean(self._acts[i].text()),
                               item.checkState(1) == Qt.Checked)


def reachability(win):
    """{total, in_simple_tree, all_tools_only, unreachable, missing_names}"""
    sm = win.simple_menu
    everything = {id(a) for _s, _p, a in sm._all()}
    tree = {id(b.defaultAction()) for p in sm.ribbon.pages.values()
            for b in p.findChildren(RibbonButton) if b.defaultAction() is not None}
    listed = {id(a) for a in sm.all_tools_panel().actions_listed()}
    return {"total": len(everything), "in_simple_tree": len(everything & tree),
            "all_tools_only": len((everything - tree) & listed),
            "unreachable": len(everything - tree - listed),
            "missing_names": list(sm.missing)}


def install(win):
    win.simple_menu = SimpleMenus(win)
    return win.simple_menu
