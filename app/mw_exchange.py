"""Exports to and imports from other programs, and printing (split out of
main_window.py, Nov 25).
"""
import fitz
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog,
    QMessageBox)
from . import annotate
from .dmoney import c2 as _c2
from .main_window import confirm_unprotected_copy, log, user_writable


class ExchangeMixin:
    """MainWindow's exchange methods (see main_window.py)."""

    def buy_quantities(self, show=True):
        """Takeoff > Buy Quantities: per item, the size of one and the
        waste; the totals then show what to order."""
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox,
                                       QTableWidget, QTableWidgetItem,
                                       QVBoxLayout)
        from . import buyqty
        v = self._view
        if v is None:
            return None
        totals = {}
        for it in annotate.totals_items(v.doc):
            if it["group"] and it["type"] != "cutout":
                k = (it["group"], it["unit"])
                totals[k] = totals.get(k, 0) + it["value"]
        rs = buyqty.rules(v.doc)
        dlg = QDialog(self)
        dlg.setWindowTitle("Buy Quantities")
        dlg.resize(720, 420)
        lay = QVBoxLayout(dlg)
        t = QTableWidget(len(totals), 6)
        t.setHorizontalHeaderLabels(["Item", "Total", "Size of one",
                                     "Buy unit", "Waste %", "Buy"])
        keys = sorted(totals)
        for r, (g, u) in enumerate(keys):
            rule = rs.get(g, {})
            for c, val in enumerate((g, f"{_c2(totals[(g, u)]):,.2f} {u}",
                                     f"{rule.get('per', '') or ''}",
                                     rule.get("unit", ""),
                                     f"{rule.get('waste', '') or ''}", "")):
                it = QTableWidgetItem(str(val))
                if c in (0, 1, 5):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(r, c, it)

        def recalc():
            for r, (g, u) in enumerate(keys):
                try:
                    per = float(t.item(r, 2).text() or 0)
                    waste = float(t.item(r, 4).text() or 0)
                except ValueError:
                    t.item(r, 5).setText("?")
                    continue
                n = buyqty.buy(totals[(g, u)], {"per": per, "waste": waste}) \
                    if per > 0 else None
                t.blockSignals(True)
                t.item(r, 5).setText("" if n is None else
                                     f"{n:,} {t.item(r, 3).text() or 'each'}")
                t.blockSignals(False)
        t.itemChanged.connect(lambda _i: recalc())
        recalc()
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        lay.addWidget(bb)

        def save():
            for r, (g, u) in enumerate(keys):
                try:
                    per = float(t.item(r, 2).text() or 0)
                    waste = float(t.item(r, 4).text() or 0)
                    buyqty.set_rule(v.doc, g, per, t.item(r, 3).text(),
                                    waste)
                except ValueError as e:
                    QMessageBox.warning(dlg, "Buy Quantities", f"{g}: {e}")
                    return
            v.mark_dirty()
            self._refresh_panels()
            dlg.accept()
        bb.accepted.connect(save)
        bb.rejected.connect(dlg.reject)
        dlg.table = t
        dlg.save = save
        if show:
            dlg.show()
        return dlg

    def import_price_list(self):
        """Estimate > Import Your Own Price List (local-only cost book)."""
        from .priceimport_ui import ImportPriceListDialog
        dlg = ImportPriceListDialog(self)
        self._price_import_dlg = dlg
        dlg.exec()
        return dlg

    def export_my_estimate(self, show=True):
        """Totals by CSI division and cost type; Save to PDF, Excel or
        CSV."""
        return self.estimate.export_my_estimate(show)

    def import_markups(self, path=None, layer=None):
        v = self._view
        if not v:
            return 0
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import Markups From", "",
                "PDF or XFDF (*.pdf *.xfdf);;PDF (*.pdf);;XFDF (*.xfdf)")
            if not path:
                return 0
        if path.lower().endswith((".xfdf", ".xml")):
            from . import xfdf
            try:
                marks = xfdf.import_marks(v.doc, path, layer)
            except Exception as ex:
                QMessageBox.warning(self, "Import Markups",
                                    f"Couldn't read that XFDF file:\n{ex}")
                return 0
        else:
            try:
                src = fitz.open(path)
            except Exception as ex:
                QMessageBox.warning(self, "Import Markups", str(ex))
                return 0
            try:
                marks = annotate.import_ops(v.doc, src, layer)
            finally:
                src.close()
        if not marks:
            QMessageBox.information(self, "Import Markups",
                                    "That PDF has no markups to import.")
            return 0
        n = v.apply_marks(marks)
        self._flash(f"Imported {n} markup(s) from {os.path.basename(path)}")
        return n

    def export_xfdf(self, path=None):
        """Markups to XFDF, for other PDF programs."""
        from . import xfdf
        v = self._view
        if not v:
            return 0
        if path is None:
            base = os.path.splitext(self._path or "markups")[0]
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Markups", base + ".xfdf", "XFDF (*.xfdf)")
            if not path:
                return 0
        n = xfdf.export(v.doc, path)
        self._flash(f"Exported {n} markup(s) to {os.path.basename(path)}")
        return n

    def link_excel(self, path=None):
        from . import qlink
        v, tab = self._view, self._tab
        if not v:
            return None
        doc_path = tab.path if tab else None
        if not doc_path:
            QMessageBox.information(self, "Quantity Link",
                                    "Save the PDF first, then link it.")
            return None
        cur = qlink.link_for(doc_path)
        if path is None:
            if cur:
                # this job's workbook is remembered (Nov 4): open it,
                # update it, or unlink
                box = QMessageBox(self)
                box.setWindowTitle("Quantity Link")
                box.setText(f"This job's quantities go to:\n{cur}")
                b_open = box.addButton("Open Workbook",
                                       QMessageBox.AcceptRole)
                b_upd = box.addButton("Update Now", QMessageBox.ActionRole)
                b_un = box.addButton("Unlink", QMessageBox.DestructiveRole)
                box.addButton(QMessageBox.Cancel)
                box.setDefaultButton(b_open)
                box.exec()
                hit = box.clickedButton()
                if hit is b_un:
                    qlink.set_link(doc_path, None)
                    self._flash("Excel link removed")
                    return None
                if hit not in (b_open, b_upd):
                    return None
                path = cur
                if hit is b_open:
                    msg = qlink.update(v.doc, path)
                    if msg:
                        self._flash(msg)
                    self._open_file_external(path)
                    return path
            else:
                base = os.path.splitext(doc_path)[0] + " quantities.xlsx"
                path, _ = QFileDialog.getSaveFileName(
                    self, "Link Quantities to Excel", base,
                    "Excel (*.xlsx)")
                if not path:
                    return None
        new = cur != path
        qlink.set_link(doc_path, path)
        msg = qlink.update(v.doc, path)
        if msg:
            self._flash(msg)
        else:
            self._flash(f"Quantities linked to {os.path.basename(path)}; "
                        "it updates whenever the takeoff changes")
            if new and os.path.isfile(path) and QMessageBox.question(
                    self, "Quantity Link", "Open the workbook now?") == \
                    QMessageBox.Yes:
                self._open_file_external(path)
        return path

    def export_bid_package(self, folder=None, ask=None):
        """Estimate > Export Bid Package: the proposal, the estimate
        summary (PDF and Excel), the estimate detail, the takeoff sheets
        and - after AI Takeoff - the estimate workbook, in one folder and
        one zip, with a contents list of what still needs a look (Nov 17).
        `folder` and `ask` are for tests. Returns bidpackage.make's
        result or None."""
        from . import bidpackage, proposal
        v = self._view
        if not v:
            return None
        if folder is None:
            # Nov 19: the bid-submittal checklist first
            from .bidsubmittal_ui import SubmittalDialog
            sub = SubmittalDialog(v.doc, self)
            ok = sub.exec()
            self._doc_edited()
            if not ok:
                return None
            start = os.path.dirname(self._path or "") or os.path.expanduser(
                "~")
            folder = QFileDialog.getExistingDirectory(
                self, "Export Bid Package To", start)
            if not folder:
                return None
        ai = getattr(self, "_ai_dlg", None)
        res = rows = None
        try:
            if ai is not None and ai.view is v and ai.result:
                res, rows = ai.result, getattr(ai, "rows", None)
        except RuntimeError:                   # the dialog was closed
            res = rows = None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = bidpackage.make(v.doc, folder, comp=proposal.company(),
                                  ai_rows=rows, ai_result=res)
        except Exception as ex:                           # noqa: BLE001
            log.exception("bid package")
            QMessageBox.warning(self, "Bid Package",
                                f"Could not make the bid package:\n{ex}")
            return None
        finally:
            QApplication.restoreOverrideCursor()
        names = [os.path.basename(p) for _k, p in out["files"]]
        text = (f"{len(names)} file(s) in {os.path.basename(out['folder'])}"
                f", and {os.path.basename(out['zip'])} to send.")
        if out["skipped"]:
            text += "\n\nNot included:\n" + "\n".join(
                f"- {bidpackage._label(k)}: {why}" for k, why in out["skipped"])
        if out["checks"]:
            text += "\n\nBefore you send it:\n" + "\n".join(
                f"- {c}" for c in out["checks"])
        if ask is None:
            ask = (lambda t: QMessageBox.question(
                self, "Bid Package", t) == QMessageBox.Yes)
        # Nov 17: the Bid Board opportunity it is for can be marked sent
        opp = bidpackage.board_match(bidpackage.project_of(v.doc))
        out["board"] = None
        if opp is not None and ask(
                text + "\n\nMark \"" + (opp.get("project") or "") + "\" for "
                + (opp.get("gc") or "the GC") + " as Submitted on the Bid "
                "Board?"):
            try:
                out["board"] = bidpackage.mark_submitted(opp, out)
                self._flash("Marked Submitted on the Bid Board")
            except Exception:                             # noqa: BLE001
                log.warning("bid board", exc_info=True)
            text = "The bid package is ready."
        if ask(text + "\n\nOpen the folder?"):
            self._open_file_external(out["folder"])
        return out

    def export_external(self, path=None, ask=True):
        """Save a copy for subs, owners and other outsiders with the
        estimate, prices, margins and audit trail left out."""
        from . import acrobat2, jobdata
        if not self._view:
            return None
        if path is None:
            base = os.path.splitext(self._path or getattr(
                self._tab, "suggest", "") or "document.pdf")[0]
            path, _ = QFileDialog.getSaveFileName(
                self, "External Issue (strip pricing)",
                base + " - external.pdf", "PDF (*.pdf)")
            if not path:
                return None
        if self._path and os.path.abspath(path) == \
                os.path.abspath(self._path):
            QMessageBox.warning(self, "External Issue",
                                "Pick a new file name; this copy must not "
                                "replace your working file.")
            return None
        from . import safeio
        prot = getattr(self._view, "protection", None)
        try:
            try:
                removed = acrobat2.external_issue(
                    self._view.doc, path, prot.open_pw if prot else None)
            except safeio.UnprotectedCopyError as e:
                if not confirm_unprotected_copy(self, "External Issue",
                                                str(e)):
                    return None
                removed = acrobat2.external_issue(
                    self._view.doc, path, allow_unprotected=True)
        except Exception as ex:
            QMessageBox.warning(self, "External Issue",
                                f"Could not save:\n{ex}")
            return None
        what = ", ".join(l for _, l in jobdata.describe(self._view.doc)) \
            or "none"
        msg = (f"Saved {os.path.basename(path)} without job data "
               f"({what}) or hidden information.")
        if ask:
            QMessageBox.information(self, "External Issue", msg)
        self._flash(msg)
        return path, removed

    def export_pdfa(self, path=None):
        from .accessibility_ui import export_pdfa
        from . import jobdata
        v = self._view
        if v is not None and path is None and jobdata.describe(v.doc):
            # an archival copy can't carry attachments (review QS-003)
            if QMessageBox.question(
                    self, "PDF/A",
                    "The archival (PDF/A) copy won't include QuantiSheet's "
                    "job data (" + ", ".join(lab for _n, lab in
                                            jobdata.describe(v.doc)) +
                    "). This file keeps it - keep working in this one.\n\n"
                    "Make the archival copy?") != QMessageBox.Yes:
                return None
        return export_pdfa(self, path)

    def export_heavybid(self, folder=None, soil=None, result=None,
                        ask=True):
        """Civil > Export to HeavyBid (Excel): biditems, activities and
        resources from the civil takeoff (pipe by depth band, structures,
        trench excavation / bedding / backfill / haul), one single-sheet
        workbook each, in HeavyBid's import order (Chief's v22)."""
        from . import civil_export, civiltakeoff, heavy
        v = self._view
        if v is None:
            return None
        if result is None:
            scales = {p: (sc["ppu"], sc.get("unit", "ft"))
                      for p, sc in annotate.read_scales(v.doc).items()}
            if not scales:
                # instant: reading every title block first took minutes on
                # a 300-sheet set only to find no sheet had a scale
                QMessageBox.information(
                    self, "Export to CivilBid",
                    "No sheet in this set has a scale yet. Set the scale on "
                    "the utility plans (Takeoff > Auto Scale) and try "
                    "again.")
                return None
            if ask:
                return self._heavybid_in_background(v, None, scales,
                                                    folder, soil)
            pages = self._heavybid_pages(v.doc, scales)
            if not pages:
                QMessageBox.information(
                    self, "Export to CivilBid",
                    "No civil plan sheet with a scale was found. Set the "
                    "scale on the utility plans (Takeoff > Auto Scale) and "
                    "try again.")
                return None
            result = civiltakeoff.takeoff(v.doc, pages, scales)
        if not result.get("pipes") and not result.get("structures"):
            QMessageBox.information(self, "Export to CivilBid",
                                    "The civil takeoff found no pipe or "
                                    "structures to export.")
            return None
        if soil is None:
            names = [n for n, _ in self.SOILS]
            pick, ok = QInputDialog.getItem(
                self, "Export to CivilBid", "Trench walls:", names, 0, False)
            if not ok:
                return None
            soil = dict(self.SOILS)[pick]
        if folder is None:
            start = os.path.dirname(self._path) if self._path else \
                os.path.expanduser("~")
            folder = QFileDialog.getExistingDirectory(
                self, "Folder for the CivilBid files", start)
            if not folder:
                return None
        try:
            out = civil_export.heavybid_export(folder, result, soil)
        except ValueError as e:
            if ask and QMessageBox.question(
                    self, "Export to CivilBid",
                    f"{e}\n\nSome codes don't line up (an activity with no "
                    "biditem, or a resource with no activity). Export "
                    "anyway?") != QMessageBox.Yes:
                return None
            out = civil_export.heavybid_export(folder, result, soil,
                                               force=True)
        files = [os.path.basename(out[k]) for k in
                 ("biditems", "activities", "resources") if out.get(k)]
        if ask:
            QMessageBox.information(
                self, "Export to CivilBid",
                f"Wrote {', '.join(files)} to {folder}.\n\nIn HeavyBid "
                "(Menu > Exchange > Excel, Import):\n"
                "1. Back up the estimate first, and try a scratch estimate "
                "before a live one.\n"
                "2. Import biditems, then activities, then resources.\n"
                "3. Tick \"First row contains column titles\" and map the "
                "columns once in your Master Estimate so new estimates "
                "keep it.")
        return out

    def print_to(self, printer, pages=None):
        """Print `pages` (0-based; default the printer's page range)."""
        from PySide6.QtGui import QImage
        from PySide6.QtPrintSupport import QPrinter
        doc = self._view.doc
        if pages is None:
            first, last = printer.fromPage(), printer.toPage()
            if first == 0:
                first, last = 1, doc.page_count
            pages = list(range(first - 1, last))
        if printer.outputFormat() == QPrinter.PdfFormat and \
                printer.outputFileName():
            # Qt's own "print to file": write the pages, don't rasterize
            return bool(self.save_pages_pdf(printer.outputFileName(),
                                            pages=pages))
        dpi = min(300, max(72, printer.resolution()))
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "Print", "Could not start printing.")
            return False
        total = len(pages)
        prog = self._print_progress(total)
        cancelled = False
        try:
            for n, i in enumerate(pages):
                if prog is not None:
                    prog.setLabelText(f"Printing page {n + 1} of {total}"
                                      f"  (sheet {i + 1})")
                    prog.setValue(n)
                    QApplication.processEvents()
                    if prog.wasCanceled():
                        cancelled = True
                        printer.abort()
                        break
                if n:
                    printer.newPage()
                pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format_RGB888)
                area = painter.viewport()
                size = img.size().scaled(area.size(), Qt.KeepAspectRatio)
                painter.setViewport(area.x(), area.y(), size.width(),
                                    size.height())
                painter.setWindow(img.rect())
                painter.drawImage(0, 0, img)
                painter.setViewport(area)
        finally:
            if painter.isActive():
                painter.end()
            if prog is not None:
                prog.setValue(total)
                prog.close()
        if cancelled:
            self._flash("Printing cancelled")
            return False
        self._flash(f"Sent {total} page(s) to the printer")
        return True

    def export_quantities(self):
        if self._view:
            self.quantities.refresh()
            self.quantities._export_dialog()

    def export_sage(self, path=None, job=None):
        """Coded assembly lines as a Sage 300 CRE Job Cost budget import
        (Job, Extra, Cost Code, Category, Description, Units, UM, Amount).
        Lines without a cost code or category are listed, not exported."""
        from . import assembly_codes as ac, costlayer_ui, sage_export
        if not self._view:
            return None
        lib = costlayer_ui.load_library(self, quiet=True) or {}
        lines, unbound = ac.priced_lines(self._view.doc, lib)
        from . import estimate_lines            # Estimate panel lines too
        lines = list(lines) + estimate_lines.sage_lines(self._view.doc)
        if job is None:
            job, ok = QInputDialog.getText(self, "Sage 300 Job Cost",
                                           "Sage job number:")
            if not ok:
                return None
        rows, problems = sage_export.job_cost_rows(lines, job=job)
        if not rows:
            QMessageBox.information(
                self, "Sage 300 Job Cost",
                "Nothing to export: bind your takeoff to coded assemblies "
                "first (Civil > CivilBid-Coded Assemblies)."
                + (f"\n\n{len(unbound)} takeoff group(s) aren't bound yet."
                   if unbound else ""))
            return None
        if not path:
            pv = sage_export.preview(rows, problems)
            if QMessageBox.question(
                    self, "Export to Sage 300",
                    f"{pv['lines']} budget line(s) for job "
                    f"{', '.join(pv['jobs']) or '(none)'}, totalling "
                    f"${_c2(pv['total']):,.2f}." +
                    (f"\n{pv['left_out']} line(s) will be left out (no cost "
                     "code or category)." if pv["left_out"] else "") +
                    "\n\nWrite the import file?") != QMessageBox.Yes:
                return None
            path, _ = QFileDialog.getSaveFileName(
                self, "Export to Sage 300", "sage-job-cost.csv",
                "CSV (*.csv)")
            if not path:
                return None
        sage_export.export_csv(path, rows)
        # a file that backs the import out again, kept beside it
        rev = os.path.splitext(path)[0] + " (reversal).csv"
        try:
            sage_export.export_csv(rev, sage_export.reversal(rows))
        except OSError:
            rev = ""
        msg = f"{len(rows)} budget line(s) written to {os.path.basename(path)}."
        if rev:
            msg += (f"\n\nIf it goes to the wrong job, importing "
                    f"{os.path.basename(rev)} backs it out.")
        if problems or unbound:
            skipped = [f"line {p['line']}: {p['description']} - {p['reason']}"
                       for p in problems[:12]]
            if unbound:
                skipped.append(f"{len(unbound)} takeoff group(s) not bound "
                               "to an assembly")
            msg += "\n\nLeft out:\n" + "\n".join(skipped)
        QMessageBox.information(self, "Sage 300 Job Cost", msg)
        return path

    def export_geo(self, kind="kml", path=None):
        """Markups on an aerial photo page to Google Earth / GIS, in their
        real place on the map."""
        from . import geoexport
        v = self._view
        if v is None:
            return None
        if geoexport.geo_of(v.doc, v.page) is None:
            QMessageBox.information(
                self, "Export", "Go to an aerial photo page first (Civil or "
                "Takeoff > Aerial Photo Page). Only those pages know where "
                "they are on the map.")
            return None
        ext = ".kml" if kind == "kml" else ".geojson"
        if path is None:
            base = os.path.splitext(self._path or "markups")[0]
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Markups to " + ("Google Earth" if kind == "kml"
                                              else "GIS"),
                base + ext, ("KML (*.kml)" if kind == "kml"
                             else "GeoJSON (*.geojson)"))
            if not path:
                return None
        n = (geoexport.to_kml if kind == "kml" else geoexport.to_geojson)(
            v.doc, v.page, path)
        self._flash(f"Exported {n} markup(s) to {os.path.basename(path)}")
        return n

    def add_printer(self, confirm=True):
        """Help > Add the QuantiSheet Printer: adds "QuantiSheet" to Windows'
        printers (print from any program and it opens here). Needs an
        administrator - Windows asks. The server setup and the MSI add it
        for every user already."""
        import subprocess
        import sys
        if not sys.platform.startswith("win"):
            return False
        if confirm and QMessageBox.question(
                self, "QuantiSheet Printer",
                "Add a printer named \"QuantiSheet\" to Windows?\n\n"
                "Print from any program to \"QuantiSheet\" and the pages "
                "open here as a new PDF (a copy is kept in Documents\\"
                "QuantiSheet\\Printed).\n\nWindows will ask for an "
                "administrator's permission.") != QMessageBox.Yes:
            return False
        import ctypes
        if getattr(sys, "frozen", False):
            exe, args = sys.executable, "printer --install"
            # never run as administrator a program any user can change
            # (threat model T-006: a per-user install lives in the user's
            # own folder - a swapped QuantiSheet.exe would get admin rights)
            if user_writable(os.path.dirname(exe)):
                QMessageBox.information(
                    self, "QuantiSheet Printer",
                    "This copy of QuantiSheet is installed just for you, in "
                    "a folder you can change, so it can't be given "
                    "administrator rights to add a printer.\n\nTo add the "
                    "printer, install QuantiSheet for all users (run the "
                    "setup as an administrator), or ask your IT person.")
                return False
        else:
            root = os.path.dirname(os.path.dirname(os.path.abspath(
                __file__)))
            exe = sys.executable
            args = f'"{os.path.join(root, "quantisheet.py")}" printer --install'
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args,
                                                 None, 0)
        if rc <= 32:                     # declined or failed
            QMessageBox.information(self, "QuantiSheet Printer",
                                    "The printer wasn't added (Windows "
                                    "didn't get an administrator's OK).")
            return False
        # the helper that opens printed pages runs as you, from sign-in
        try:
            from . import printer_setup, printhelper
            printer_setup._set_run("HKEY_CURRENT_USER",
                                   printhelper.helper_command())
            printhelper.ensure_running()
        except Exception:                                 # noqa: BLE001
            log.warning("print helper not turned on", exc_info=True)
        self.statusBar().showMessage(
            "Adding the QuantiSheet printer - it appears in Windows' "
            "printers in a few seconds.", 10000)
        return True

    def export_as(self, fmt):
        from . import acrobat
        if not self._view:
            return None
        doc = self._view.doc
        if fmt in ("png", "jpg"):
            folder = QFileDialog.getExistingDirectory(self, "Save Images To")
            if not folder:
                return None
        else:
            filt = {"docx": "Word (*.docx)", "xlsx": "Excel (*.xlsx)",
                    "txt": "Text (*.txt)", "pptx": "PowerPoint (*.pptx)",
                    "html": "Web page (*.html)"}[fmt]
            path = self._ask_save("Export", "." + fmt, filt)
            if not path:
                return None
        # every export runs on a worker thread now: Excel on a 4-sheet set
        # held the window for 25 s (review 0.12.29, step 9)
        if fmt != "txt":
            return self._export_big(fmt, folder if fmt in ("png", "jpg")
                                    else path)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if fmt in ("png", "jpg"):
                out = acrobat.export_images(doc, folder, fmt, dpi=150)
                msg = f"Saved {len(out)} images"
            elif fmt == "docx":
                out = acrobat.export_word(doc, path)
                msg = "Exported to Word (text and tables; layout simplified)"
            elif fmt == "pptx":
                from . import acrobat2
                out = acrobat2.export_powerpoint(doc, path)
                msg = "Exported to PowerPoint (one slide per page)"
            elif fmt == "html":
                from . import acrobat2
                out = acrobat2.export_html(doc, path)
                msg = "Exported web page"
            elif fmt == "xlsx":
                n = acrobat.export_excel(doc, path)
                out = path
                msg = f"Exported {n} sheet(s) to Excel"
            else:
                out = acrobat.export_text(doc, path)
                msg = "Exported text"
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Export", f"Export failed:\n{ex}")
            return None
        QApplication.restoreOverrideCursor()
        self._flash(msg)
        return out

    def import_dxf(self, path=None, out=None, what=None):
        """A DXF drawing as PDF ready for takeoff: model space on one
        sheet at a standard scale with its layers, or the paper space
        sheets as plotted with each viewport's scale."""
        from . import dxf
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Import AutoCAD DXF", "", "AutoCAD DXF (*.dxf)")
            if not path:
                return None
        if what is None:
            try:
                sheets = dxf.layouts(path)
            except Exception as ex:
                QMessageBox.warning(self, "Import DXF", str(ex))
                return None
            what = "model"
            if sheets:
                n_vp = sum(n for _, n in sheets)
                choices = [f"Sheets as plotted ({len(sheets)} layout(s), "
                           f"{n_vp} viewport(s), each with its scale)",
                           "Model space (one sheet, with layers you can "
                           "switch on and off)"]
                pick, ok = QInputDialog.getItem(
                    self, "Import AutoCAD DXF", "What to import:", choices,
                    0, False)
                if not ok:
                    return None
                what = "layouts" if pick == choices[0] else "model"
        if out is None:
            base = os.path.splitext(path)[0]
            out = base + ".pdf"
            if os.path.exists(out):
                out = base + " (from DXF).pdf"
            out, _ = QFileDialog.getSaveFileName(
                self, "Save the Drawing as PDF", out, "PDF (*.pdf)")
            if not out:
                return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            info = dxf.to_pdf(path, out, what=what)
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Import DXF", str(ex))
            return None
        QApplication.restoreOverrideCursor()
        self.open_path(out)
        if what == "layouts":
            msg = (f"Imported {info['pages']} sheet(s) with "
                   f"{info['viewports']} viewport(s) ({info['scale']}). "
                   "Each viewport has its scale, so takeoff is exact.")
            if info.get("layers_off"):
                msg += (f" {info['layers_off']} layer(s) were off in the "
                        "drawing and came in switched off.")
        else:
            msg = (f"Imported at {info['scale']} on {info['sheet']}, "
                   f"{info['layers']} layer(s). The scale is set, so you "
                   "can measure right away (layers: Markup > Layers).")
            if info.get("layers_off"):
                msg += (f" {info['layers_off']} layer(s) were off in the "
                        "drawing and came in switched off.")
        if info.get("turned_on"):
            msg += (" Almost every layer was switched off in the file, so "
                    "they all came in on (Markup > Layers to hide some).")
        if info["skipped"]:
            msg += f" {info['skipped']} item(s) couldn't be drawn."
        self.statusBar().showMessage(msg, 15000)
        return info

    def export_dxf(self, path=None):
        """This page's line work, text, markups and takeoff as a DXF."""
        from . import annotate, dxf
        v = self._view
        if not v:
            return None
        if path is None:
            path = self._ask_save("Export AutoCAD DXF",
                                  f" - page {v.page + 1}.dxf",
                                  "AutoCAD DXF (*.dxf)")
            if not path:
                return None
        page = v.page
        has_scale = bool(annotate.read_scales(v.doc).get(page))

        def done(info):
            # on the window thread once the worker has written the file
            self._flash(
                f"Exported {info['entities']} items to DXF in "
                f"{'real ' + info['units'] if has_scale else 'paper inches (no scale set)'}.",
                15000)
        # off the window thread: one sheet held it for 14 s (review 0.12.29)
        self._in_background("Export DXF", f"Exporting page {page + 1} to "
                            "DXF...", lambda d: dxf.from_page(d, page, path),
                            done)
        return path
