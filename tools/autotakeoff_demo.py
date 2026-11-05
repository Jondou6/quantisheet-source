"""Make trial\\autotakeoff_demo.pdf: the A-sheets with 1/4" = 1'-0" set."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))
import fitz                                    # noqa: E402

from app import annotate                       # noqa: E402

doc = fitz.open(sys.argv[1])
annotate.apply_op(doc, annotate.new_op(
    "set_scale", 0, ppu=18.0, unit="ft",
    pages=list(range(doc.page_count))))
doc.save(sys.argv[2])
