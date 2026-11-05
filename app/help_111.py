"""Help Center pages for QuantiSheet 1.1.1.

The lessons live in app/helpcenter.py as tut() records, and the Help
Center tree is built from the list T that those calls fill. This file
holds the 1.1.1 pages only.

Wire them with one import in app/helpcenter.py, right after the
SHORTCUTS list and before shortcuts_html():

    from . import help_111  # noqa: E402,F401  (adds the 1.1.1 pages)

Importing this module registers the pages once (register() runs at the
bottom of this file and is safe to call twice). Do not add a separate
help_111.register() call in helpcenter.py: when app.help_111 is imported
first, helpcenter would see this module before register() exists.

Show Me is left off on these pages ("try" stays empty).

In page titles and goals, "&" is written plainly: helpcenter escapes
those two fields itself. Steps and tips are HTML, so they use &amp;.
"""
from . import helpcenter

PAGE_IDS = (
    "onewindow", "firstrole", "quickbar", "rightpage", "findany",
    "chestkeys", "exportone", "comparekey", "pastetakeoff", "buyqty",
    "followtakeoff", "itemview", "editruns", "takecare",
    "svccalls", "svcagree", "svclogs", "svcprice", "svcrecords",
    "bocrews", "bocost", "boapprove", "bowaiting", "bofield",
    "safefiles", "uptodate",
)

EXTRA_SHORTCUTS = [
    ("Find a sheet, takeoff item, RFI or service record", "Ctrl+K"),
    ("Show where a command lives (in Ctrl+K)", "Shift+Enter"),
    ("The first nine Tool Chest tools", "1 through 9"),
    ("Repeat the last tool (from Select)", "Space"),
    ("Open the menus from the keyboard", "F10, or Alt on its own"),
    ("Compare", "Ctrl+Alt+C"),
    ("Arc while drawing a run or an area", "Tab"),
    ("Status of the selected markup", "Alt+1 through Alt+9"),
]

_registered = False


def register():
    """Add the 1.1.1 lessons and shortcut rows. Safe to call twice."""
    global _registered
    if _registered:
        return
    if not hasattr(helpcenter, "SHORTCUTS"):
        raise RuntimeError(
            "Call help_111.register() after helpcenter.SHORTCUTS exists.")
    _registered = True
    _add_pages()
    helpcenter.SHORTCUTS.extend(EXTRA_SHORTCUTS)


