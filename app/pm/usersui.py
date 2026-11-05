"""Project Center > project menu > Users and roles: per-person logins on
the shared project (email + password) with a role each.

Admin - everything, including logins. Project manager - everything else.
Estimator - bidding, budget, change events, RFIs, meetings, the team.
Subcontractor - adds RFIs, submittals, punch items, observations, daily
logs and issues, and changes only their own or ones assigned to them.
Viewer - reads everything, changes nothing.
"""
import secrets

from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..collab.hub import ROLE_NAMES, ROLES
from .store import StoreError


def temp_password():
    """A readable starting password to give someone (they can change it)."""
    words = ["brick", "steel", "rebar", "grout", "joist", "truss", "plumb",
             "level", "rafter", "footer", "slab", "beam", "stud", "flash"]
    # two words for readability plus 8 characters from an unambiguous
    # 31-letter alphabet: about 47 bits (was ~17; review 3 #23)
    alpha = "23456789abcdefghjkmnpqrstuvwxyz"
    tail = "".join(secrets.choice(alpha) for _ in range(8))
    return f"{secrets.choice(words)}-{secrets.choice(words)}-{tail}"


class AddUserDialog(QDialog):
    def __init__(self, parent=None, first=False, me=""):
        super().__init__(parent)
        self.setWindowTitle("Turn On Logins" if first else "Add a Login")
        v = QVBoxLayout(self)
        if first:
            lab = QLabel("Logins replace the shared project password: each "
                         "person signs in with their own email and password "
                         "and a role. Start with your own login (admin). "
                         "Everyone else must then sign in again with a "
                         "login you give them.")
            lab.setWordWrap(True)
            v.addWidget(lab)
        f = QFormLayout()
        self.email = QLineEdit()
        self.name = QLineEdit(me if first else "")
        self.role = QComboBox()
        for r in ROLES:
            self.role.addItem(ROLE_NAMES[r], r)
        if first:
            self.role.setEnabled(False)
        else:
            self.role.setCurrentIndex(ROLES.index("sub"))
        self.pw = QLineEdit("" if first else temp_password())
        if first:
            self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("8 or more characters")
        f.addRow("Email", self.email)
        f.addRow("Name", self.name)
        f.addRow("Role", self.role)
        f.addRow("Password", self.pw)
        v.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self):
        return {"email": self.email.text().strip(),
                "name": self.name.text().strip(),
                "role": self.role.currentData(),
                "password": self.pw.text()}


