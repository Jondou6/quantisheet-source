"""First run: create the company's first Admin."""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel,
                               QLineEdit)

from .. import APP_NAME, security


class FirstRunDialog(QDialog):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        self.setWindowTitle(f"{APP_NAME} - first run")
        lay = QFormLayout(self)
        self.company = QLineEdit()
        self.name = QLineEdit()
        self.email = QLineEdit()
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addRow("Company name", self.company)
        lay.addRow("Your name", self.name)
        lay.addRow("Email", self.email)
        lay.addRow("Password (10+ characters)", self.pw)
        self.msg = QLabel("")
        lay.addRow(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.create)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def create(self):
        if len(self.pw.text()) < 10 or not self.email.text().strip():
            self.msg.setText("Enter an email and a password of 10 or more "
                             "characters.")
            return False
        security.add_user(self.office.db, self.name.text().strip() or "Admin",
                          self.email.text().strip(), "Admin", self.pw.text())
        self.office.sign_in(self.email.text().strip(), self.pw.text())
        self.office.set_company(name=self.company.text().strip())
        self.accept()
        return True
