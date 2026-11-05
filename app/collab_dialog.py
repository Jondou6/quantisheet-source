from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QRadioButton, QButtonGroup
)
from .collab.session import CollabSession


class CollabDialog(QDialog):
    """Connect to (or disconnect from) a collaboration room.

    The session lives on the view, so it keeps running after this dialog
    closes and the person can carry on editing. Status shows in the main
    window's status bar.
    """

    def __init__(self, view, parent=None, relay=None, on_status=None):
        super().__init__(parent)
        self.view = view
        self.on_status = on_status
        self.setWindowTitle("Live Collaboration")
        self.resize(460, 260)
        layout = QVBoxLayout(self)

        session = getattr(view, "session", None)
        if session:
            self._build_connected(layout, session)
            return

        if relay:
            ws_url, web_url = relay.urls()
            layout.addWidget(QLabel(
                f"Relay running on this computer.\n"
                f"Desktop peers connect to: {ws_url}\n"
                f"Phones open: {web_url}\n"
                "The phone link includes the relay token: anyone who has "
                "it can join and edit. Share it like a password."))
            default_url, host_default = "ws://localhost:8765", True
        else:
            layout.addWidget(QLabel(
                "To host, start the relay first (Tools > Start Relay).\n"
                "To join, enter the host's relay address."))
            default_url, host_default = "ws://localhost:8765", False

        r = QHBoxLayout()
        r.addWidget(QLabel("Relay URL:"))
        self.url = QLineEdit(default_url)
        r.addWidget(self.url, 1)
        layout.addLayout(r)

        from . import settings
        rt = QHBoxLayout()
        rt.addWidget(QLabel("Relay token:"))
        self.token = QLineEdit((getattr(relay, "token", None) if relay
                                else None) or settings.get("collab_token")
                               or "")
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("from whoever runs the relay")
        rt.addWidget(self.token, 1)
        layout.addLayout(rt)

        from PySide6.QtWidgets import QCheckBox
        self.plain_lan = QCheckBox(
            "In-house network: allow unencrypted connections (ws://)")
        self.plain_lan.setToolTip(
            "Without a wss:// relay, the relay token, room password and "
            "drawings cross the network readable by anyone on it. Only for a "
            "trusted office network.")
        self.plain_lan.setChecked(bool(settings.get("collab_allow_plain_lan")))
        self.plain_lan.toggled.connect(
            lambda on: settings.set("collab_allow_plain_lan", bool(on)))
        layout.addWidget(self.plain_lan)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Room:"))
        self.room = QLineEdit("default")
        r2.addWidget(self.room)
        r2.addWidget(QLabel("Password:"))
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("first to join sets it")
        r2.addWidget(self.pw, 1)
        layout.addLayout(r2)

        r3 = QHBoxLayout()
        self.as_host = QRadioButton("Host (share my document)")
        self.as_peer = QRadioButton("Join (get the host's document)")
        group = QButtonGroup(self)
        group.addButton(self.as_host)
        group.addButton(self.as_peer)
        (self.as_host if host_default else self.as_peer).setChecked(True)
        r3.addWidget(self.as_host)
        r3.addWidget(self.as_peer)
        layout.addLayout(r3)

        layout.addWidget(QLabel(
            "Note: traffic is not encrypted. Use on networks you trust."))

        b = QHBoxLayout()
        connect = QPushButton("Connect")
        connect.setDefault(True)
        connect.clicked.connect(self._connect)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        b.addStretch()
        b.addWidget(connect)
        b.addWidget(cancel)
        layout.addLayout(b)

    def _build_connected(self, layout, session):
        c = session.client
        state = "connected" if c.connected else (c.error or "connecting…")
        layout.addWidget(QLabel(
            f"Room “{c.room}” on {c.url}\n"
            f"Role: {session.role}\nStatus: {state}\n"
            f"People in room: {c.peer_count}"))
        b = QHBoxLayout()
        if session.role == "host":
            send = QPushButton("Resend Document to Everyone")
            send.clicked.connect(lambda: (session.push_document(force=True),
                                          self.accept()))
            b.addWidget(send)
        disc = QPushButton("Disconnect")
        disc.clicked.connect(self._disconnect)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        b.addStretch()
        b.addWidget(disc)
        b.addWidget(close)
        layout.addLayout(b)

    def _connect(self):
        from . import settings
        tok = self.token.text().strip() or None
        if tok:
            settings.set("collab_token", tok)
        session = CollabSession(
            self.view, self.url.text().strip(),
            room=self.room.text().strip() or "default", token=tok,
            password=self.pw.text() or None,
            role="host" if self.as_host.isChecked() else "peer",
            on_status=self.on_status)
        self.view.session = session
        session.start()
        if self.on_status:
            self.on_status("connecting…")
        self.accept()

    def _disconnect(self):
        self.view.session.stop()
        self.view.session = None
        if self.on_status:
            self.on_status("disconnected")
        self.accept()