class UsersDialog(QDialog):
    def __init__(self, center):
        super().__init__(center)
        self.center = center
        self.store = center.store
        self.setWindowTitle("Users and Roles")
        self.resize(760, 460)
        v = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Email", "Name", "Role",
                                              "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.add_btn = QPushButton("Add Login…")
        self.add_btn.clicked.connect(lambda: self.add())
        self.role_btn = QPushButton("Change Role…")
        self.role_btn.clicked.connect(lambda: self.change_role())
        self.reset_btn = QPushButton("Reset Password…")
        self.reset_btn.clicked.connect(lambda: self.reset_password())
        self.off_btn = QPushButton("Disable / Enable")
        self.off_btn.clicked.connect(lambda: self.toggle())
        self.rm_btn = QPushButton("Remove")
        self.rm_btn.clicked.connect(lambda: self.remove())
        self.mine_btn = QPushButton("Change My Password…")
        self.mine_btn.clicked.connect(lambda: self.my_password())
        for b in (self.add_btn, self.role_btn, self.reset_btn, self.off_btn,
                  self.rm_btn, self.mine_btn):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        legend = QLabel(__doc__.split("\n\n", 1)[1].replace("\n", " "))
        legend.setWordWrap(True)
        legend.setObjectName("muted")
        v.addWidget(legend)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.users = []
        self.refresh()

    # ---------------------------------------------------------- list
    def refresh(self):
        h = self.store.data.get("hub") or {}
        admin = self.store.role == "admin"
        try:
            self.users = self.store.users() if admin else []
        except StoreError as e:
            self.info.setText(str(e))
            self.users = []
        if not h.get("logins"):
            self.info.setText("This project uses one shared password. Turn "
                              "on logins to give each person their own "
                              "email, password and role.")
            self.add_btn.setText("Turn On Logins…")
        else:
            from ..collab.hub import ROLE_NAMES as RN
            self.info.setText(f"Signed in as {h.get('user') or ''} "
                              f"<{h.get('email')}> - "
                              f"{RN.get(self.store.role)}.")
            self.add_btn.setText("Add Login…")
        for b in (self.add_btn, self.role_btn, self.reset_btn, self.off_btn,
                  self.rm_btn):
            b.setEnabled(admin)
        self.mine_btn.setEnabled(bool(h.get("logins")))
        self.table.setRowCount(len(self.users))
        for i, u in enumerate(self.users):
            for j, val in enumerate((u["email"], u.get("name", ""),
                                     ROLE_NAMES.get(u["role"], u["role"]),
                                     "Disabled" if u.get("disabled")
                                     else "Active")):
                self.table.setItem(i, j, QTableWidgetItem(val))
        return self.users

    def selected(self):
        r = self.table.currentRow()
        return self.users[r] if 0 <= r < len(self.users) else None

    def _do(self, fn, *a, **k):
        try:
            return fn(*a, **k)
        except StoreError as e:
            QMessageBox.warning(self, "Users and Roles", str(e))
            return None
        finally:
            self.refresh()

    # ---------------------------------------------------------- edits
    def add(self, values=None):
        first = not (self.store.data.get("hub") or {}).get("logins")
        if values is None:
            dlg = AddUserDialog(self, first, self.store.me)
            if not dlg.exec():
                return None
            values = dlg.values()
        if first:
            values["role"] = "admin"
        r = self._do(self.store.add_user, values["email"],
                     values.get("name") or values["email"],
                     values["role"], values["password"])
        if r and not first:
            QMessageBox.information(
                self, "Login added",
                f"Send {values['email']} the project name "
                f"\"{self.store.name}\", the relay address and this "
                f"password: {values['password']}\n\nThey can change it "
                "after they sign in.")
        return r

    def change_role(self, role=None):
        u = self.selected()
        if u is None:
            return None
        if role is None:
            names = [ROLE_NAMES[r] for r in ROLES]
            pick, ok = QInputDialog.getItem(
                self, "Change Role", f"Role for {u['email']}", names,
                ROLES.index(u["role"]) if u["role"] in ROLES else 0, False)
            if not ok:
                return None
            role = ROLES[names.index(pick)]
        return self._do(self.store.set_user, u["email"], role=role)

    def reset_password(self, password=None):
        u = self.selected()
        if u is None:
            return None
        password = password or temp_password()
        r = self._do(self.store.set_user, u["email"], password=password)
        if r:
            QMessageBox.information(self, "Password reset",
                                    f"New password for {u['email']}: "
                                    f"{password}")
        return r

    def toggle(self):
        u = self.selected()
        if u is None:
            return None
        return self._do(self.store.set_user, u["email"],
                        disabled=not u.get("disabled"))

    def remove(self, confirm=True):
        u = self.selected()
        if u is None:
            return None
        if confirm and QMessageBox.question(
                self, "Remove login", f"Remove {u['email']}'s login?") \
                != QMessageBox.Yes:
            return None
        return self._do(self.store.remove_user, u["email"])

    def my_password(self, old=None, new=None):
        if old is None:
            old, ok = QInputDialog.getText(self, "Change My Password",
                                           "Current password",
                                           QLineEdit.Password)
            if not ok:
                return None
            new, ok = QInputDialog.getText(self, "Change My Password",
                                           "New password (8 or more "
                                           "characters)", QLineEdit.Password)
            if not ok:
                return None
        return self._do(self.store.change_password, old, new)
