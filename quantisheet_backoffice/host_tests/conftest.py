"""QuantiSheet's side of the Back Office hook (brief tests 1.1 and 1.3).
These need QuantiSheet's own code, so they are NOT part of the Back
Office suite (quantisheet_backoffice/tests never imports app). Run them
from the QuantiSheet folder together with its suite:

    python -m pytest tests quantisheet_backoffice/host_tests

They reuse QuantiSheet's own tests/conftest.py fixtures (no real registry,
no real Group Policy) and tests/test_gui.py's window fixture."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
TESTS = os.path.join(ROOT, "tests")
for p in (ROOT, TESTS):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QUANTISHEET_DRAW_PROCESS", "0")

_spec = importlib.util.spec_from_file_location(
    "_quantisheet_tests_conftest", os.path.join(TESTS, "conftest.py"))
_host = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_host)
_no_real_registry = _host._no_real_registry          # autouse fixture
