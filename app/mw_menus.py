"""The menus and the ribbon: what is on them and in which order (split out
of main_window.py, Nov 25).
"""
import logging

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QApplication, QToolBar
from . import icons, settings, takeoff
from .main_window import TOOL_MENU, log


class MenusMixin:
    """MainWindow's menus methods (see main_window.py)."""

    def _build_menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._file_menu = f
        # One column that fits a laptop screen (Chief's user test, Nov 6:
        # 40-odd top-level rows spilled into two columns). Related commands
        # sit in submenus; every command keeps its name and shortcut.
        self._act(f, "Open…", QKeySequence.Open, self.open_file, False)
        self._act(f, "New Window", None, lambda: self.new_window(), False)
        self.recent_menu = f.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        self._act(f, "Open Bid Download (.zip) as a Job…", None,
                  lambda: self.open_bid_zip(), False)
        self._act(f, "Open Project Folder…", None, self._choose_project, False)
        self._act(f, "Close Tab", QKeySequence.Close,
                  lambda: self.close_tab(self.tabs.currentIndex()))
        f.addSeparator()
        self._act(f, "Save", QKeySequence.Save, self.save_file)
        self._act(f, "Save As…", QKeySequence.SaveAs, self.save_as)
        self.autosave_action = self._act(f, "AutoSave", None,
                                         lambda: self.toggle_autosave(),
                                         False)
        self.autosave_action.setCheckable(True)
        self._act(f, "Recover Unsaved Files…", None,
                  lambda: self.recover_unsaved(ask_if_none=True), False)
        cs = f.addMenu("Copies && Cloud")
        self._act(cs, "Work on a Local Copy", None,
                  lambda: self.work_on_local_copy())
        self._act(cs, "Copy Back to the Original", None,
                  lambda: self.copy_back_original())
        # Open from / Save to Dropbox (hidden when IT turns Dropbox off)
        from . import dropbox_ui
        dropbox_ui.add_actions(self, cs)
        self._act(cs, "Version History…", None, self.show_versions)
        f.addSeparator()
        new = f.addMenu("Create")
        self._act(new, "New From Form Library…", "Ctrl+Shift+N",
                  lambda: self.new_from_form(), False)
        self._act(new, "Generate Set…", None, lambda: self.generate_set(),
                  False)
        self._act(new, "Create PDF From File…", None, self.create_pdf, False)
        self._act(new, "Combine Files…", None, self.combine_files, False)
        imp = f.addMenu("Import")
        self._act(imp, "Import AutoCAD DXF…", None, lambda: self.import_dxf(),
                  False)
        self._act(imp, "Import Markups (PDF or XFDF)…", None,
                  self.import_markups)
        exp = f.addMenu("Export To")
        self._act(exp, "Word Document (.docx)…", None,
                  lambda: self.export_as("docx"))
        self._act(exp, "Excel Workbook (.xlsx)…", None,
                  lambda: self.export_as("xlsx"))
        self._act(exp, "PowerPoint (.pptx)…", None,
                  lambda: self.export_as("pptx"))
        self._act(exp, "Web Page (.html)…", None,
                  lambda: self.export_as("html"))
        self._act(exp, "Text (.txt)…", None, lambda: self.export_as("txt"))
        self._act(exp, "AutoCAD DXF (this page)…", None,
                  lambda: self.export_dxf())
        self._act(exp, "Google Earth (KML, aerial page markups)…", None,
                  lambda: self.export_geo("kml"))
        self._act(exp, "GIS (GeoJSON, aerial page markups)…", None,
                  lambda: self.export_geo("geojson"))
        self._act(exp, "PDF/A (archival)…", None, lambda: self.export_pdfa())
        self._act(exp, "External Issue (strip pricing)…", None,
                  lambda: self.export_external())
        self._act(exp, "Images (PNG)…", None, lambda: self.export_as("png"))
        self._act(exp, "Images (JPEG)…", None, lambda: self.export_as("jpg"))
        exp.addSeparator()
        self._act(exp, "Export Markups (XFDF)…", None, self.export_xfdf)
        cmp_ = f.addMenu("Compare")
        self._act(cmp_, "Compare…", "Ctrl+Alt+C", lambda: self.compare())
        self._act(cmp_, "Compare Text With…", None, self.compare_with)
        self._act(cmp_, "Compare Revisions (Overlay)…", "Ctrl+Alt+O",
                  self.compare_revisions)
        self._act(cmp_, "Quick Compare (Same Sheets)…", None,
                  self.compare_visual)
        prot = f.addMenu("Protect && Repair")
        self._act(prot, "Password Protect…", None, self.protect)
        self._act(prot, "Remove Security…", None, self.unprotect)
        self._act(prot, "Remove Hidden Information…", None, self.sanitize)
        prot.addSeparator()
        self._act(prot, "Reduce File Size…", None, self.reduce_size)
        self._act(prot, "Check / Repair PDF…", None, self.check_repair)
        sig = f.addMenu("Sign")
        self._act(sig, "Sign…", None, self.sign)
        self._act(sig, "Verify Signatures…", None, self.verify)
        self._act(sig, "Signing Timestamp Server…", None,
                  lambda: self.timestamp_server(), False)
        f.addSeparator()
        self._act(f, "Print…", QKeySequence.Print, self.print_doc)
        self._act(f, "Print Preview…", None, self.print_preview)
        self._act(f, "Document Properties…", "Ctrl+D", self.doc_properties)
        self._act(f, "Attachments…", None, lambda: self.attachments())
        f.addSeparator()
        self._act(f, "Exit", QKeySequence.Quit, self.close, False)

        e = mb.addMenu("&Edit")
        self._undo_act = self._act(e, "Undo", QKeySequence.Undo, self.undo)
        self._redo_act = self._act(e, "Redo", QKeySequence.Redo, self.redo)
        # both redo keys on every platform, and Ctrl+Shift+Z never falls
        # through to Undo (Chief's estimator test, Nov 7)
        self._undo_act.setShortcuts([QKeySequence("Ctrl+Z")])
        self._redo_act.setShortcuts([QKeySequence("Ctrl+Y"),
                                     QKeySequence("Ctrl+Shift+Z")])
        e.addSeparator()
        self._act(e, "Copy Text", QKeySequence.Copy, self.copy_text)
        self._act(e, "Copy as Table (for Excel)", "Ctrl+Shift+C",
                  self.copy_table)
        self._act(e, "Select All Text on Page", QKeySequence.SelectAll,
                  self.select_all_text)
        self._act(e, "Copy All Text on This Page", None,
                  lambda: self.copy_text(page=True))
        self._act(e, "Paste", QKeySequence.Paste, lambda: self.paste())
        self._act(e, "Paste Image", None,
                  lambda: self._view and self._view.paste_image())
        self._act(e, "Delete Selected Markup", QKeySequence.Delete,
                  lambda: self._view and self._view.delete_selected())
        self._act(e, "Add Selected Markup to Tool Chest…", None,
                  self.add_selected_to_chest)
        e.addSeparator()
        self._act(e, "Find…", QKeySequence.Find, self.find)
        e.addSeparator()
        self._act(e, "Author Name…", None, self.set_author, False)
        e.addSeparator()

        v = mb.addMenu("&View")
        for d in (self.thumb_dock, self.takeoff_dock, self.bm_dock,
                  self.docs_dock, self.chest_dock, self.props_dock,
                  self.markups_dock, self.asm_dock, self.est_dock,
                  self.qty_dock):
            v.addAction(d.toggleViewAction())
        a = self._act(v, "Bottom Panels (Markups, Estimate…)", "F9",
                      lambda: self.toggle_bottom_panels(), False)
        a.setCheckable(True)
        self.bottom_act = a
        v.addSeparator()
        self._act(v, "Next Page", "PgDown",
                  lambda: self._view and self._view.next_page())
        self._act(v, "Previous Page", "PgUp",
                  lambda: self._view and self._view.prev_page())
        self._act(v, "Go to Page…", "Ctrl+G", self.go_to_page)
        self._act(v, "First Page", "Ctrl+Home",
                  lambda: self.page_nav.first())
        self._act(v, "Last Page", "Ctrl+End", lambda: self.page_nav.last())
        v.addSeparator()
        self._act(v, "Zoom In", QKeySequence.ZoomIn, lambda: self._zoom(1.25))
        self._act(v, "Zoom Out", QKeySequence.ZoomOut, lambda: self._zoom(0.8))
        self._act(v, "Fit Width", "Ctrl+2", self.fit_width)
        self._act(v, "Fit Page", "Ctrl+0", self.fit_page)
        self._act(v, "Previous View", "Alt+Left", self.previous_view)
        self._act(v, "Actual Size", "Ctrl+1", lambda: self._view and
                  self._view.set_zoom(QApplication.primaryScreen()
                                      .logicalDotsPerInch() / 72))
        v.addSeparator()
        self.snap_action = QAction("Snap to Content", self, checkable=True)
        self.snap_action.setShortcut("Shift+F9")
        self.snap_action.setToolTip("Snap drawing and measuring to line "
                                    "ends, corners and intersections (Shift+F9)")
        self.snap_action.setChecked(settings.get("snap", True) is not False)
        self.snap_action.toggled.connect(self.set_snap)
        v.addAction(self.snap_action)
        self.thin_action = QAction("Enhance Thin Lines", self)
        self.thin_action.setCheckable(True)
        self.thin_action.setToolTip("Draw hairlines at least one screen "
                                    "pixel wide, so drawings stay crisp "
                                    "when zoomed out")
        self.thin_action.setChecked(settings.get("thin_lines", True)
                                    is not False)
        self.thin_action.toggled.connect(self.set_thin_lines)
        v.addAction(self.thin_action)
        v.addSeparator()
        tm = v.addMenu("Theme")
        tg = QActionGroup(self)
        from . import theme as _theme
        self._theme_actions = []          # Python-owned (Grok N5): an action
        for key, label in (("system", "Follow Windows"), ("dark", "Dark"),
                           ("light", "Light")):     # made by addAction(text)
            ta = QAction(label, self)              # could lose its wrapper
            tm.addAction(ta)
            self._theme_actions.append(ta)
            ta.setCheckable(True)
            ta.setChecked(_theme.mode() == key)
            ta.triggered.connect(lambda _c=False, k=key: self.set_theme(k))
            tg.addAction(ta)
        self._act(v, "Command Search…", "Ctrl+K",
                  lambda: self.command_search(), False)
        self._act(v, "Show Ribbon", "Ctrl+F1",
                  lambda: self.active_ribbon().set_collapsed(
                      not self.active_ribbon().collapsed), False)
        # Takeoff Studio pieces (Chief's v24 / v26)
        v.addSeparator()
        from . import snap_indicator as _si
        sm = v.addMenu("Snap Modes")
        self._snap_mode_actions = {}
        on = _si.load_modes()
        for m in _si.ORDER:
            ma = sm.addAction(m)
            ma.setCheckable(True)
            ma.setChecked(m in on)
            ma.toggled.connect(lambda _c=False: self._set_snap_modes())
            self._snap_mode_actions[m] = ma
        self._field_action = self._act(v, "Field Mode", "Ctrl+5",
                                       lambda: self.toggle_field_mode(),
                                       False)
        self._field_action.setCheckable(True)
        dm = v.addMenu("Density")
        dg = QActionGroup(self)
        from . import field_mode as _fm
        cur = settings.get("density", "comfortable")
        for name in _fm.DENSITY:
            da = QAction(name.title(), self)      # Python-owned, as above
            dm.addAction(da)
            da.setCheckable(True)
            da.setChecked(name == cur)
            da.triggered.connect(lambda _c=False, n=name:
                                 self.set_density(n))
            dg.addAction(da)
        self._view_menu_bar = v
        # Color Takeoff By (Nov 4 takeoff list #6)
        cm = v.addMenu("Color Takeoff By")
        cg = QActionGroup(self)
        for label, mode in (("Off", None), ("Item", "item"),
                            ("Status", "status"),
                            ("Priced / Not Priced", "priced")):
            ca = QAction(label, self)
            ca.setCheckable(True)
            ca.setChecked(mode is None)
            ca.triggered.connect(lambda _c=False, m=mode: self.color_by(m))
            cg.addAction(ca)
            cm.addAction(ca)
        # ribbon tabs (Nov 4, fewer clicks): quickaccess.py
        tm = v.addMenu("Ribbon Tabs")
        for label, key, default in (
                ("Show All Tabs", "show_all_tabs", False),
                ("Tabs Follow the Open File", "tabs_follow_file", True),
                ("Classic Tabs (all 14, next start)", "classic_tabs", False)):
            ta = QAction(label, self)
            ta.setCheckable(True)
            ta.setChecked(bool(settings.get(key, default)))
            ta.triggered.connect(lambda c=False, k=key: self._tab_option(k, c))
            tm.addAction(ta)
        tm.addSeparator()
        self._act(tm, "Choose My Role (Estimator, PM, Service, Office)…", None,
                  lambda: self._choose_role(), False)
        dbl = QAction("Double-Click Edits PDF Text", self)
        dbl.setCheckable(True)
        dbl.setChecked(bool(settings.get("dblclick_edits_text", True)))
        dbl.triggered.connect(lambda c=False: settings.set(
            "dblclick_edits_text", bool(c)))
        v.addAction(dbl)

        menus = {"Markup": mb.addMenu("&Markup"), "Edit": e, "View": v}
        menus["Fill & Sign"] = mb.addMenu("F&ill && Sign")
        menus["Takeoff"] = mb.addMenu("&Takeoff")
        for menu, label, tool, key, _tb in TOOL_MENU:
            m = menus[menu]
            if label is None:
                m.addSeparator()
                continue
            a = self._act(m, label, key,
                          lambda checked=False, t=tool: self.set_tool(t))
            a.setCheckable(True)
            a.setData(tool)
            a.setIcon(icons.icon(tool))
            a.setToolTip(f"{label} ({key})" if key else label)
            self._tools.addAction(a)
            self._tool_actions[tool] = a
        self._tool_actions[None].setChecked(True)
        mk = menus["Markup"]
        mk.addSeparator()
        self._act(mk, "Markup Color…", None, self.pick_color)
        self._act(mk, "Default Style", None, self.reset_color)
        self._act(mk, "Refresh Legends", None, self.refresh_legends)
        lsm = mk.addMenu("Legend Style")
        self._legend_style_group = QActionGroup(self)
        for key, text in (("takeoff", "Takeoff (quantities only)"),
                          ("classic", "Classic (counts + 2 decimals)")):
            a = lsm.addAction(text)
            a.setCheckable(True)
            a.setChecked(settings.get("legend_style", "takeoff") == key)
            a.triggered.connect(
                lambda checked=False, k=key: settings.set("legend_style", k))
            self._legend_style_group.addAction(a)
        mk.addSeparator()
        self._act(mk, "Line Styles…", None, self.line_styles, False)
        self._act(mk, "Hatch Patterns…", None, self.hatch_patterns, False)
        self._act(mk, "Layers…", None, self.layers)

        fsm = menus["Fill & Sign"]
        fsm.addSeparator()
        self._act(fsm, "Fill From the Job and Sign…", None,
                  lambda: self.fill_from_job_and_sign(), False)
        self._act(fsm, "Change Signature…", None,
                  lambda: self._redraw_signature("signature"), False)
        self._act(fsm, "Change Initials…", None,
                  lambda: self._redraw_signature("initials"), False)

        t = menus["Takeoff"]
        self._act(t, "Count From a Picture…", None,
                  lambda: self.count_from_picture())
        t.addSeparator()
        presets = t.addMenu("Scale Presets")
        for family, items in takeoff.PRESETS.items():
            sub = presets.addMenu(family)
            for name, (ppu, unit) in items:
                a = self._act(sub, name, None,
                              lambda _=False, n=name, p=ppu, u=unit:
                              self.apply_scale_preset(n, p, u))
        self._act(t, "Auto Scale (Read Sheets)…", None,
                  lambda: self.sheet_setup(scales=True, bookmarks=False))
        self._act(t, "Auto Scale (Check Against Dimensions)…", None,
                  lambda: self._boost("autoscale"))
        self._act(t, "Auto Takeoff (Review)…", "Ctrl+Alt+R",
                  lambda: self._boost("autotakeoff_review"))
        self._act(t, "Show Scale", None, self.show_scale)
        sl = t.addMenu("Show Side Lengths")
        self._side_group = QActionGroup(self)
        for key, text in (("off", "Off"), ("selected", "Selected Markup"),
                          ("all", "All Measurements on the Page")):
            act = sl.addAction(text)
            act.setCheckable(True)
            act.setChecked(settings.get("side_lengths", "off") == key)
            act.triggered.connect(
                lambda checked=False, k=key: self.set_side_lengths(k))
            self._side_group.addAction(act)
        from . import measure_extra as _mx
        cm = t.addMenu("Captions")
        self._caption_group = QActionGroup(self)
        for key, text in _mx.CAPTIONS.items():
            act = cm.addAction(text)
            act.setCheckable(True)
            act.setChecked(_mx.caption_mode() == key)
            act.triggered.connect(
                lambda checked=False, k=key: self.set_captions(k))
            self._caption_group.addAction(act)
        self._act(t, "Viewports on This Page…", None, self.manage_viewports)
        t.addSeparator()
        self._act(t, "Takeoff Standard…", None, self.takeoff_standard)
        t.addSeparator()
        self._act(t, "Count by Label…", None, self.auto_count_label)
        from . import takeoff_assist_ui as _tau
        self._act(t, "Count Several Symbols…", None,
                  lambda: _tau.count_several(self))
        self._act(t, "Try the Count Library…", None,
                  self.try_count_library)
        self._act(t, "Item Names Learned…", None, self.item_names_learned,
                  False)
        self._act(t, "Auto Takeoff Rooms on This Sheet…", "Ctrl+Shift+R",
                  self.auto_takeoff_rooms)
        a = self._act(t, "Rooms: Use Tag Area When the Trace Differs",
                      None, lambda: self.toggle_room_tag_area(), False)
        a.setCheckable(True)
        a.setChecked(bool(settings.get("rooms_use_tag_area", True)))
        self.room_tag_act = a
        self._act(t, "Auto Takeoff Walls && Doors on This Sheet…",
                  "Ctrl+Shift+W", self.auto_walls)
        self._act(t, "Walls by Role…", None,
                  lambda: _tau.walls_by_role(self))
        self._act(t, "Change Wall Role of Selection…", None,
                  lambda: _tau.change_wall_role(self))
        a = self._act(t, "Trace Outline: Follow Drawn Lines", None,
                      lambda: None, False)
        a.setCheckable(True)
        a.setChecked(_tau.trace_follow())
        a.toggled.connect(_tau.set_trace_follow)
        self.trace_follow_act = a
        self._act(t, "Trade Takeoff (Pipe, Duct, Devices, Roof, Rebar, "
                  "Earthwork)…", "Ctrl+Alt+T", self.trade_takeoff)
        self._act(t, "Check Takeoff…", "Ctrl+Alt+K", self.check_takeoff)
        self.roof_act = self._act(t, "Roof Plan Takeoff…", None,
                                  self.roof_takeoff)
        on = bool(settings.get("roof_takeoff", False))
        self.roof_act.setVisible(on)
        a = t.addAction("Show Roof Plan Tools")
        a.setCheckable(True)
        a.setChecked(on)
        a.toggled.connect(self._show_roof_tools)
        # Nov 23 (Jon): quantities from a 3D (IFC) model - its own 3D Model
        # tab after AI, and here in the Takeoff menu
        self._act(t, "3D Model Quantities (IFC)…", None,
                  lambda: self.model_quantities(), False)
        t.addSeparator()
        self._act(t, "Assembly Library…", "Ctrl+Shift+L",
                  self.assemblies.open_library)
        a = self._act(t, "Take Off Into Assembly…", None,
                      lambda: self.take_into_assembly())
        a.setStatusTip("Pick a CSI division and an assembly; the matching "
                       "tool starts and what you trace is priced by it")
        t.addAction(self.asm_dock.toggleViewAction())
        self._act(t, "Labor Rates && Crews…", None, self.labor_settings)
        self._act(t, "Cost Books…", None, self.cost_books)
        self._act(t, "Add From Cost Book…", None,
                  lambda: self.add_from_cost_book())
        self._act(t, "Quick $/SF Estimate…", None,
                  lambda: self.quick_sf_estimate(), False)
        self._act(t, "Model Estimate…", None,
                  lambda: self.model_estimate(), False)
        self._act(t, "Concrete Calculator…", None,
                  lambda: self.calculators(0), False)
        self._act(t, "Brick and Block Calculator…", None,
                  lambda: self.calculators(1), False)
        self._act(t, "Roofing Calculator…", None,
                  lambda: self.calculators(2), False)
        self._act(t, "Rebar Calculator…", None,
                  lambda: self.calculators(3), False)
        self._act(t, "Beam and Header Calculator…", None,
                  lambda: self.calculators(4), False)
        self._act(t, "Column and Post Calculator…", None,
                  lambda: self.calculators(5), False)
        self._act(t, "Footing Size Calculator…", None,
                  lambda: self.calculators(6), False)
        self._act(t, "Metal Stud Framing Calculator…", None,
                  lambda: self.calculators(7), False)
        self._act(t, "Structural Steel Calculator…", None,
                  lambda: self.calculators(8), False)
        self._act(t, "Earthwork Calculator…", None,
                  lambda: self.calculators(9), False)
        self._act(t, "Aggregate and Asphalt Calculator…", None,
                  lambda: self.calculators(10), False)
        self._act(t, "Drywall Calculator…", None,
                  lambda: self.calculators(11), False)
        self._act(t, "Paint Calculator…", None,
                  lambda: self.calculators(12), False)
        self._act(t, "Date and Time Calculators…", None,
                  lambda: self.date_calculators(), False)
        self._act(t, "Bid Tabs…", None, self.bid_tabs, False)
        self._act(t, "Bid Leveling…", None, self.bid_leveling, False)
        a = self._act(t, "Scope Sheets…", None, lambda: self.scope_sheets(),
                      False)
        a.setStatusTip("Compare sub bids for one trade at a time on your "
                       "Scope Sheet: budget, bidders, checklist, scope "
                       "lines, math check, award")
        a.setWhatsThis(a.statusTip())
        self._act(t, "Price Database…", None, self.price_database, False)
        self._act(t, "Location Factors…", None, self.location_factors, False)
        self._act(t, "Import Your Own Price List…", None,
                  self.import_price_list, False)
        self._act(t, "Export Assembly Estimate (Excel)…", None,
                  lambda: self.assemblies._export_dialog())
        self._act(t, "Bid Build-up…", None, lambda: self.bid_buildup(),
                  False)
        self._act(t, "Pre-bid Checklist…", None,
                  lambda: self.prebid_checklist())
        self._act(t, "Leveling Board…", None, lambda: self.leveling_board())
        self._act(t, "Bid Form Autopilot…", None, lambda: self.bid_form_autopilot())
        self._act(t, "Bid Form Workbook…", None, lambda: self.bid_form_workbook())
        self._act(t, "Builder's Risk Quote Request…", None,
                  lambda: self.builders_risk())
        self._act(t, "Placeholders && Allowances…", None,
                  lambda: self.placeholders())
        self._act(t, "Escalation to Buy Date…", None,
                  lambda: self.escalation())
        self._act(t, "Bid Gate Settings…", None, lambda: self.bid_gate_settings(),
                  False)
        from . import coverage_ui
        self._act(t, "Carry Takeoff Forward to a Revised Set…", None,
                  lambda: self.carry_forward())
        self._act(t, "Typical Sheet (Count This Sheet N Times)…", None,
                  lambda: self.page_multiplier())
        self._act(t, "Wood Sheathing Helper…", None,
                  lambda: self.sheathing_helper())
        self._act(t, "Buy Quantities (Sheets, Boxes, Rolls)…", None,
                  lambda: self.buy_quantities())
        self._act(t, "Coverage Map and Second Check…", None,
                  lambda: coverage_ui.show(self))
        self._act(t, "Revision Changes (Old → New)…", None,
                  lambda: self._boost("revdelta"))
        self._act(t, "Job Cost Feedback (Bid vs Actual)…", None,
                  lambda: self.job_cost_feedback(), False)
        self._act(t, "Estimating Dashboard…", None,
                  lambda: self.estimating_dashboard(), False)
        self._act(t, "Bid Board…", None, lambda: self.bid_board(), False)
        a = self._act(t, "Show Unpriced Markups", None,
                      lambda: self.toggle_unpriced())
        a.setCheckable(True)
        self.unpriced_act = a
        self._act(t, "Create Proposal…", "Ctrl+Shift+B",
                  lambda: self.create_proposal())
        self._act(t, "Export Bid Package…", None,
                  lambda: self.export_bid_package())
        t.addSeparator()
        t.addAction(self.est_dock.toggleViewAction())
        self._act(t, "Price These…", None, lambda: self.price_these())
        self._act(t, "Award: Budget && Commitments in the Job…", None,
                  lambda: self.award_estimate())
        self._act(t, "Export Estimate (CSV)…", None,
                  lambda: self.estimate._export_dialog())
        self._act(t, "Export My Estimate…", None,
                  lambda: self.export_my_estimate())
        self._act(t, "Export Quantities (CSV)…", None, self.export_quantities)
        self._act(t, "Export to Sage 300 Job Cost (CSV)…", None,
                  self.export_sage)
        self._act(t, "Link Quantities to Excel…", None, self.link_excel)
        from .estimating import ui as estimating_tools      # r36 features
        estimating_tools.add_menu(self, t)

        p = mb.addMenu("&Pages")
        self._act(p, "Rotate Right", "Ctrl+Shift+=",
                  lambda: self._page_action("rotate_right", self._sel_pages()))
        self._act(p, "Rotate Left", "Ctrl+Shift+-",
                  lambda: self._page_action("rotate_left", self._sel_pages()))
        self._act(p, "Rotate All Pages Right", None,
                  lambda: self._page_action("rotate_right",
                                            list(range(self._doc().page_count))))
        p.addSeparator()
        self._act(p, "Insert Blank Page", None,
                  lambda: self._page_action("insert_blank", self._sel_pages()))
        self._act(p, "Insert Pages From PDF…", None,
                  lambda: self._page_action("insert_pdf", self._sel_pages()))
        self._act(p, "Duplicate Page", None, self.duplicate_page)
        self._act(p, "Replace Pages…", None, self.replace_pages)
        self._act(p, "Organize Pages…", "Ctrl+Shift+G", self.organize_pages)
        self._act(p, "Split Document…", None, self.split_doc)
        self._act(p, "Booklet / N-up…", None, self.booklet_nup)
        self._act(p, "Extract Pages…", None,
                  lambda: self._page_action("extract", self._sel_pages(True)))
        self._act(p, "Delete Pages…", None,
                  lambda: self._page_action("delete", self._sel_pages(True)))
        p.addSeparator()
        self._act(p, "Header && Footer…", None, self.header_footer)
        self._act(p, "Auto Bookmark Sheets…", None,
                  lambda: self.sheet_setup(scales=False, bookmarks=True))
        self._act(p, "Link Sheet References", None, self.batch_link)
        self._act(p, "Remove Sheet Links", None,
                  lambda: self.batch_link(remove=True))
        self._act(p, "Page Numbers…", None,
                  lambda: self.header_footer(page_numbers=True))
        self._act(p, "Crop Pages", None, lambda: self.set_tool("crop"))
        self._act(p, "Bates Numbering…", None, self.bates)
        self._act(p, "Watermark…", None, self.watermark)

        dm = mb.addMenu("&Document")
        self._act(dm, "Make Searchable (OCR)…", None, self.make_searchable)
        self._act(dm, "Check Scan Quality…", None, self.scan_quality)
        self._act(dm, "Preflight / PDF/X…", None,
                  lambda: self.preflight())
        self._act(dm, "Request Signatures…", None,
                  lambda: self.request_signatures())
        self._act(dm, "Signature Requests…", None,
                  lambda: self.signature_requests(), False)
        self._act(dm, "Accessibility Check…", None,
                  lambda: self.accessibility_check())
        self._act(dm, "Spec Book Sections…", None,
                  lambda: self.spec_sections())
        self._act(dm, "Search && Redact…", None, self.search_redact)
        dm.addSeparator()
        self._act(dm, "Prepare Form (detect fields)", None, self.prepare_form)
        self._act(dm, "Clear Form", None, self.clear_form)
        self._act(dm, "Fill Form From Job", None, lambda: self.fill_form())
        dm.addSeparator()
        self._act(dm, "Flatten Markups && Fields…", None, self.flatten)
        self._act(dm, "Auto Bookmark (Link Details)…", None,
                  lambda: self._boost("autobookmark"))

        tl = mb.addMenu("&Tools")
        self._act(tl, "Action Wizard (Batch Process)…", None, self.batch,
                  False)
        self._act(tl, "Macros…", None, self.open_macros)
        self._act(tl, "Package Tracker…", None, self.package_tracker, False)
        self._act(tl, "Back Up My QuantiSheet Data…", None,
                  lambda: self.backup_data(), False)
        self._act(tl, "Restore QuantiSheet Data From a Backup…", None,
                  lambda: self.restore_data(), False)
        self._act(tl, "Time Log…", None, lambda: self.time_log(), False)
        tl.addSeparator()
        self._act(tl, "Start Relay (host on this computer)…", None,
                  self.start_relay, False)
        self._act(tl, "Live Collaboration…", None, self.open_collab)

        # Nov 20 (Jon): its own menu, after Tools
        pam = mb.addMenu("Project &Analysis")
        self._act(pam, "Project Analysis…", None,
                  lambda: self.project_analysis())
        self._act(pam, "Find Bid Terms…", None, lambda: self.bid_terms())
        self._act(pam, "Manufacturers in Specs…", None,
                  lambda: self.spec_manufacturers())
        self._act(pam, "Bid Submittal Checklist…", None,
                  lambda: self.bid_submittal())

        r = mb.addMenu("&Review")
        self._act(r, "Revision Log…", None, lambda: self.revision_log())
        self._act(r, "Tags vs Schedule Check…", None,
                  lambda: self.tag_check())
        self._act(r, "Measurement Audit…", None,
                  lambda: self.measurement_audit())
        r.addSeparator()
        self._act(r, "Auto-Markup by Rules", None, self.auto_markup)
        self._act(r, "Edit Auto-Markup Rules…", None, self.edit_rules)
        r.addSeparator()
        self._act(r, "AI Takeoff (Whole Set)…", "Ctrl+Shift+A",
                  lambda: self.ai_takeoff())
        z = r.addMenu("AI Takeoff Zones")
        self._act(z, "Draw a Zone: Only Here", None,
                  lambda: self._view and self._view.set_tool("zone_include"))
        self._act(z, "Draw a Zone: Leave Out", None,
                  lambda: self._view and self._view.set_tool("zone_exclude"))
        self._act(z, "Clear Zones on This Page", None,
                  lambda: self._view and self._view.clear_zones())
        self._act(r, "Build Schedule From Plans…", None,
                  lambda: self.ai_schedule(), False)
        self._act(r, "Voice Commands", "Ctrl+Shift+V",
                  lambda: self.voice_commands())
        self._act(r, "AI: Summarize…", None, self.ai_summary)
        # Nov 23 (Jon): project assistants, also on the AI tab
        self._act(r, "Ask the Project…", None, lambda: self.ask_project(),
                  False)
        self._act(r, "Draft Daily Log From Notes…", None,
                  lambda: self.daily_draft(), False)
        self._act(r, "Check Submittal Against Spec…", None,
                  lambda: self.submittal_check(), False)
        self._act(r, "AI: Redline…", None, self.ai_redline)
        self._act(r, "AI: Spec-Check…", None, self.ai_spec_check)
        self._act(r, "Spec Book Risk Scanner…", None,
                  lambda: self.spec_risk(), False)
        self._act(r, "AI: Translate Markups…", None, self.translate_markups)
        self._act(r, "AI: Find RFIs && Questions…", None, self.ai_find_rfis)
        self._act(r, "Local AI Models…", None, lambda: self.ai_models(),
                  False)
        r.addSeparator()
        r.addAction(self.rfi_dock.toggleViewAction())
        self._act(r, "New RFI…", None, lambda: self.new_rfi("RFI"))
        self._act(r, "New Submittal…", None,
                  lambda: self.new_rfi("Submittal"))
        self._act(r, "Submittal Review Stamp", None,
                  lambda: self.set_tool("review_stamp"))

        pj = mb.addMenu("&Project")
        self._act(pj, "Project Center…", "Ctrl+Shift+P",
                  lambda: self.project_center(), False)
        self._act(pj, "Company Directory…", None,
                  lambda: self.company_directory(), False)
        self._act(pj, "Bid Invites Send As…", None,
                  lambda: self.bid_invite_sender(), False)
        self._act(pj, "Scheduler (Gantt)…", "Ctrl+Shift+J",
                  lambda: self.scheduler(), False)
        self._act(pj, "New Schedule…", None,
                  lambda: self.scheduler(new=True), False)
        self._act(pj, "Weekly Owner Report…", None,
                  lambda: self.weekly_owner_report(), False)
        self._act(pj, "Date and Time Calculators…", None,
                  lambda: self.date_calculators(), False)
        pj.addSeparator()
        self._act(pj, "New Set From Files…", None,
                  lambda: self._sets_do("new_set"), False)
        self._act(pj, "Open Set…", None, lambda: self._sets_do("open_set"),
                  False)
        self._act(pj, "Batch Slip Sheet…", None,
                  lambda: self.batch_slip_sheet(), False)
        self._act(pj, "Watch Plan Folder…", None,
                  lambda: self.watch_plan_folder())
        self._act(pj, "Check Plan Folder Now", None,
                  lambda: self.check_plan_folder(quiet=False))
        self._act(pj, "Search Takeoff Across Jobs…", None,
                  lambda: self.measurement_audit(1), False)
        pj.addSeparator()
        self._act(pj, "Drawing Register…", None,
                  lambda: self.doc_control(0))
        self._act(pj, "Transmittals…", None, lambda: self.doc_control(1))
        self._act(pj, "New Transmittal…", None,
                  lambda: self.doc_control(1).new_transmittal())
        self._act(pj, "Addenda…", None, lambda: self.doc_control(2))
        pj.addSeparator()
        self._act(pj, "Punch List…", "Ctrl+Shift+U", lambda: self.quality(0))
        self._act(pj, "New Punch Item…", None,
                  lambda: self.quality(0).new_punch())
        self._act(pj, "Three-Phase Inspections…", None,
                  lambda: self.quality(1))
        pj.addSeparator()
        self._act(pj, "Code Check…", None, self.code_check)
        self._act(pj, "Project Risk Flags…", None,
                  lambda: self.risk_flags(), False)
        pj.addSeparator()
        self._act(pj, "Submittal Log…", None, self.submittal_log, False)

        # Module: add-on reference tools (ADA first; ClaimIt to come).
        # No drawing needed: the Standards and the counts checker work alone
        md = mb.addMenu("&Module")
        self._module_menu = md
        self._act(md, "ADA Standards PDF…", None, self.ada_pdf, False)
        self._act(md, "ADA Standards (2010)…", None, lambda: self.ada(0),
                  False)
        self._act(md, "ADA Checker…", None, lambda: self.ada(1), False)
        md.addSeparator()
        self._act(md, "Climate Zone by County…", None,
                  lambda: self.energy_code(0), False)
        self._act(md, "Code Library…", None, lambda: self.energy_code(1),
                  False)
        self._act(md, "Read the Energy Code Online…", None,
                  lambda: self.energy_code(2), False)
        from . import claims_hook        # optional separate program
        if claims_hook.launcher() is not None:
            md.addSeparator()
            self._act(md, "ClaimIT (Insurance Claim Estimate)…", None,
                      self.open_claims_module, False)   # no PDF needed
        from . import backoffice_hook    # optional Back Office program
        backoffice_hook.add_menu_item(self, md)
        from . import master_hook        # Master Schedule (sub updates)
        master_hook.add_menu_item(self, md)

        bl = mb.addMenu("&Billing")
        self._act(bl, "Contract && Billing…", "Ctrl+Shift+M",
                  lambda: self.billing())
        self._act(bl, "Schedule of Values…", None,
                  lambda: self.billing("Schedule of Values"))
        self._act(bl, "Change Order From Selected Markup…", None,
                  self.change_from_markup)
        self._act(bl, "Change Order From Revision…", None,
                  lambda: self.change_from_revision())
        self._act(bl, "Change Orders…", None,
                  lambda: self.billing("Change Orders"))
        self._act(bl, "Pay Applications…", None,
                  lambda: self.billing("Pay Applications"))
        self._act(bl, "Lien Waivers…", None,
                  lambda: self.billing("Lien Waivers"))

        cv = mb.addMenu("&Civil")
        self._act(cv, "Civil Takeoff (Trades)…", None,
                  lambda: self.trade_takeoff())
        self._act(cv, "Work Notes Takeoff…", None,
                  lambda: self.work_notes_takeoff())
        self._act(cv, "Haul Calculator…", None, lambda: self.civil(6),
                  False)
        self._act(cv, "Export to CivilBid (Excel)…", None,
                  lambda: self.export_heavybid())
        from . import costlayer_ui
        costlayer_ui.add_menu(self, cv)
        from . import aerial_ui
        aerial_ui.add_menu(self, cv)
        from . import production_ui
        production_ui.add_menu(self, cv)
        cv.addSeparator()
        self._act(cv, "Crew Estimate (Activities)…", None,
                  lambda: self.civil(0))
        self._act(cv, "Estimate From Takeoff (All Groups)", None,
                  lambda: self.civil(0).add_all_groups())
        self._act(cv, "Add From Activity Library…", None,
                  lambda: self.civil(0).add_from_library())
        self._act(cv, "Start From Master Estimate…", None,
                  lambda: self.civil(0).start_from_master())
        self._act(cv, "Crews…", None, lambda: self.civil(1), False)
        self._act(cv, "Equipment Rates…", None, lambda: self.civil(2), False)
        self._act(cv, "Labor Burden && Wages…", None, lambda: self.civil(3),
                  False)
        self._act(cv, "Import Prevailing Wages (Davis-Bacon)…", None,
                  lambda: self.civil(3).import_wages())
        cv.addSeparator()
        self._act(cv, "Material && Sub Quotes…", None, lambda: self.civil(9))
        self._act(cv, "Crew Schedule…", None, lambda: self.civil(10))
        self._act(cv, "Resources (Hours by Class && Equipment)…", None,
                  lambda: self.civil(11))
        self._act(cv, "Export Cash Flow…", None,
                  lambda: self.civil(10).export_cashflow())
        cv.addSeparator()
        self._act(cv, "Owner Bid Schedule…", None, lambda: self.civil(4))
        self._act(cv, "Import Owner Bid Schedule…", None,
                  lambda: self.civil(4).import_pay())
        self._act(cv, "Export Priced Bid Schedule…", None,
                  lambda: self.civil(4).export_pay())
        self._act(cv, "Indirects…", None, lambda: self.civil(5))
        self._act(cv, "Bid Versions…", None, lambda: self.civil(7))
        self._act(cv, "Save Bid Version…", None,
                  lambda: self.civil(7).save_version())
        cv.addSeparator()
        self._act(cv, "Time Cards…", None, lambda: self.project_center(),
                  False)
        self._act(cv, "Production History…", None, lambda: self.civil(8),
                  False)
        self._act(cv, "Cost to Complete (Forecast)…", None,
                  lambda: self.civil(12))
        self._act(cv, "Civil Job Cost (Bid vs Actual)…", None,
                  lambda: self.job_cost_feedback(), False)

        h = mb.addMenu("&Help")
        self._help_menu = h
        self._act(h, "Help Center && Tutorials…", "F1", self.help_center,
                  False)
        self._act(h, "Features && How-To Guide (PDF)", None,
                  lambda: self.open_guide(), False)
        self._act(h, "Video Tutorials", None,
                  lambda: self.video_tutorials(), False)
        self._act(h, "Welcome Tour", None, self.welcome_tour, False)
        self._act(h, "Open Practice Drawings", None, self.open_practice,
                  False)
        self._act(h, "Practice Job (10 Minutes)…", None,
                  lambda: self.practice_job(), False)
        self._act(h, "Keyboard Shortcuts", None, self.shortcuts, False)
        self._act(h, "Customize Shortcuts…", None,
                  lambda: self.customize_shortcuts(), False)
        self._act(h, "Report an Issue…", None, self.report_issue, False)
        self._act(h, "Support Bundle for IT…", None, self.support_bundle,
                  False)
        self._act(h, "Recent Problems (Log)…", None,
                  lambda: self.recent_problems(), False)
        try:           # team copy only, off until the tester ticks it
            from . import errorreports
            errorreports.install(self, h)
        except Exception:                                 # noqa: BLE001
            logging.getLogger(__name__).debug("error reports not wired",
                                              exc_info=True)
        from . import betalicense as _bl
        store = _bl.is_store()      # the Store copy: no printer, no key
        if not store:
            self._act(h, "Add the QuantiSheet Printer…", None,
                      self.add_printer, False)
        h.addSeparator()
        self._act(h, "Terms of Service", None,
                  lambda: self.about("Terms of Service"), False)
        self._act(h, "Privacy", None, lambda: self.about("Privacy"), False)
        self._act(h, "Third-Party Licenses", None,
                  lambda: self.about("Third-Party Licenses"), False)
        if not store:
            self._act(h, "Enter License Key…", None, self.enter_license,
                      False)
        h.addSeparator()
        self._act(h, "About QuantiSheet", None, self.about, False)
        # team copy only: Help > Check for Updates (never the Store copy)
        try:
            from . import updatecheck_ui
            updatecheck_ui.install(self, h)
        except Exception:                                 # noqa: BLE001
            logging.getLogger(__name__).debug("update check not wired",
                                              exc_info=True)
        exit_a = next((a for a in self._file_menu.actions()
                       if a.text().replace("&", "") == "Exit"), None)
        if exit_a is not None:
            self._file_menu.insertMenu(exit_a, h)
            self._file_menu.insertSeparator(exit_a)
        else:
            self._file_menu.addMenu(h)

    def _ribbon_only_actions(self):
        """Commands that are on the ribbon only, with no menu entry (Jon
        places each one): Send with QuantiLink on the Home tab (Nov 23).
        None of them when IT turned the feature off."""
        if getattr(self, "_ribbon_only", None) is None:
            from . import policy
            self._ribbon_only = []
            if policy.allowed("quantilink"):
                a = QAction("Send with QuantiLink…", self)
                a.setToolTip("Send with QuantiLink: a job's RFIs, "
                             "submittals, daily logs or meeting minutes "
                             "to the office's QuantiLink server, with "
                             "share links back for an email")
                a.triggered.connect(lambda: self.send_quantilink())
                self._ribbon_only.append(a)
        return self._ribbon_only

    def _build_toolbar(self):
        """The ribbon (replaces the old toolbars), Ctrl+K command search
        and the theme."""
        from . import theme
        from .ribbon import Ribbon, clean
        self._index_actions()
        # menus stay as the source of every command; their shortcuts need
        # the actions on the window once the menu bar is hidden
        for a in self._cmd.values():
            if a not in self.actions():
                self.addAction(a)
        self.menuBar().hide()
        self.ribbon = Ribbon(self)
        self.ribbon.app_button.setMenu(self._file_menu)
        self.ribbon.help_button.setMenu(self._help_menu)
        self.ribbon.search_requested.connect(self.command_search)
        self.ribbon.theme_picked.connect(self.set_theme)
        missing = []
        from . import quickaccess
        for tab, title, items in self.RIBBON:
            tab, title = quickaccess.fold(tab, title)  # fewer tabs (Nov 4)
            g = self.ribbon.page(tab).group(title)
            for it in items:
                if it == "@scale":
                    self._build_scale_box(g)
                    continue
                if isinstance(it, list):
                    acts = [self.command(t) for t in it]
                    missing += [t for t, a in zip(it, acts) if a is None]
                    acts = [a for a in acts if a is not None]
                    for a in acts:
                        if a.icon().isNull():
                            tool = a.data() if isinstance(a.data(), str) \
                                else None
                            if tool and icons.has(tool):
                                a.setIcon(icons.icon(tool))
                    if acts:
                        g.small(acts)
                    continue
                text, label, icon = it if isinstance(it, tuple) else \
                    (it, None, None)
                a = self.command(text)
                if a is None:
                    missing.append(text)
                    continue
                if icon:
                    a.setIcon(icons.icon(icon))
                    a.setProperty("qs_icon", icon)
                if label:
                    a.setIconText(label)
                g.large(a, label)
        self._place_roof_tile()
        claims = self.command("ClaimIT (Insurance Claim Estimate)")
        if claims is not None:          # only when ClaimIT is installed
            claims.setIcon(icons.icon("dollar"))
            claims.setProperty("qs_icon", "dollar")
            claims.setIconText("ClaimIT")
            t_, g_ = quickaccess.fold("Module", "ClaimIT")
            self.ribbon.page(t_).group(g_).large(claims, "ClaimIT")
        qlink = self.command("Send with QuantiLink")
        if qlink is not None:           # not when IT turned it off
            qlink.setIcon(icons.icon("link"))
            qlink.setProperty("qs_icon", "link")
            qlink.setIconText("QuantiLink")
            t_, g_ = quickaccess.fold("Home", "File")
            self.ribbon.page(t_).group(g_).large(qlink, "QuantiLink")
        ms = self.command("Master Schedule (Sub Updates)")
        if ms is not None:              # the Master Schedule module is on
            ms.setIcon(icons.icon("calendar"))
            ms.setProperty("qs_icon", "calendar")
            ms.setIconText("Master Schedule")
            t_, g_ = quickaccess.fold("Module", "Schedule")
            self.ribbon.page(t_).group(g_).large(ms, "Master Schedule")
        up = self.command("Check for Updates Now")
        if up is not None:          # team / Store copy only (review Part F)
            up.setProperty("keywords", "update updater upgrade new version "
                           "download install latest")
            up.setProperty("qs_icon", "sync")
            if up.icon().isNull():
                up.setIcon(icons.icon("sync"))
            self.ribbon.page("Help").group("About").large(up, "Updates")
        if missing:
            log.warning("ribbon: no command named %s", ", ".join(missing))
        self._ribbon_missing = missing
        holder = QToolBar("Ribbon")
        holder.setObjectName("ribbon_bar")
        holder.setMovable(False)
        holder.setFloatable(False)
        holder.toggleViewAction().setVisible(False)
        holder.setContextMenuPolicy(Qt.PreventContextMenu)
        holder.setStyleSheet("QToolBar { padding: 0; margin: 0; }")
        holder.addWidget(self.ribbon)
        self.addToolBar(Qt.TopToolBarArea, holder)
        self._ribbon_bar = holder
        # always open on the Home tab (Jon, 0.13.11), not the last one used
        self._fill_ai_tab()
        self._fill_approved_tiles()
        if "Home" in self.ribbon.pages:
            self.ribbon.show_page("Home")
        self.ribbon.set_collapsed(bool(settings.get("ribbon_collapsed")))
        self.ribbon.page_changed.connect(
            lambda _n: self._sync_tool_chest(force=True, tab_change=True))
        self._chest_mode = None
        self._sync_tool_chest()
        theme.hub.changed.connect(self._retheme)
        QTimer.singleShot(0, self._tidy_dock_tabs)
        # load the modules the first edit needs while the user looks around
        QTimer.singleShot(1500, self._preload)

    def _fill_approved_tiles(self):
        """Menu windows approved onto the ribbon (stage 1 placement)."""
        from PySide6.QtWidgets import QMenu, QToolButton
        from .ribbon import clean
        missing = []
        missing += self._ribbon_put("Home", "File", (
            ("Generate Set", "Generate Set", "layers"),
            ("Print Preview", "Print Preview", "print"),
            ("Save As", "Save As", "save"),
            ("Recover Unsaved Files", "Recover", "history"),
        ))
        missing += self._ribbon_put("Document", "Forms", (
            ("New From Form Library", "Form Library", "form"),
        ))
        missing += self._ribbon_put("Project", "Sets", (
            ("Open Bid Download (.zip) as a Job", "Bid Download", "package"),
        ))
        missing += self._ribbon_put("Document", "Protect", (
            ("Check / Repair PDF", "Check / Repair", "shield"),
        ))
        missing += self._ribbon_put("Document", "Content", (
            ("Attachments", "Attachments", "attach"),
            ("Check Scan Quality", "Scan Quality", "audit"),
            ("Auto Bookmark (Link Details)", "Link Details", "bookmark"),
        ))
        missing += self._ribbon_put("Takeoff", "Plan Set", (
            ("Takeoff Standard", "Standard", "checklist"),
            ("Coverage Map and Second Check", "Coverage", "overlay"),
        ))
        missing += self._ribbon_put("Estimate", "Pricing", (
            ("Model Estimate", "Model", "estimate"),
            ("Location Factors", "Location", "flag"),
            ("Import Your Own Price List", "Price List", "import"),
            ("Planning Cost Model", "Cost Model", "budget"),
            ("Estimate Templates", "Templates", "book"),
            ("Supplier Price List Import", "Supplier Prices", "import"),
            ("Match Rates & Price a Workbook", "Match Rates", "dollar"),
            ("Crew Hours by Pay Item", "Crew Hours", "crew"),
        ))
        missing += self._ribbon_put("Estimate", "Assemblies", (
            ("Assembly Rules & Wall-Type Assemblies", "Wall Assemblies",
             "walls"),
        ))
        missing += self._ribbon_put("Estimate", "Bidding", (
            ("Bid Gate Settings", "Bid Gate", "lock"),
            ("Award: Budget & Commitments in the Job", "Award", "gavel"),
            ("Estimate Error Check", "Error Check", "checklist"),
            ("Bid-Day Quote Comparison", "Bid Day", "compare"),
            ("Estimate vs Actual", "Vs Actual", "trend"),
            ("Job Cost Feedback (Bid vs Actual)", "Job Cost", "budget"),
        ))
        missing += self._ribbon_put("Estimate", "Output", (
            ("Material Order List", "Materials", "list"),
            ("Estimating Dashboard", "Dashboard", "panels"),
            ("Bid Board", "Bid Board", "list"),
            ("Export to Sage 300 Job Cost (CSV)", "Sage 300", "export"),
        ))
        missing += self._ribbon_put("Estimate", "Civil Estimate", (
            ("Assembly Library (CivilBid codes)", "CivilBid Library",
             "assembly"),
            ("Bind Takeoff Group to Assembly", "Bind Group", "link"),
            ("Insert Assembly Line", "Insert Line", "add_line"),
            ("Bid Summary (Coded Assemblies)", "Coded Summary", "bidtabs"),
            ("Revision Change Report", "Code Changes", "compare"),
        ))
        missing += self._ribbon_put("Estimate", "Civil Field", (
            ("Production by Depth", "By Depth", "measure_volume"),
        ))
        missing += self._ribbon_put("Pages", "Pages", (
            ("Booklet / N-up", "Booklet", "panels"),
            ("Rotate All Pages Right", "Rotate All", "rotate"),
            ("Remove Sheet Links", "Unlink Sheets", "link"),
        ))
        missing += self._ribbon_put("Help", "Learn", (
            ("Practice Job (10 Minutes)", "Practice Job", "home"),
        ))
        missing += self._ribbon_put("Tools", "Settings", (
            ("Customize Shortcuts", "Shortcuts", "keyboard"),
            ("Back Up My QuantiSheet Data", "Back Up", "save"),
            ("Restore QuantiSheet Data From a Backup", "Restore", "history"),
            ("Time Log", "Time Log", "calendar"),
        ))
        missing += self._ribbon_put("Help", "About", (
            ("Support Bundle for IT", "Support Bundle", "package"),
            ("Recent Problems (Log)", "Problems", "history"),
            ("Add the QuantiSheet Printer", "Printer", "print"),
            ("Enter License Key", "License", "lock"),
        ))
        missing += self._ribbon_put("Project", "Manage", (
            ("Bid Invites Send As", "Bid Invites", "mail"),
        ))
        missing += self._ribbon_put("Project", "Schedule", (
            ("New Schedule", "New Schedule", "gantt"),
        ))
        missing += self._ribbon_put("Billing", "Changes", (
            ("Change Order From Revision", "From Revision", "change_order"),
        ))
        # one Dropbox tile, one Export tile (the menus already exist)
        g = self.ribbon.page("Home").group("File")
        box = getattr(self, "_dropbox_actions", None) or {}
        if box:
            m = QMenu(g)
            for a in box.values():
                m.addAction(a)
            first = next(iter(box.values()))
            first.setProperty("qs_icon", "cloud")
            if first.icon().isNull():
                first.setIcon(icons.icon("cloud"))
            b = g.large(first, "Dropbox", menu=m)
            b.setPopupMode(QToolButton.InstantPopup)
            shown = any(a.isVisible() for a in box.values())
            b.setVisible(shown)
        exp_menu = None
        for a in self._file_menu.actions():
            if a.menu() is not None and clean(a.text()).lower() == "export to":
                exp_menu = a.menu()
                break
        if exp_menu is not None:
            first = next((a for a in exp_menu.actions()
                          if not a.isSeparator() and a.text()), None)
            if first is not None:
                first.setProperty("qs_icon", "export")
                if first.icon().isNull():
                    first.setIcon(icons.icon("export"))
                b = g.large(first, "Export", menu=exp_menu)
                b.setPopupMode(QToolButton.InstantPopup)
        missing += self._fill_pdf_tab(exp_menu)
        self._approved_missing = missing
        if missing:
            log.warning("ribbon placement: no command named %s",
                        ", ".join(missing))
        return missing
