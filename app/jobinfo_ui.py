"""The Job Info fields (description, website / contact, job ZIP, location
region and project image) - a tab of Create Proposal."""
import os

from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QWidget)

from . import jobinfo

AUTO = ""          # region combo: let the ZIP / cost book decide


class JobInfoWidget(QWidget):
    def __init__(self, doc, data=None, parent=None):
        super().__init__(parent)
        self.doc = doc
        from . import proposal
        data = data if data is not None else proposal.read(doc)
        f = QFormLayout(self)
        self.description = QPlainTextEdit(str(data.get("description") or ""))
        self.description.setFixedHeight(64)
        self.description.setPlaceholderText("What the job is, in a sentence "
                                            "or two (shown on the cover)")
        f.addRow("Description:", self.description)
        self.website = QLineEdit(str(data.get("website") or ""))
        self.website.setPlaceholderText("Website, or owner / contact link")
        f.addRow("Website / contact:", self.website)
        self.zip = QLineEdit(str(data.get("job_zip") or ""))
        self.zip.setPlaceholderText("e.g. 29401")
        self.zip.setMaxLength(10)
        self.zip.textChanged.connect(self._show_region)
        f.addRow("Job ZIP:", self.zip)
        self.region = QComboBox()
        self.region.addItem("From the job ZIP (or cost book)", AUTO)
        try:
            from . import locfactors
            names = [r["region"] for r in locfactors.rows()]
        except Exception:                                 # noqa: BLE001
            names = []
        picked = str(data.get("location_region") or "")
        if picked and picked not in names:
            names.append(picked)
        for n in names:
            self.region.addItem(n, n)
        i = self.region.findData(picked) if picked else 0
        self.region.setCurrentIndex(max(0, i))
        self.region.currentIndexChanged.connect(self._show_region)
        row = QHBoxLayout()
        row.addWidget(self.region, 1)
        b = QPushButton("Location Factors…")
        b.setToolTip("Search by state, city, abbreviation or ZIP; add your "
                     "own regions and factors")
        b.clicked.connect(self.location_factors)
        row.addWidget(b)
        f.addRow("Location region:", row)
        self.region_label = QLabel("")
        self.region_label.setWordWrap(True)
        f.addRow(self.region_label)
        row = QHBoxLayout()
        self.image = QLineEdit(str(data.get("image_name") or ""))
        self.image.setReadOnly(True)
        self.image.setPlaceholderText("PNG or JPG, up to 10 MB (optional)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self.pick_image())
        clear = QPushButton("Remove")
        clear.clicked.connect(self.remove_image)
        row.addWidget(self.image, 1)
        row.addWidget(browse)
        row.addWidget(clear)
        f.addRow("Project image:", row)
        f.addRow(QLabel("<small>Saved in the PDF with the proposal details;"
                        " the image and description go on the proposal "
                        "cover.</small>"))
        self.new_image = None          # a path picked here, embedded on OK
        self.drop_image = False
        self._show_region()

    def values(self):
        return {"description": self.description.toPlainText().rstrip(),
                "website": self.website.text().strip(),
                "job_zip": jobinfo.clean_zip(self.zip.text()),
                "location_region": self.region.currentData() or ""}

    def current_region(self):
        """(region, how) the job would use with what's typed here."""
        return jobinfo.region_source(self.doc, self.values())

    def _show_region(self, *_):
        reg, how = self.current_region()
        z = jobinfo.clean_zip(self.zip.text())
        if how == "picked":
            txt = f"Region: <b>{reg}</b> (picked for this job)"
        elif how == "zip":
            txt = f"Region: <b>{reg}</b> (from ZIP {z})"
        elif reg:
            txt = f"Region: <b>{reg}</b> (the job's cost book region)"
            if z:
                txt += f"<br>No region for {z} - pick one or add it"
        else:
            txt = (f"No region for {z} - pick one or add it" if z else
                   "Region: none yet - type the job ZIP or pick one")
        self.region_label.setText(txt)
        return reg

    def pick_image(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Project Image", "", "Images (*.png *.jpg *.jpeg)")
        if not path:
            return False
        try:
            jobinfo.check_image(path)
        except jobinfo.ImageError as e:
            QMessageBox.warning(self, "Project Image", str(e))
            return False
        self.new_image, self.drop_image = path, False
        self.image.setText(os.path.basename(path))
        return True

    def remove_image(self):
        self.new_image, self.drop_image = None, True
        self.image.clear()

    def commit(self):
        """Embed (or remove) the image picked here. False, with a message,
        when it was refused."""
        try:
            if self.new_image:
                jobinfo.set_image(self.doc, self.new_image)
            elif self.drop_image:
                jobinfo.clear_image(self.doc)
        except (jobinfo.ImageError, OSError) as e:
            QMessageBox.warning(self, "Project Image", str(e))
            return False
        self.new_image, self.drop_image = None, False
        return True

    def location_factors(self):
        from .location_ui import LocationFactorsDialog
        dlg = LocationFactorsDialog(self, search=self.zip.text().strip())
        self._loc_dlg = dlg
        if dlg.exec():
            pick = dlg.chosen()
            if pick:
                if self.region.findData(pick) < 0:
                    self.region.addItem(pick, pick)
                self.region.setCurrentIndex(self.region.findData(pick))
        self._show_region()
        return dlg