def _add_pages():
    tut = helpcenter.tut

    tut("onewindow", "Getting started", "One window, and New Window", 2,
        "QuantiSheet opens in the window you already have.",
        ["Start QuantiSheet again while it is running. The window that is "
         "already open comes forward.",
         "Open a PDF from Windows while QuantiSheet is running. It opens in "
         "that same window.",
         "When you want a second window on purpose, use File > <b>New "
         "Window</b>."],
        ["A second click on the QuantiSheet icon while it is still "
         "starting waits for the first start. It does not open a second "
         "copy."],
        practice=False)

    tut("firstrole", "Getting started", "Pick a role the first time", 2,
        "The first time QuantiSheet opens, pick the work you do most.",
        ["The first time QuantiSheet opens, it asks <b>What do you mostly "
         "do?</b>",
         "Choose <b>Estimator</b>, <b>Project Manager</b>, <b>Service</b> "
         "or <b>Office</b>. Or click <b>Skip</b>.",
         "Your choice sets the quick bar pins. It also hides tabs that role "
         "does not need: Project Manager hides Estimate, Service hides "
         "Takeoff, and Office hides Takeoff and Estimate. Estimator keeps "
         "every tab.",
         "To pick again later, use View > Ribbon Tabs > <b>Choose My Role "
         "(Estimator, PM, Service, Office)</b>."],
        ["View > Ribbon Tabs > <b>Show All Tabs</b> brings back every tab.",
         "Tabs also follow the open file. With no file open, Markup, "
         "Takeoff, Review, Pages and Document are hidden. A letter or "
         "legal size document hides Takeoff. Turn this off with View > "
         "Ribbon Tabs > <b>Tabs Follow the Open File</b>.",
         "There are fewer tabs now. Module and Billing are on the Project "
         "tab, Civil is on the Estimate tab, and the AI groups are on "
         "Takeoff, Project, Tools and Review. View > Ribbon Tabs > "
         "<b>Classic Tabs (all 14, next start)</b> brings the old tabs "
         "back the next time QuantiSheet starts.",
         "The same first screen offers a short tour, <b>Bring My Data From "
         "Another PC</b> and <b>Keyboard Shortcuts</b>.",
         "Project Center logins are a separate list. In Project Center, the "
         "project menu > Users and roles uses Admin, Project manager, "
         "Estimator, Subcontractor and Viewer on a shared project."],
        practice=False)

    tut("quickbar", "Getting started", "Quick bar pins", 2,
        "Keep the commands you use on the quick bar, in the order you want.",
        ["The quick bar is the row under the ribbon, marked <b>Quick</b>.",
         "To pin a command, right-click its ribbon button and choose "
         "<b>Pin to Quick Bar</b>.",
         "Drag a pin to reorder it.",
         "Right-click a pin for <b>Unpin From Quick Bar</b>, <b>Move "
         "Left</b>, <b>Move Right</b> or <b>Restore Default Pins</b>."],
        ["The role you pick on the first screen sets the starting pins.",
         "The Export button sits at the right end of the quick bar. See "
         "One Export button."],
        practice=False)

    tut("rightpage", "Getting started", "Right-click the page", 3,
        "The page menu holds the commands you use on the spot you clicked.",
        ["Right-click an empty spot on the page (not a markup).",
         "The menu starts with <b>Set Scale</b>, <b>Length</b>, "
         "<b>Area</b> and <b>Count</b>. When you clicked on PDF text, "
         "<b>Edit Text Here</b> edits that text in place.",
         "It also has <b>Redact Area</b>, <b>Snapshot</b> and <b>New RFI "
         "Here</b>, plus <b>Again:</b> rows for the last tools you used.",
         "Then <b>Rotate This Page</b> and <b>Insert Pages From PDF "
         "Here</b>.",
         "After you copy markups, the menu has <b>Paste Here</b> (at the "
         "spot you clicked) and <b>Paste in Place</b> (the same spot as "
         "the copy). Otherwise it has <b>Paste</b>."],
        ["Each row starts the command of the same name. A command that "
         "can't run right now is left off the menu.",
         "Snapshot: drag a box. That area is copied as a picture, ready to "
         "paste.",
         "New RFI Here starts an RFI on this sheet and opens the RFI "
         "panel.",
         "Redact Area starts the Redact tool. See Keeping files safe.",
         "Length, Area and Count are the tools in Measure by hand. Set "
         "Scale is in Set the scale."],
        practice=False)

    tut("findany", "Getting started", "Ctrl+K finds the work, and the button",
        3,
        "Search finds a sheet, a takeoff item, a Tool Chest tool, an RFI "
        "or a service record, and it shows where a button lives.",
        ["Press <b>Ctrl+K</b> (View > Command Search).",
         "Type a command, a sheet number such as A2.1, a takeoff item, a "
         "Tool Chest tool, an RFI, or a service property or piece of "
         "equipment.",
         "Each result shows what it is (for a command, its menu path) and "
         "its shortcut. Press Enter to open it.",
         "For a command, press <b>Shift+Enter</b> instead. Its ribbon tab "
         "opens and the button lights up."],
        ["A sheet opens at that page. A takeoff item goes to its markup. "
         "An RFI goes to its markup or page.",
         "A service record opens Equipment &amp; Service Records.",
         "A Tool Chest tool shows its number key, for the first nine.",
         "Ctrl+K also finds commands, as in Your first ten minutes."],
        practice=False)

    tut("chestkeys", "Getting started",
        "Number keys, Space, and menus from the keyboard", 3,
        "Run a Tool Chest tool, repeat a tool, and open the menus without "
        "the mouse.",
        ["The number keys <b>1</b> through <b>9</b> run the first nine "
         "Tool Chest tools, in the order the Tool Chest panel shows them.",
         "With the Select tool on, press <b>Space</b> to start the last "
         "takeoff or markup tool again, with the same item.",
         "Press <b>F10</b>, or press and let go of <b>Alt</b> on its own, "
         "to open the menus from the keyboard.",
         "Help > <b>Customize Shortcuts</b> lists every command. Click a "
         "shortcut and press the new keys."],
        ["Number keys don't start a tool while you are drawing.",
         "In Customize Shortcuts, a key another command had moves to the "
         "new command, and the other one is cleared. <b>Reset All</b> goes "
         "back to the built-in keys the next time QuantiSheet starts.",
         "With a markup selected, <b>Alt+1</b> through <b>Alt+9</b> set "
         "its status.",
         "Esc still returns to the Select tool, as in Your first ten "
         "minutes."],
        practice=False)

    tut("exportone", "Working together", "One Export button", 2,
        "Export from one button, which remembers what you chose last time.",
        ["The <b>Export</b> button is at the right end of the quick bar.",
         "Click its arrow to see every export command in the menus. Pick "
         "the one you want.",
         "The button then reads <b>Export:</b> and that name. Click the "
         "button itself to run the same export again."],
        ["The list is built from the export commands in the menus, so a "
         "new export shows up there on its own."],
        practice=False)

    tut("comparekey", "Markup and review", "Compare (Ctrl+Alt+C)", 2,
        "One Compare window, with the newest revision picked for you.",
        ["Press <b>Ctrl+Alt+C</b>, click <b>Compare</b> on the Home or Review "
         "tab, or use File > <b>Compare</b>.",
         "The other revision box starts with the newest PDF in the same "
         "folder whose name starts the same way. Click <b>Browse</b> to "
         "pick another.",
         "Choose <b>Overlay</b> (old in red, new in green, lined up sheet "
         "by sheet), <b>Changes</b> (changed areas outlined on the new "
         "set) or <b>Text</b> (words added and removed, as a report). "
         "Then click <b>Compare</b>."],
        ["Compare remembers the kind you used last.",
         "Overlay is the same as Compare Revisions (Overlay), Ctrl+Alt+O. "
         "The lesson Compare revisions walks through it."],
        practice=False)

    tut("pastetakeoff", "Takeoff", "Copy takeoff onto another sheet", 3,
        "Takeoff copied onto another sheet is rescaled to that sheet.",
        ["Select the measurements on the sheet you measured, then press "
         "<b>Ctrl+C</b>.",
         "Go to the other sheet and press <b>Ctrl+V</b>. The markups go in "
         "at the same spot. Or right-click the page > <b>Paste Here</b> to "
         "put them where you clicked.",
         "Each measurement is worked out again at that sheet's scale."],
        ["Set the scale on the sheet you paste onto first. A measurement "
         "pasted onto a sheet with no scale is left out, and the status "
         "bar says so. The lesson Set the scale is how.",
         "Counts, shapes, item names, colors and Tool Chest settings come "
         "along too."],
        practice=False)

    tut("buyqty", "Takeoff", "Buy quantities", 2,
        "A buy quantity is what to order, with waste, rounded up.",
        ["Takeoff > <b>Buy Quantities (Sheets, Boxes, Rolls)</b> (also Buy "
         "Qty in the Takeoff tab's Plan Set group). Each "
         "takeoff item is a row with its total.",
         "Type the <b>Size of one</b> (for example 32 for a 32 sf sheet), "
         "the <b>Buy unit</b> (sheets, boxes, rolls) and the "
         "<b>Waste %</b>.",
         "The <b>Buy</b> column is the total plus waste, divided by the "
         "size of one, rounded up to whole units. Click <b>Save</b>."],
        ["The buy rules are kept with the job, by item name.",
         "Leave Size of one blank to clear an item's rule."],
        practice=False)

    tut("followtakeoff", "Takeoff",
        "Tags and the schedule, carry forward, typical sheets", 4,
        "Check tags against the schedule, carry takeoff forward, and "
        "count a typical sheet more than once.",
        ["Review > <b>Tags vs Schedule Check</b>. Type the tags to look "
         "for, such as D-#, and click <b>Check</b>. The list shows tags "
         "that match, tags on the plans only, and tags in the schedule "
         "only.",
         "Takeoff > <b>Carry Takeoff Forward to a Revised Set</b> opens "
         "Compare Revisions. Pick the newer set, click Compare, then "
         "<b>Slip Sheet: Update This Set to the Newer Revision</b>.",
         "Takeoff > <b>Typical Sheet (Count This Sheet N Times)</b>. Type "
         "how many times this sheet's takeoff counts, such as 5 for floors "
         "2 to 6. Type 1 to count it once."],
        ["In the tag box, * is any letters, ? is one letter and # is a "
         "number. <b>Save CSV</b> saves the list. <b>Make an RFI</b> turns "
         "the gaps into an RFI.",
         "Carry forward keeps your takeoff. Takeoff in a changed area is "
         "marked \"Check - drawing revised\".",
         "A typical sheet shows a \"Typical sheet x5\" badge, and its "
         "multiplier is used in the totals."],
        practice=False)

    tut("itemview", "Takeoff", "Color by item, and show only this item", 2,
        "See takeoff in each item's color, or one item at a time.",
        ["View > <b>Color Takeoff By</b> > <b>Item</b> outlines each "
         "item's takeoff in its own color, with a legend on the page.",
         "Select a measurement, right-click it and choose <b>Show Only "
         "This Item</b>.",
         "Everything else on the sheet fades, and that item stays clear. "
         "Press <b>Esc</b> to show everything again."],
        ["Color Takeoff By can also color by <b>Status</b> or by <b>Priced "
         "/ Not Priced</b>. Choose <b>Off</b> to stop.",
         "Show Only This Item is also at Takeoff > Selected Measurement, "
         "and on the Takeoff tab as <b>Only This</b>."],
        practice=False)

    tut("editruns", "Takeoff", "Bulk edit, join, split and arcs", 3,
        "Change several measurements, join or split a run, and draw an arc.",
        ["Select the measurements, right-click and choose <b>Bulk Edit "
         "Selected</b>. Set the wall height, rise / drop, status or item "
         "name. A blank box keeps what each one has.",
         "Select runs of the same item whose ends meet, right-click and "
         "choose <b>Join Runs Into One</b>. Right-click a run at a corner "
         "and choose <b>Split Run at This Corner</b>.",
         "While you draw a run or an area, press <b>Tab</b>. Click a point "
         "on the curve, then its end. Press Tab again for straight "
         "segments."],
        ["Select several markups with Ctrl+click, or drag a box, as in "
         "Fix takeoff on the drawing.",
         "Bulk Edit Selected is also at Takeoff > Selected Measurement, and "
         "on the Takeoff tab as <b>Bulk Edit</b>.",
         "Tab only draws an arc while a run or an area is being drawn."],
        practice=False)

    tut("takecare", "Takeoff", "Cutouts counted once, and a flagged scale", 3,
        "An overlap is deducted once, and a scale read on open waits for "
        "you to confirm it.",
        ["Where two cutouts overlap, the shared part is counted once. A "
         "cutout that reaches outside its area only takes away the part "
         "inside.",
         "When a set opens with no scales, QuantiSheet reads the scale "
         "from each title block and sets the ones that read cleanly.",
         "The status bar scale then says <b>(read from title block - click "
         "to confirm)</b>. Check a known dimension, click the scale, and "
         "choose <b>Scale Looks Right (Confirm)</b>."],
        ["Cutout (Shift+X) is the deduct tool in Measure by hand.",
         "Clicking the status bar scale also offers Set Scale (Calibrate), "
         "Read Scales From Title Blocks, Show Scale and Standard Scales.",
         "Takeoff > <b>Auto Scale (Read Sheets)</b> reads the title blocks "
         "whenever you ask."],
        practice=False)

    tut("svccalls", "Service", "Calls: work orders, dispatch and T&M tags",
        6,
        "On the Service tab, Calls is the work order, the day's board and "
        "the signed time-and-material tag.",
        ["Open <b>Service Work Order</b> (Service tab, Calls group, Work "
         "Order). Type the customer, the site, the unit, the complaint and "
         "the technician, then <b>Add ticket</b>. Sites and units come "
         "from Equipment &amp; Service Records.",
         "Type hours and <b>Add time</b>. Type the part, the quantity, "
         "the cost, the price and the item number on the truck, then "
         "<b>Add part</b>. When nothing was used, click <b>No parts "
         "used</b>.",
         "To bill a flat-rate task, pick the task and <b>Customer "
         "price</b> or <b>Agreement member price</b>, then <b>Use "
         "flat-rate task</b>. <b>Use book time and parts</b> puts that "
         "task's hours and parts on the ticket when the ticket does not "
         "already have time or parts.",
         "Type notes. <b>Print work order</b> writes the PDF. <b>Close "
         "and invoice</b> needs notes, time, and parts (or No parts "
         "used). Closing writes the invoice and keeps the profit on the "
         "ticket.",
         "Open <b>Dispatch Board</b>. Unassigned tickets are on the left. "
         "Each technician is a list for the day shown. Drop a ticket on "
         "a technician to assign that day. Drop it on Unassigned to clear "
         "the technician and the day. <b>Add technician</b> adds a column. "
         "<b>Print day sheet</b> writes the day's PDF.",
         "Open <b>T&amp;M Tag</b>. Type the customer, the site and the "
         "description, then <b>New tag</b>. Add labor, material and "
         "equipment lines with <b>Add line</b>. <b>Print tag</b> writes "
         "the PDF. <b>Sign tag</b> signs it on this computer. Signing "
         "does not contact a time server."],
        ["Printed pages use the company details from Create Proposal. "
         "These windows keep their files on this computer.",
         "The Service tab groups are Calls, Agreements, Logs &amp; Tests, "
         "Pricing, Records and Quotes. The same windows are on the Service "
         "menu, and Ctrl+K finds them."],
        practice=False)

    tut("svcagree", "Service", "Agreements and the build-to-service handover",
        5,
        "An agreement is a price and a number of visits. At closeout, the "
        "equipment becomes service records, and a maintenance agreement "
        "is offered.",
        ["Open <b>Service Agreements</b> (Service tab, Agreements group). "
         "Type the customer, the site, the price, the visits per year and "
         "the renewal date (YYYY-MM-DD), then <b>Add agreement</b>. The "
         "visits box starts at 2. The list column is Visits / year.",
         "Renewal is warned at 90, 60 and 30 days, and when the date has "
         "passed. The window says when nothing renews inside 90 days.",
         "<b>Create due visits</b> opens a planned-maintenance work order "
         "for each visit that is due. Profit on the list is the agreement "
         "price minus the time and parts used on its visits. <b>Print "
         "summary</b> writes the PDF.",
         "Open <b>Build-to-Service Handover</b> at closeout (Agreements "
         "group, Handover). Type the warranty start (YYYY-MM-DD) and, if "
         "you will offer one, the agreement price. Paste one block per "
         "unit: kind, make, model, serial and warranty. O&amp;M PDFs go in "
         "the box under that, one path per line.",
         "<b>Read equipment</b> lists what it found and saves nothing. "
         "<b>Add to service records</b> adds units that have a model or a "
         "serial. The warranty start is the closeout date. <b>Accept PM "
         "agreement</b> is what saves the maintenance agreement. Until "
         "you accept it, the offer stays an offer."],
        ["Handover sits in the Agreements group because Accept PM "
         "agreement is what saves one."],
        practice=False)

    tut("svclogs", "Service", "Refrigerant log and backflow test report", 5,
        "Logs & Tests keeps the refrigerant added to a unit, and the "
        "backflow assembly test.",
        ["The unit has to be in Equipment &amp; Service Records before it "
         "can be logged. Open <b>Refrigerant Log</b> (Service tab, Logs "
         "&amp; Tests group), pick the unit, and type the refrigerant, the "
         "full charge in pounds, the kind of equipment and the charge "
         "date. <b>Add unit</b>.",
         "The kinds are industrial process refrigeration, commercial "
         "refrigeration, comfort cooling and other appliances.",
         "For a visit, type pounds added, pounds recovered, the cylinder "
         "number, the 608 certificate number, the technician and the "
         "visit date. <b>Add visit</b>. <b>Print site log</b> writes the "
         "PDF for the site.",
         "The log works out a leak rate for the year from the pounds "
         "added and the full charge. For a full charge of 50 pounds or "
         "more, the limits are 30% for industrial process refrigeration, "
         "20% for commercial refrigeration, and 10% for comfort cooling "
         "and other appliances. A unit over its limit is flagged. A "
         "smaller unit is still marked at the same percentage, and the "
         "line says the full charge is under 50 lb.",
         "Open <b>Backflow Test Report</b>. Pick the site and the device, "
         "or click <b>Fill from service record</b>. That copies the "
         "account, the device and the company phone, and sets the next "
         "test one year after the test date. Fill the readings (including "
         "Leaked, Closed tight and psi), the application, the category, "
         "the method, the test kit, the certification number and the "
         "signature. <b>Save report</b>, then <b>Print PDF</b>."],
        ["Application choices are Domestic, Fire Line, Irrigation and "
         "Other. Category is General, Limited or Inspector. Method is "
         "Direction of flow or Differential. Test kit is Vertical tube "
         "or Differential gauge. The report is this program's own page.",
         "The company name on the PDF is the one from Create Proposal. "
         "A blank company setting leaves the name off."],
        practice=False)

    tut("svcprice", "Service",
        "Flat-rate book, recommendations and truck stock", 5,
        "Pricing is the task price, the recommendation the technician "
        "writes up, and the parts on the truck.",
        ["Open <b>Flat-Rate Pricebook</b> (Service tab, Pricing group). "
         "Type a code, the task, the customer price, the member price, the "
         "hours, the labor cost and a tier, then <b>Add task</b>. A "
         "built-in part is typed as name, quantity and cost, for example "
         "capacitor, 1, 12.50. No prices ship with the program.",
         "Tiers are base, option, Good, Better and Best. <b>Option "
         "quote</b> saves a PDF of the tasks as an option quote.",
         "Open <b>Tech Recommendations</b>. Pick the unit, and type a "
         "note, a photo file, a price and a tier. You can point the line "
         "at a flat-rate task. <b>Add recommendation</b>. <b>Option quote "
         "for this unit</b> builds the customer quote from that unit's "
         "list. Each line needs a price or a pricebook task.",
         "Tiers on a recommendation are option, base, Good, Better and "
         "Best. Good, Better and Best are options the customer picks "
         "among. Option is an optional line.",
         "Open <b>Truck Stock</b>. <b>Add truck</b> with the truck name "
         "and the technician. <b>Add catalog part</b> with the part, the "
         "item number and the supplier. <b>Put on truck</b> adds the "
         "quantity. The list shows on hand and the minimum. <b>Export "
         "restock list</b> is what is under the minimum, in the same "
         "export the Material Order List already uses. A part on a work "
         "order uses the item number on the truck, and those parts come "
         "off that truck."],
        ["On the Service tab the Pricing buttons read Pricebook, Recommend "
         "and Truck Stock."],
        practice=False)

    tut("svcrecords", "Service", "Service records and quotes with options", 4,
        "Records holds the equipment. Quotes are the customer quote, "
        "including the options a technician recommended.",
        ["Open <b>Equipment &amp; Service Records</b> (Service tab, "
         "Records group, or Takeoff > Estimating Tools). Open the records "
         "file, or use the default file. <b>Add Property / Job</b>, then "
         "<b>Add Equipment</b> (make, model, serial, install date, "
         "warranty).",
         "<b>Add Recurring Service</b> (every N days, weeks, months or "
         "years). Coming due and overdue lists what to do. <b>Mark "
         "Service Done</b> moves the next due date.",
         "Work orders, the refrigerant log, the backflow report, "
         "recommendations and the handover all use these same records.",
         "Open <b>Customer Quote With Options</b> (Service tab, Quotes "
         "group, or Takeoff > Estimating Tools). It builds the quote from "
         "the priced estimate: base scope, Good / Better / Best (or your "
         "own option names), and optional lines. The customer sees prices "
         "only. A technician's Option quote for this unit is the same kind "
         "of quote, built from that unit's recommendations."],
        ["The in-window How to on each Estimating Tools page is the short "
         "version of that page.",
         "Ctrl+K finds a property or a piece of equipment by name and opens "
         "these records."],
        practice=False)

    tut("bocrews", "Back Office", "Crew board and the checklist editor", 4,
        "See who is on which job, copy yesterday's crews, and edit the "
        "QA checklists.",
        ["On the Project tab, click <b>Back Office</b> (Office group). The "
         "button shows only when Back Office is installed.",
         "Open the <b>Crew Board</b> page. Type the date, the cost code and "
         "the hours (the hours box starts at 8). Drag a crew from the left "
         "list onto a job in the right list. The board lists the crew, the "
         "job, the cost code and the hours.",
         "<b>Copy Yesterday's Crews</b> is a button on the board. It "
         "copies the most recent earlier board onto the date you are "
         "looking at. <b>Fill daily logs and time cards</b> writes each "
         "job's daily-log manpower and draft time cards. Running it "
         "again does not add a second copy. <b>Print crew board</b> "
         "writes the PDF.",
         "Open the <b>Checklist Templates</b> page. The editor is on the "
         "page: pick a checklist, or type a name. One check per line. "
         "<b>Save checklist</b> replaces that checklist's lines. "
         "<b>Delete checklist</b> hides it; the row stays. Built-in lists "
         "are seeded once."],
        ["Back Office is also on the Module menu as QuantiSheet Back "
         "Office (press F10 to reach the menus).",
         "When the last crew board is older than yesterday, that day is "
         "the one copied, and the page says which date it came from."],
        practice=False)

    tut("bocost", "Back Office", "Job cost report and duplicate invoices", 4,
        "Bring in a job cost report and publish it. A second copy of an "
        "invoice is held back unless someone records why.",
        ["Open the <b>Job Cost Report</b> page and pick the job. "
         "<b>Import Job Cost Report</b> reads a job cost report PDF. "
         "Printer files (.PRN) are refused. The report is a job, then each "
         "cost code, then lines such as Labor, Material, Subcontractor and "
         "Other, then a cost-code total.",
         "The grid shows the code, the description, the total estimate, "
         "committed, JTD cost, the variance and overrun. Overrun is a "
         "negative budget variance, or job-to-date cost over the total "
         "estimate.",
         "<b>Publish to Job Cost</b> makes the job cost view use this "
         "report for the codes it contains: budget, committed and actual. "
         "<b>Unpublish</b> puts the books figures back.",
         "On the <b>Payables</b> page, type the folder of invoice PDFs in "
         "the Invoice folder box, click <b>Use this folder</b>, then "
         "<b>Scan invoice folder</b>. A PDF whose text already has a "
         "vendor, an invoice number, a date and a total is saved as a "
         "draft. The same file is not captured twice. Files that are not "
         "PDFs are skipped. Nothing is moved or deleted out of the folder.",
         "An invoice is held back as a possible duplicate when it repeats "
         "the vendor and invoice number, or the same vendor and amount "
         "within 7 days, or the same file. Pick it under <b>Held back as "
         "possible duplicates</b> and click <b>Allow This Duplicate</b>. "
         "You are asked why. Your name and the reason are kept."],
        ["Once a folder is set, the Payables page also checks it every few "
         "seconds while it is open.",
         "Approving an invoice from Waiting on Me is a later lesson."],
        practice=False)

    tut("boapprove", "Back Office",
        "A separate approver, and the payroll key", 4,
        "The person who entered a record is not the person who approves "
        "it, unless an Admin allows that. The payroll key can be rotated "
        "and backed up.",
        ["Whoever entered an invoice or other approvable item, or coded "
         "it, cannot approve it. The program says you can't approve your "
         "own record. The same rule blocks rejecting your own record.",
         "Open the <b>Payroll Key &amp; Approvals</b> page. The "
         "<b>Self-Approval</b> button is for an Admin only. It stays off "
         "until an Admin turns it on. Changing it asks why, and that "
         "reason is kept. Every self-approval is written to the audit log "
         "with who did it.",
         "<b>Rotate Payroll Key</b> makes a new key and re-locks the "
         "payroll and HR fields already on file. The key is kept in this "
         "Windows user's profile, not in the company folder.",
         "<b>Back Up Payroll Key</b> writes a copy locked with a password "
         "you choose (10 characters or more, typed twice). The password is "
         "not stored, and the file does not hold the key in the clear. "
         "<b>Restore Payroll Key</b> puts that copy back. The key is not "
         "written to the audit log."],
        ["Back up the key again after you rotate it. Earlier keys stay on "
         "this PC, so old backups still open.",
         "If the payroll key is not on this Windows login when Back Office "
         "opens the company, it offers <b>Restore From Key Backup</b>. It "
         "never makes a new key in its place."],
        practice=False)

    tut("bowaiting", "Back Office", "Waiting on Me", 3,
        "Invoices waiting on you have their own page, and Home counts "
        "them. Approve is one click. Reject needs a reason.",
        ["Open the <b>Waiting on Me</b> page. The list is the invoices "
         "whose current step is you: AP number, vendor, invoice, job and "
         "total.",
         "Select one. The page shows the coding and the invoice text.",
         "<b>Approve</b> approves it, burns an approval stamp onto a copy "
         "of the invoice PDF (job, cost code, amount, approver and date), "
         "and remembers that vendor's job, cost code and approval path "
         "for the next invoice from them. The file that was captured is "
         "left as it was.",
         "To reject, type a reason in the box (it says a reason is "
         "required) and click <b>Reject</b>."],
        ["The separate-approver rule applies here. You can't approve "
         "your own record unless an Admin has turned on Self-Approval.",
         "The Home page shows how many items are <b>Waiting on you</b>."],
        practice=False)

    tut("bofield", "Back Office",
        "Safety meetings, incidents, pre-task plans, equipment, warranty",
        6,
        "Back Office has a page each for the safety meeting, the incident, "
        "the day's pre-task plan, equipment reminders, and warranty calls "
        "on a closed job.",
        ["<b>Safety Meetings</b>: pick a topic, type the date and the "
         "attendee, sign on the pad, then <b>Add attendee and sign</b>. "
         "<b>Sign-in sheet</b> writes the one-page PDF. Signatures stay "
         "in the company file.",
         "<b>Incidents</b>: type the kind (it starts as near miss), the "
         "date, where, the weather and what happened, then <b>Save "
         "incident</b>. Nothing is filed or sent.",
         "<b>Pre-Task Plans</b>: type the date and the job id. <b>Copy "
         "yesterday's plan</b> copies the latest plan for that job from "
         "before the date onto this date, and fills in the task, hazards "
         "and controls. Signatures are not copied.",
         "<b>Equipment</b>: <b>Show reminders</b> lists service and "
         "inspection items that are due. The reminders stay on this "
         "screen. Nothing is sent.",
         "<b>Warranty &amp; Service Calls</b> is for a job that has been "
         "closed out. Type the job id and click <b>Mark job closed</b>. "
         "Type the caller and the issue, then <b>Log call</b>. Nothing is "
         "dispatched off this computer."],
        ["Each of these is its own page in the Back Office list on the "
         "left.",
         "A warranty call needs the job closed first, and it needs a "
         "caller and the issue."],
        practice=False)

    tut("safefiles", "Working together", "Keeping files safe", 5,
        "Signatures, redaction, job data, newer files, shared files, "
        "backups, updates, the Sage export and macros.",
        ["Before a save would change a signed PDF, QuantiSheet asks first. "
         "It says whether the signatures stay valid or will not be valid "
         "in the saved file.",
         "<b>Redact Area</b> (right-click the page) removes the text, line "
         "art and picture under the box, then checks that nothing is left. "
         "After you save, the saved file is checked for the redacted "
         "words.",
         "When a PDF comes back without its QuantiSheet data (email and "
         "some PDF tools strip it), QuantiSheet offers to put back the copy "
         "this computer kept at the last save.",
         "A file saved by a newer version of QuantiSheet opens to look at, "
         "but saving is turned off so nothing in it is lost.",
         "On a shared file, when someone else has it open, the status bar "
         "names who has this file open, and on which computer. If someone "
         "else saved it after you opened it, Save offers <b>Save a "
         "Copy</b>, <b>Overwrite</b> or Cancel.",
         "Tools > <b>Back Up My QuantiSheet Data</b> and Tools > "
         "<b>Restore QuantiSheet Data From a Backup</b>. A backup also "
         "runs once a week on its own.",
         "Takeoff > <b>Export to Sage 300 Job Cost (CSV)</b> shows a "
         "preview first. It writes the import file and a reversal file "
         "next to it.",
         "Tools > <b>Macros</b> > <b>Load &amp; Replay</b> checks the macro "
         "before it runs."],
        ["If the redaction check fails, the redaction is undone and you "
         "are told.",
         "The weekly backup goes to Documents\\QuantiSheet Backups, and the "
         "last four are kept. A backup holds your signing key and Back "
         "Office data, so keep it private.",
         "The Sage export preview shows the number of lines, the job and "
         "the total, and how many lines are left out. Importing the "
         "reversal file backs the import out.",
         "A macro only replays markups. Steps it can't play here are "
         "listed first, and you choose whether to play the rest.",
         "When QuantiSheet checks for updates itself, the update "
         "information must carry a valid signature. Without one, no "
         "update is offered."],
        practice=False)

    tut("uptodate", "Getting started", "Check for updates, and About", 2,
        "Ask for an update when you want one. About shows the last check.",
        ["Help > <b>Check for Updates Now</b>. When there is nothing new, "
         "it says QuantiSheet is up to date.",
         "Help > <b>About QuantiSheet</b> shows the version, then <b>Up to "
         "date · last checked</b> and the date and time.",
         "Help > <b>Check for Updates Automatically</b> turns the "
         "automatic check on or off."],
        ["These items are on copies that check for updates. A copy that "
         "does not check shows no update line in About.",
         "Before the first check, About says not checked yet."],
        practice=False)


register()
