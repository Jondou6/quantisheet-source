"""ClaimIT: a separate, optional claims estimating program for
residential and commercial property claims.

It runs as its own process (python -m quantisheet_claims, or
ClaimIT.exe). QuantiSheet hands it takeoff quantities through one
JSON file (see interface.py); nothing else is shared. The module never
imports QuantiSheet's `app` package and never writes QuantiSheet data.

Money is integer cents, rates are integer basis points (10000 = 100%),
quantities are integer ten-thousandths (qty_q4). Every rounding goes
through cents.div_round_half_up.

No ESX import or export (Jon, Oct 20, 2026). Do not read or write
Xactimate files.
"""
__version__ = "0.2.2"
INTERFACE_VERSION = 1
