"""Service desk for release 1.1.1.

Work orders, agreements, refrigerant logs, backflow reports, a flat-rate
pricebook, truck stock, technician recommendations, signed time-and-material
tags, closeout handover and a dispatch board. They sit on Equipment &
Service Records and the customer quote. Each tool is its own module and
window.

Nothing in this package makes a network call. Nothing in this package
imports Back Office. Company names and logos come from proposal.company()
at print time.

Wire the windows from menu.ENTRIES. This package does not edit the ribbon.
"""
from .menu import ENTRIES

__all__ = ["ENTRIES"]
