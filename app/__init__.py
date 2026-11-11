__version__ = "1.1.4"


# Money rounds half up everywhere, the way an estimator rounds by hand:
# Decimal's default is half-even, which made 1.125 into 1.12 wherever a
# quantize() forgot rounding= (Chief's round 5, Nov 9). DefaultContext is
# what new threads copy; getcontext() is this one.
import decimal as _decimal
_decimal.DefaultContext.rounding = _decimal.ROUND_HALF_UP
_decimal.getcontext().rounding = _decimal.ROUND_HALF_UP

# PyMuPDF's old "fitz" name prints a deprecation warning on import; point
# it at the real module (pymupdf) so `import fitz` everywhere stays quiet
# and keeps working.
import sys as _sys

try:
    import pymupdf as _pymupdf
    _sys.modules.setdefault("fitz", _pymupdf)
except ImportError:                      # very old PyMuPDF: only "fitz"
    pass


import logging as _logging


def _more_open_files():
    """The PDF engine (MuPDF) opens files through the Windows C runtime,
    which allows only 512 at once by default. A long session on a big set
    reached that ("Too many open files" saving a copy of a 309-sheet set),
    so allow 8192 - the runtime's maximum. One runtime is shared by every
    module in the process, so this covers MuPDF too."""
    if not _sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        crt = ctypes.cdll.ucrtbase
        if crt._getmaxstdio() < 8192:
            crt._setmaxstdio(8192)
        n = crt._getmaxstdio()
        _logging.getLogger(__name__).debug("open-file limit %s", n)   # L1
        return n
    except Exception:
        _logging.getLogger(__name__).debug("open-file limit unchanged",
                                           exc_info=True)
        return None


_more_open_files()
