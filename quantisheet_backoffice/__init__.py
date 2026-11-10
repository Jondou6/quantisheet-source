"""QuantiSheet Back Office: an optional add-on program beside app/.

QuantiSheet starts it as a separate process through
app/backoffice_hook.py and hands it one read-only JSON snapshot per job.
This package never imports the host's app package and keeps its own
settings, data folder and tests.
"""
__version__ = "0.4.0"
APP_NAME = "QuantiSheet Back Office"


# Money rounds half up everywhere, the way an estimator rounds by hand:
# Decimal's default is half-even, which made 1.125 into 1.12 wherever a
# quantize() forgot rounding= (Chief's round 5, Nov 9). DefaultContext is
# what new threads copy; getcontext() is this one.
import decimal as _decimal
_decimal.DefaultContext.rounding = _decimal.ROUND_HALF_UP
_decimal.getcontext().rounding = _decimal.ROUND_HALF_UP
