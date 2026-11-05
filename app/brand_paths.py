"""QuantiSheet's own folders outside the settings folder (settings.DIR):
%LOCALAPPDATA%\\QuantiSheet (the print helper's log, the Code Library) and
Documents\\QuantiSheet\\Printed (printed PDFs)."""
import os

NEW = "QuantiSheet"
PRINTED = "Printed"
CODE_LIBRARY = "Code Library"


def printed_folder(documents):
    """<Documents>\\QuantiSheet\\Printed."""
    return os.path.join(documents, NEW, PRINTED)


def local_dir():
    """%LOCALAPPDATA%\\QuantiSheet (off Windows: ~/QuantiSheet)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, NEW)
