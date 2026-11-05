"""Where each service window should be wired.

This release does not edit the ribbon, menus or main window. The other
developer adds one entry per row. `call` is module.function; each
open_window(parent=None) shows the window and returns it.
"""

# label, where it should go, function to call
ENTRIES = (
    {"label": "Service Work Order…",
     "where": "New Service ribbon tab",
     "call": "app.service.workorder_ui.open_window"},
    {"label": "Service Agreements…",
     "where": "New Service ribbon tab",
     "call": "app.service.agreements_ui.open_window"},
    {"label": "Refrigerant Log…",
     "where": "New Service ribbon tab",
     "call": "app.service.refrigerant_ui.open_window"},
    {"label": "Backflow Test Report…",
     "where": "New Service ribbon tab",
     "call": "app.service.backflow_ui.open_window"},
    {"label": "Flat-Rate Pricebook…",
     "where": "New Service ribbon tab",
     "call": "app.service.pricebook_ui.open_window"},
    {"label": "Truck Stock…",
     "where": "New Service ribbon tab",
     "call": "app.service.truckstock_ui.open_window"},
    {"label": "Tech Recommendations…",
     "where": "New Service ribbon tab",
     "call": "app.service.recommend_ui.open_window"},
    {"label": "T&M Tag…",
     "where": "New Service ribbon tab",
     "call": "app.service.tmtag_ui.open_window"},
    {"label": "Build-to-Service Handover…",
     "where": "New Service ribbon tab",
     "call": "app.service.handover_ui.open_window"},
    {"label": "Dispatch Board…",
     "where": "New Service ribbon tab",
     "call": "app.service.dispatch_ui.open_window"},
)
