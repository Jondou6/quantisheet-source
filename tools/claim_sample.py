"""Sample schedule claim package and quality check (made-up job):
python tools/claim_sample.py out_claim.pdf out_check.pdf"""
import datetime as dt
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from app import settings                                     # noqa: E402

tmp = tempfile.mkdtemp()
settings.DIR = os.path.join(tmp, "cfg")
settings.PATH = os.path.join(tmp, "cfg", "s.json")
settings._cache = {"author": "Pat Example"}


class MP:
    def setattr(self, o, n, v):
        setattr(o, n, v)

    def setenv(self, *a):
        pass


import pathlib                                               # noqa: E402
import test_claim_package as T                               # noqa: E402
from app.pm import claim_package, schedule_check             # noqa: E402

s = T._job(pathlib.Path(tmp), MP())
today = dt.date(2026, 11, 20)
claim_package.export_pdf(s, sys.argv[1], today)
schedule_check.export_pdf(s, sys.argv[2], today)
print("ok")
