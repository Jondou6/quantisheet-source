"""The snapshot QuantiSheet hands over (app/backoffice_hook.py writes it to
a new quantisheet-backoffice-* folder in the system temp folder). It holds
job data, so Back Office deletes it once imported. Only that kind of file
is ever deleted: a snapshot the user picked by hand is left alone."""
from __future__ import annotations

import os
import shutil
import tempfile

PREFIX = "quantisheet-backoffice-"
NAME = "snapshot.json"


def is_handoff(path) -> bool:
    p = os.path.realpath(path)
    folder = os.path.dirname(p)
    tmp = os.path.realpath(tempfile.gettempdir())
    return (os.path.basename(p) == NAME and
            os.path.basename(folder).startswith(PREFIX) and
            os.path.dirname(folder) == tmp)


def discard(path) -> bool:
    """Delete a hand-off snapshot and its temp folder. True if deleted."""
    if not path or not is_handoff(path):
        return False
    shutil.rmtree(os.path.dirname(os.path.realpath(path)), ignore_errors=True)
    return not os.path.exists(path)
