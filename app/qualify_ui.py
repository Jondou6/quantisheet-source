"""Qualification badges and the award warning, for the windows that level
bids (see qualify.py)."""
from PySide6.QtWidgets import QInputDialog

from . import qualify, settings

NO_WARNING, CANCELLED = "no warning", "cancelled"


def _contacts(contacts):
    if contacts is not None:
        return contacts
    try:
        from . import subdir
        return subdir.load()
    except Exception:                                     # noqa: BLE001
        return []


def line(pairs, contacts=None):
    """The badges line for [(bidder name, bid in dollars or None)]."""
    cs = _contacts(contacts)
    return qualify.html([
        (n, qualify.badges(qualify.find(n, cs),
                           None if a is None else float(a)))
        for n, a in pairs])


def confirm(parent, company, amount=None, title="Award", contacts=None,
            reason=None):
    """Before an award or a quote goes into the estimate. Returns
    NO_WARNING, CANCELLED, or the override record (qualify.override) when
    the user gave a reason to go ahead in spite of a warning."""
    warn = qualify.award_warnings(
        qualify.find(company, _contacts(contacts)),
        None if amount is None else float(amount))
    if not warn:
        return NO_WARNING
    if reason is None:
        reason, ok = QInputDialog.getText(
            parent, title, f"{company}:\n- " + "\n- ".join(warn) +
            "\n\nTo go ahead anyway, give the reason (it is kept with the "
            "award):")
        if not ok:
            return CANCELLED
    try:
        return qualify.override(company, warn, reason,
                                settings.get("author", "") or "")
    except ValueError:
        return CANCELLED
