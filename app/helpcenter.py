"""Help Center: step-by-step tutorials, each with a Show Me button that
opens the practice drawings and starts the command it teaches.

Tutorial = {id, group, title, minutes, goal, steps, tips, try}; `try` is
a list of menu command names run in order by Show Me (practice drawings
opened first when `practice` is set). Command names are the menu texts,
so Ctrl+K finds every one of them too.
"""
import html
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSplitter, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from . import settings

T = []


def tut(id, group, title, minutes, goal, steps, tips=(), try_=(),
        practice=True, page=0):
    T.append({"id": id, "group": group, "title": title, "minutes": minutes,
              "goal": goal, "steps": list(steps), "tips": list(tips),
              "try": list(try_), "practice": practice, "page": page})


# ------------------------------------------------------------- getting started
tut("first", "Getting started", "Your first ten minutes (hands-on)", 10,
    "Do a small real job from start to finish on the practice drawings: "
    "open, scale, measure, mark up, find and save. (For a quick look at "
    "what each part of the window is, use Help > Welcome Tour instead.)",
    ["Help > <b>Open Practice Drawings</b>. A small sample set opens in its "
     "own tab - nothing you do to it matters, so try everything.",
     "Turn to the floor plan with <b>PgDn</b> (or click it in the Pages "
     "panel). Zoom with <b>Ctrl+wheel</b>; <b>Ctrl+0</b> fits the page.",
     "Check the scale chip at the bottom right. If it says no scale, click "
     "<b>Set Scale</b> on the rail, click both ends of a dimension you can "
     "read, and type its length.",
     "Measure a room: <b>Shift+A</b> (Area), click each corner, Enter to "
     "finish. The square feet show on the plan and in the Markups List.",
     "Measure a wall: <b>Shift+L</b> (Length), click both ends. Count "
     "three doors with <b>Shift+C</b>, a click on each.",
     "Cloud something: <b>C</b>, drag a box around it, then type a note in "
     "the Properties panel's Subject or Comment.",
     "Press <b>V</b> (Select) and click your area. Change its colour or "
     "label in Properties; Delete removes it, Ctrl+Z brings it back.",
     "Find a word on every sheet: <b>Ctrl+F</b>, type DOOR, Enter. Matches "
     "light up; Enter again goes to the next.",
     "Look at the <b>Markups List</b> (right side): every cloud and "
     "measurement you made, with totals. Click a row to jump to it.",
     "Save with <b>Ctrl+S</b>. Everything is kept inside the PDF, so anyone "
     "who opens it sees your markups and quantities."],
    ["Lost? <b>Ctrl+K</b> and type what you want to do.",
     "Esc always takes you back to the Select tool.",
     "AutoSave (bottom right) saves every couple of minutes; Recover Unsaved "
     "Files brings work back after a crash.",
     "Next: <i>Set the scale</i>, then <i>Measure by hand</i>, then "
     "<i>From quantities to an estimate</i>."],
    ["Open Practice Drawings"])

tut("navigate", "Getting started", "Open, view and move around", 4,
    "Zoom, pan and jump between sheets quickly.",
    ["<b>Fit Width</b> (Ctrl+2) and <b>Fit Page</b> (Ctrl+0) are on the "
     "Home tab; Ctrl+1 is actual size.",
     "Ctrl+mouse wheel zooms where the pointer is. Drag a box with the "
     "right mouse button (or press <b>Z</b>) to zoom to that box.",
     "<b>Alt+Left</b> goes back to where you were (Previous View) - "
     "after a zoom or after following a sheet link.",
     "PgDn / PgUp turn pages; scrolling past the bottom of a page turns "
     "it too. Ctrl+G goes to a page number.",
     "Click a thumbnail in the Pages panel to jump to it.",
     "Pages > <b>Link Sheet References</b> turns callouts like 3/A-501 "
     "into links: click one to jump, Alt+Left to come back."],
    ["View > Enhance Thin Lines keeps hairlines visible when zoomed out."],
    ["Fit Page"])

# ------------------------------------------------------------- editing
tut("edittext", "Editing PDFs", "Edit text and pictures on the page", 4,
    "Change words, fonts and pictures right on the page.",
    ["PDF Management tab > <b>Edit Text</b>. Every paragraph and picture "
     "gets a light outline.",
     "Click inside a paragraph and type. It keeps the paragraph's own font "
     "and wraps to its box.",
     "Use the small bar above it for font, size, <b>B</b>old, <i>I</i>talic, "
     "colour and alignment (applies to the selected words, or the whole "
     "paragraph). Ctrl+B and Ctrl+I work too.",
     "Click outside the paragraph (or Ctrl+Enter) to keep the change; Esc "
     "cancels.",
     "Double-click empty space to add new text.",
     "Click a picture to select it: drag to move, drag a corner to resize "
     "(Shift frees the proportions), arrow keys nudge, Delete removes, "
     "right-click > Replace Image.",
     "Ctrl+Z undoes any edit in one step."],
    ["Edited text stays real, searchable text."],
    ["Edit Text"], page=3)

tut("pages", "Editing PDFs", "Organize, combine and split pages", 3,
    "Put pages in order and build or break up a set.",
    ["Pages > <b>Organize Pages</b> (Ctrl+Shift+G) shows every page as a "
     "big thumbnail.",
     "Drag thumbnails to reorder. Select several with Ctrl or Shift, then "
     "Rotate, Duplicate, Delete or Reverse.",
     "Click <b>Apply</b> - the whole change is one undo step, and each "
     "sheet keeps its scale.",
     "File > <b>Combine Files</b> joins PDFs and images into one PDF; "
     "Pages > Split Document and Extract Pages break one apart.",
     "Pages > <b>Auto Bookmark Sheets</b> reads each title block and "
     "bookmarks the sheet by number and title."],
    try_=["Organize Pages"])

tut("sign", "Editing PDFs", "Forms, signatures and signing requests", 5,
    "Fill and sign forms yourself, or send a PDF out for signature.",
    ["Fill & Sign tab: <b>Signature</b>, Initials, Fill Text, Check Mark "
     "and Date - click where each goes.",
     "Document > <b>Prepare Form</b> finds the blanks in a flat form and "
     "turns them into fields.",
     "To send for signature: Document > <b>Request Signatures</b>. Add "
     "signers in order, drag signature, initials, date and text boxes "
     "onto the pages for each, and Send. Signers get an email link and sign "
     "in any browser - no account.",
     "Document > <b>Signature Requests</b> shows who has signed, sends "
     "reminders and gets the signed PDF with its certificate of "
     "completion.",
     "Owners who require DocuSign: choose it under Send with."],
    try_=["Request Signatures"], practice=False)

# ------------------------------------------------------------- markup
tut("markup", "Markup and review", "Markups, Tool Chest and the Markups "
    "List", 5, "Mark up drawings and keep track of every comment.",
    ["Markup tab: Cloud (C), Rectangle (R), Arrow (A), Text Box (T), "
     "Callout (Q), Highlight (H), Pen (P) and more. Press the letter, "
     "drag on the page.",
     "Select a markup (V, then click) to change colour, line style, hatch "
     "or layer in the Properties panel, or right-click it.",
     "Right-click a markup > <b>Add to Tool Chest</b> to reuse that exact "
     "style later with one click.",
     "The <b>Markups List</b> at the bottom lists every markup: filter, "
     "set statuses, add columns, export a summary.",
     "Right-click a markup > <b>Create RFI</b> to turn a question into a "
     "numbered RFI with the markup attached."],
    try_=["Cloud"])

tut("compare", "Markup and review", "Compare revisions", 4,
    "See exactly what changed between two issues of a drawing.",
    ["Home or Review tab > <b>Compare Revisions (Overlay)</b>; pick the "
     "older and the newer set.",
     "Sheets pair up by number and line themselves up. Red is removed, "
     "green is added, black is unchanged.",
     "Cloud Changes draws clouds around what changed.",
     "Slip Sheet puts the new sheet under your markups and takeoff; "
     "measurements on changed areas are flagged \"Check - drawing "
     "revised\".",
     "Project > <b>Batch Slip Sheet</b> does a whole set at once and logs "
     "each revision."],
    try_=["Compare Revisions (Overlay)"], practice=False)

# ------------------------------------------------------------- takeoff
tut("scale", "Takeoff", "Set the scale", 2,
    "Every measurement depends on the scale - set it first.",
    ["Takeoff tab > <b>Auto Scale (Read Sheets)</b> reads the scale "
     "printed on each sheet and sets them all.",
     "Or pick a preset from the scale box on the Takeoff tab "
     "(1/4\" = 1'-0\" ...). Takeoff > Scale Presets asks which pages: "
     "this one, every page, the pages the same size, or a list (1-4, 7).",
     "A written scale is only right on a full-size print. If the sheet "
     "says HALF SIZE, is a small sheet (11x17) or is a different size from "
     "most of the set, you are warned - check a known dimension.",
     "Or <b>Calibrate</b>: drag along a dimension you know, type its "
     "length.",
     "The status bar (bottom right) shows the scale of the page you're "
     "on.",
     "A detail at a different scale: Viewport (Scale Region) draws a box "
     "with its own scale."],
    try_=["Auto Scale (Read Sheets)"])

tut("measure", "Takeoff", "Measure by hand: length, area, count", 5,
    "Take off quantities and see them add up by group.",
    ["Type a group name in the Properties panel's <b>Subject</b> box "
     "(\"Interior Wall\", \"Carpet\") - every measurement goes into it.",
     "<b>Length</b> (Shift+L): click, click. <b>Polylength</b> (Shift+P): "
     "click each corner, double-click to finish.",
     "<b>Area</b> (Shift+A): click the corners, double-click to close. "
     "<b>Cutout</b> (Shift+X) deducts an opening.",
     "<b>Count</b> (Shift+C): click each item.",
     "Shift+F9 turns Snap on: the cursor snaps to line ends and corners.",
     "<b>Trace Length</b> (Shift+T): click a drawn line and its whole run "
     "is measured.",
     "The <b>Quantities</b> panel totals everything by group.",
     "A tool stays on after each measurement until you press Esc."],
    ["Right-click a measurement > Set Typical Count for repeated units.",
     "Takeoff > <b>Show Side Lengths</b> shows each side's length on the "
     "selected measurement or all of them (on screen only).",
     "Takeoff > <b>Captions</b>: labels show the name and quantity, the "
     "quantity only or the name only - on every page at once."],
    ["Area"])

tut("autotakeoff", "Takeoff", "Automatic takeoff: rooms, walls, doors, "
    "symbols", 5, "Let QuantiSheet measure the routine parts for you.",
    ["<b>Auto Area</b> (Shift+R): click inside a room - its floor area is "
     "traced along the walls.",
     "Takeoff > <b>Auto Takeoff Rooms on This Sheet</b> (Ctrl+Shift+R) "
     "measures every tagged room and checks each against its tag's "
     "square footage.",
     "Takeoff > <b>Auto Takeoff Walls &amp; Doors</b> (Ctrl+Shift+W) "
     "measures wall centerlines by thickness and counts doors by width.",
     "<b>Count Symbol</b>: drag a box around one symbol - every copy on "
     "the sheet (or the set) is counted, turned ones too.",
     "Takeoff > <b>Count by Label</b> finds a tag like \"WH-1\" - or a "
     "whole family with wildcards (<b>WH-#</b>) - and lists every hit "
     "before anything is counted.",
     "<b>Trace Outline</b> (Shift+O): click along an irregular slab or "
     "paving edge - each click lands on the drawn corner or edge, and the "
     "corners between two clicks on the same line are added for you "
     "(Ctrl+click for a straight cut). Area, perimeter and length show as "
     "you go.",
     "Takeoff > <b>Walls by Role</b> sorts the walls into Exterior, "
     "Corridor, Demising, Shaft, Restroom and Interior groups from the "
     "room names on the sheet; change any wall's role before adding, or "
     "later with Change Wall Role of Selection.",
     "Takeoff > <b>Count Several Symbols</b>: box one sample of each "
     "symbol, name them, Find All - one review list per symbol."],
    ["Then use Check Takeoff to look over what the automatic tools did."],
    ["Auto Takeoff Walls & Doors on This Sheet"])

tut("trades", "Takeoff", "Trade Takeoff: pipe, duct, devices, steel, "
    "roof, rebar, earthwork", 6,
    "Take off MEP, structural and site work from the drawings' own lines "
    "and tags.",
    ["Takeoff > <b>Trade Takeoff</b> (Ctrl+Alt+T). Each tab is a trade.",
     "<b>Pipe &amp; Conduit</b>: Find on This Sheet lists each line style "
     "as a system, named from tags like 4\" CW. Tick what's in scope, "
     "type over a name to rename it, Add to Takeoff.",
     "<b>Ductwork</b>: duct sizes from tags (24x12) with sheet metal and "
     "weight.",
     "<b>Fixtures &amp; Devices</b>: Count Legend Symbols counts every "
     "symbol in the legend on every sheet.",
     "<b>Structural Steel</b>: members tagged W12X26 with weight and tons.",
     "<b>Drywall &amp; Paint</b>, <b>Roofing</b>, <b>Rebar</b> and "
     "<b>Earthwork</b> work from your takeoff (walls, roof areas, "
     "footings and slabs, contours).",
     "Every result is an ordinary measurement: edit it, delete it, or "
     "Ctrl+Z the whole add."],
    ["Practice drawing P-101 has tagged pipes and a legend to try.",
     "Fire extinguishers and other life-safety symbols in a code legend "
     "are looked for on the life safety and floor plans; notes in the "
     "legend (mounting heights, egress paths) are not counted."],
    ["Trade Takeoff (Pipe, Duct, Devices, Roof, Rebar, Earthwork)"],
    page=1)

tut("check", "Takeoff", "Check Takeoff (review automatic work)", 2,
    "Look over every automatic measurement before you bid.",
    ["Takeoff > <b>Check Takeoff</b> (Ctrl+Alt+K).",
     "It zooms to each automatic measurement in turn.",
     "<b>A</b> accepts it, <b>D</b> deletes it, <b>S</b> skips. Accept "
     "Rest of Group accepts the rest of the same kind.",
     "It shows how many are checked; accepted items show as Accepted in "
     "the Markups List and Measurement Audit."],
    ["You can also decide right on the drawing: select a dashed AI markup "
     "(or several) and press <b>A</b> to accept or <b>D</b> to deny.",
     "After AI Takeoff, its <b>Review Queue</b> lists everything still "
     "waiting, least sure first."],
    try_=["Check Takeoff"])

tut("fixtakeoff", "Takeoff", "Fix takeoff on the drawing: reshape, "
    "select several, accept", 4,
    "Correct an outline that is nearly right instead of redrawing it, and "
    "clean up many markups at once.",
    ["Press <b>V</b> (Select) and click an area or a line. Small square "
     "handles appear on its corners.",
     "<b>Drag a corner</b> to move it. <b>Drag the dot in the middle of a "
     "side</b> to add a corner there. <b>Ctrl+click a corner</b> to remove "
     "it. The quantity and its label follow as you go; Ctrl+Z undoes it.",
     "<b>Select several:</b> drag a box on empty space, or Ctrl+click "
     "markups one by one. The status bar shows their combined total.",
     "Right-click the selection: <b>Move Selected to Item</b> (put them "
     "under another takeoff item), Status, or <b>Delete</b> them together.",
     "AI work is dashed with a small \"AI\" badge until someone accepts "
     "it. Select it and press <b>A</b> to accept (it turns solid and joins "
     "the totals) or <b>D</b> to deny (deleted). Right-click works too.",
     "The Markups List's <b>Origin</b> column tells them apart: manual, "
     "AI not checked, AI accepted, or <b>AI, edited</b> - an AI outline a "
     "person reshaped."],
    ["Reshaping keeps the markup's status, colour and typical count.",
     "Renaming an AI item, or moving its pieces to your own item, teaches "
     "AI Takeoff your name for next time (Takeoff > Item Names Learned)."],
    try_=["Area"])

tut("missedcounts", "Takeoff", "Find missed counts and reuse your symbols",
    4, "Make sure nothing was missed, and stop boxing the same symbols on "
    "every job.",
    ["Count a symbol with <b>Count Symbol</b> (box one copy). Its picture "
     "is kept in the PDF.",
     "Right-click one of its counts > <b>Show Uncounted Copies of …</b>: "
     "copies on this sheet with no count mark are outlined in orange. "
     "<b>Count the Uncounted Copies</b> adds them in one step.",
     "Found one the AI missed? In the <b>Review Queue</b>, click Report "
     "Missed, then box one copy on the drawing - the copies like it come "
     "in as dashed counts in review, out of the totals until you accept "
     "them.",
     "Right-click a count > <b>Add … to the Count Library</b> to keep its "
     "symbol for every job.",
     "On the next plan set: Takeoff > <b>Try the Count Library</b>. Tick "
     "the symbols and pages, Find - what it finds comes in as counts in "
     "review, and copies already counted are left alone.",
     "With the price database on a shared folder, the library sits beside "
     "it and the whole office shares one."],
    ["Counting by picture can be turned off (setting picture_count); these "
     "tools then say so instead of guessing.",
     "Title blocks, schedules, legends and notes are left out of library "
     "counts automatically."],
    try_=["Count Symbol"])

tut("countlabel", "Takeoff", "Count by Label: tags and tag families", 3,
    "Count tags such as P-1, WH-2 or EF-1 - and see every hit before "
    "anything is counted.",
    ["Takeoff > <b>Count by Label</b>. Type the tag and press Find.",
     "Wildcards for a family: <b>#</b> a number (P-# finds P-1 … P-12), "
     "<b>?</b> one letter (D? finds D1 and DA, not D10), <b>*</b> any "
     "letters (WH-* finds WH-2 and WH-2B).",
     "Hits are grouped by tag. Ones in the title block, a schedule, a "
     "legend or notes are listed but not ticked. Untick anything wrong; "
     "double-click a hit to go to its page.",
     "Choose <b>One item per tag</b> (P-1, P-2 … as separate items) or "
     "<b>All as one item</b> with a name you type, then <b>Count</b>.",
     "Without a wildcard a tag matches whole words only - D1 is not D10."],
    ["Scanned sheets are searched with OCR when it is installed."],
    try_=["Count by Label"])

tut("walls", "Takeoff", "Wall areas, rise/drop, convert and copies", 4,
    "Get drywall and paint areas, vertical runs and repeated items without "
    "redrawing anything.",
    ["<b>Wall Area</b> (Shift+W): click along the wall, double-click, then "
     "type its height (9') and any openings (3x7 x2, 6x4). The quantity "
     "is length x height less the openings, in square feet.",
     "Right-click any run > <b>Wall Height and Openings</b> turns it into "
     "a wall area (height 0 turns it back into a length).",
     "Right-click a run > <b>Rise / Drop</b> adds vertical length - conduit "
     "dropping 8' to a switch measures plan length + 8'.",
     "Right-click a measurement > <b>Convert To</b>: an area's outline "
     "becomes its perimeter, a run becomes an area, volume or wall area - "
     "the same points, name and color. (After Auto Area this gives the "
     "room's perimeter or volume.)",
     "Right-click a volume > <b>Show Volume In</b> cu ft, cu yd or cu in.",
     "Right-click a markup > <b>Copy Several Times</b>: how many, how far "
     "apart and which way. The copies are shown dashed while you choose.",
     "Right-click a count > <b>Add More to</b> it: the Count tool comes on "
     "with that name and color, numbering after the ones already there."],
    ["Reshaping a wall keeps its height and openings; the area follows.",
     "Proposals list wall heights and rise/drop allowances under "
     "Qualifications."],
    try_=["Wall Area (Length x Height)"])

tut("toolsets", "Takeoff", "Tool sets, legends and the takeoff standard", 4,
    "Give the whole team the same tools, a legend that keeps itself up to "
    "date and one way of doing takeoff.",
    ["Tool Chest > <b>Tool Sets</b> > New Set. Right-click a markup on the "
     "page > Add to Tool Chest, then right-click the tool > <b>Edit</b>: "
     "unit cost, column values (Product = Type X), the unit it keeps "
     "(metric), rise/drop, wall height, volume depth.",
     "Tool Chest > Tool Sets > <b>Save Sets as a File</b>. Others "
     "double-click the .qstools file (or Open a Tool Set File) and get the "
     "same sets, statuses and Markups List columns. A set of the same name "
     "is replaced, so everyone stays the same.",
     "The <b>Takeoff (Metric)</b> set keeps quantities in m, m\u00b2 and "
     "m\u00b3 even on a sheet scaled in feet.",
     "A tool with a unit cost adds Unit Cost and Total Cost (Value x Unit "
     "Cost) columns to the Markups List.",
     "Draw a <b>Legend</b> (Markup tab): choose this page or every page, "
     "only the items of one or more tool sets (unused ones show 0), keep it "
     "up to date, and show how many markups.",
     "Takeoff > <b>Takeoff Standard</b>: the office's steps - setup, "
     "columns, tools, takeoff, legends, revisions, update, report. Steps "
     "the drawing shows are ticked for you; add your own steps."],
    ["Restore Default Tools (Tool Sets menu) brings back any default tool "
     "or set you removed, including the metric set."],
    try_=["Takeoff Standard"])

# ------------------------------------------------------------- AI
tut("aisetup", "AI tools", "Set up the local AI (optional)", 3,
    "The AI helpers run on this PC only. Nothing is sent to the internet. "
    "Everything else in QuantiSheet works without them.",
    ["Install Ollama, the free program that runs AI models on your own PC "
     "(your IT person can do this; it needs about 4 GB of disk).",
     "Start it, then open a Command Prompt and type <b>ollama pull "
     "llama3.2</b> to download the model QuantiSheet uses.",
     "Back in QuantiSheet, try an AI command again. If the PC is slow (no "
     "graphics card), the first answer can take a minute while the model "
     "loads; it stays loaded for 30 minutes."],
    ["When Ollama isn't installed or running, or the model is missing, "
     "QuantiSheet says so in one line and carries on - nothing waits for it.",
     "Your administrator can turn the AI off for everyone (DisableAI)."],
    practice=False)

tut("aitakeoff", "AI tools", "AI Takeoff: a whole plan set in one go", 4,
    "Let QuantiSheet read every sheet and take off what it can - then "
    "check it.",
    ["Open the plan set and click the <b>AI</b> tab > <b>AI Takeoff</b> "
     "(Ctrl+Shift+A).",
     "<b>1. Read the Set</b>: every sheet's number, title, discipline and "
     "scale are read. Details, sections and schedules are skipped; sheets "
     "with no usable scale are listed - set those with Auto Scale or "
     "Calibrate and read again.",
     "Untick any sheet you don't want, then <b>2. Run AI Takeoff</b>: "
     "rooms on floor plans; pipe by size and depth, manholes and "
     "structures on civil sheets; pipe runs and legend fixtures on MEP "
     "sheets.",
     "Read the summary - totals and anything that needs a person. AI "
     "marks are dashed with an \"AI\" badge, and anything it wasn't sure "
     "of stays out of every total until you accept it.",
     "Click <b>Review Queue</b>: everything still waiting, least sure "
     "first - Accept, Deny, Undo, Report Missed. Or decide on the drawing: "
     "select a dashed markup and press <b>A</b> or <b>D</b>. Ctrl+Z takes "
     "the whole run off again.",
     "Each sheet's scale gets a confidence score and a picture of the "
     "printed scale; a doubtful one is held until you confirm it.",
     "Run it again after changes: what's already on the drawing (accepted, "
     "in review or measured by hand) is never added twice, and your "
     "earlier decisions are kept.",
     "With the local AI model installed (Ollama), <b>Write Scope "
     "Summary</b> drafts a scope narrative from the sheets and "
     "quantities."],
    ["Everything is an ordinary measurement marked \"AI takeoff\" - "
     "estimates, exports and the audit trail treat it like hand takeoff.",
     "The bid check warns while AI items are still waiting for review, so "
     "a bid can't go out short without you knowing.",
     "Nothing leaves your computer: the takeoff runs locally. (If "
     "QUANTISHEET_OLLAMA_HOST is set to another computer, the AI text "
     "features send the prompt and sheet text there - keep it on your "
     "own network.)"],
    ["AI Takeoff (Whole Set)"])

tut("aizones", "AI tools", "AI Takeoff zones and the names it learns", 3,
    "Tell AI Takeoff where to work on a sheet, and have it use your item "
    "names.",
    ["AI tab > <b>AI Takeoff Zones</b> > <b>Draw a Zone: Only Here</b>, "
     "then drag a box: a green dashed zone. With one or more on a sheet, "
     "AI Takeoff keeps only what it finds inside them (one wing, one "
     "phase).",
     "<b>Draw a Zone: Leave Out</b> draws a red zone: nothing it finds "
     "inside is added (an area by others, a legend it read as plan).",
     "Zones are ordinary markups - move, delete, or AI Takeoff Zones > "
     "<b>Clear Zones on This Page</b>. Results are kept or left out whole "
     "by where they sit; nothing is cut at a zone's edge.",
     "Rename an item AI Takeoff made (Takeoff panel > Rename), or move its "
     "pieces to your own item - the next AI Takeoff uses your name "
     "straight away.",
     "Rooms are matched without their number: renaming OFFICE 101 to "
     "\"Office - ACT\" names every office. Keep the number in your name "
     "(\"Office 101 (carpet)\") and each room keeps its own.",
     "Takeoff > <b>Item Names Learned</b> lists every pair; forget one, or "
     "turn the renaming off."],
    ["The summary says how many results your zones left out and how many "
     "names were applied.",
     "With the price database on a shared folder, the office learns names "
     "together."],
    ["Draw a Zone: Only Here"])

tut("civil", "AI tools", "Civil and sewer takeoff: pipe, manholes, depth",
    4,
    "Take off a sewer, storm or water plan by size and depth, priced with "
    "trench assemblies.",
    ["Set the sheet's scale (Auto Scale reads 1\" = 40' from the title "
     "block).",
     "Takeoff > <b>Trade Takeoff</b> > <b>Civil &amp; Utilities</b> > Find "
     "(tick Every sheet with a scale for the whole set).",
     "Pipe is traced along its line and named from its label (8\" PVC "
     "SDR-35); lengths run manhole centre to centre. Profiles are left "
     "out so nothing is counted twice; existing pipe isn't ticked.",
     "Manholes, cleanouts, inlets and valves are counted once each by tag "
     "(MH-12), with depth from their RIM and INV callouts.",
     "Each pipe size is split into depth bands (0-6, 6-10, 10-14 ft...) "
     "and gets a trench assembly with D and H filled in: excavation, "
     "bedding, backfill, haul-off and shoring. Add Trench pavement "
     "restoration or dewatering assemblies where they apply."],
    ["The Check column compares traced length with the LF written in the "
     "labels."],
    ["Trade Takeoff (Pipe, Duct, Devices, Roof, Rebar, Earthwork)"])

tut("voice", "AI tools", "Voice commands", 2,
    "Drive QuantiSheet hands-free.",
    ["AI tab > <b>Voice</b> (Ctrl+Shift+V) turns listening on; the button "
     "stays lit while it listens.",
     "Say a command: <i>next page</i>, <i>go to page twelve</i>, <i>go to "
     "sheet C two oh one</i>, <i>zoom in</i>, <i>zoom to two hundred "
     "percent</i>, <i>fit width</i>, <i>measure length</i>, <i>count</i>, "
     "<i>auto scale</i>, <i>AI takeoff</i>, <i>check takeoff</i>, "
     "<i>search for digester</i>, <i>undo</i>, <i>save</i>.",
     "What was heard shows in the status bar. Say <i>stop listening</i> "
     "or press Ctrl+Shift+V again to turn it off."],
    ["It uses Windows' own speech recognition: offline, private, no "
     "account. A headset microphone works best in a noisy office."],
    ["Voice Commands"], practice=False)

# ------------------------------------------------------------- estimating
tut("estimate", "Estimating", "From quantities to an estimate", 6,
    "Price your takeoff with assemblies, a cost book and crews.",
    ["Estimate tab > <b>Assembly Library</b>: pick an assembly (strip "
     "footing, metal stud wall, TPO roof ...) for each takeoff group.",
     "Assemblies turn quantities into materials, labor and equipment with "
     "formulas you can edit.",
     "<b>Cost Books</b> holds your prices; <b>Labor Rates &amp; Crews</b> "
     "your crews and burden.",
     "The <b>Estimate</b> panel shows the priced lines; Export Assembly "
     "Estimate makes an Excel workbook.",
     "<b>Link Quantities to Excel</b> keeps a workbook updated as the "
     "takeoff changes.",
     "<b>Bid Build-up</b> adds overhead, profit, bond and markups; "
     "<b>Create Proposal</b> makes the client PDF.",
     "On the proposal's Scope &amp; Terms tab, <b>Qualifications</b> can "
     "list what the takeoff assumed (AI items not checked and left out, "
     "wall heights, rise/drop allowances, typical units), and a rough "
     "schedule from the estimate's labor hours and your crew size."],
    try_=["Assembly Library"], practice=False)

tut("bidding", "Estimating", "Bid tabs and bid leveling", 4,
    "Compare subcontractor bids line by line.",
    ["Estimate > <b>Bid Tabs</b> shows unit prices from public bids "
     "(low, median, high).",
     "Estimate > <b>Bid Leveling</b>: enter each sub's bid and scope; "
     "omissions are filled with your own number so totals compare fairly.",
     "Carries and buy-ins are listed for the award.",
     "Estimate > <b>Scope Sheets</b>: your Scope Sheet for one trade at a "
     "time - budget (Qty x Unit $), each bidder's company, bid price, "
     "YES/NO checklist and scope amounts, TOTAL PRICE and a Math Check "
     "that turns red when a sub's lines don't add up to the price. Type "
     "amounts like 1,250 or (500); paste blocks straight from Excel; "
     "export the workbook with live formulas or a PDF for the owner.",
     "Project Center > Bid Packages sends invitations and collects bids "
     "online."],
    try_=["Bid Leveling"], practice=False)

tut("precon", "Estimating", "Bid management: invite, prequalify, open, "
    "level, award", 6,
    "Run a bid day from your Company Directory to the award letters.",
    ["Project Center > <b>Company Directory</b>: star your favorite subs, "
     "record certifications (MBE, WBE, DBE...), insurance dates and bonding. "
     "Expiring insurance and prequalification are flagged at the top.",
     "<b>Send Prequal Form</b> emails a fillable PDF; when it comes back, "
     "<b>Read Returned Prequal</b> scores it (EMR, years, safety, bonding, "
     "history) and you approve it with a dollar limit.",
     "In a Bid Package, <b>Add Bidders from Company Directory</b> can take "
     "only prequalified subs or your favorites. Set <b>Sealed bids</b> to "
     "keep every number hidden until the due time.",
     "After the deadline, <b>Open Sealed Bids</b>; then <b>Level Bids</b>. "
     "In the leveling window right-click a cell to plug a missing item, "
     "mark it included or correct a price; right-click a bidder for an "
     "adjustment. Plugs are saved on the package.",
     "<b>Award</b> makes the draft subcontract and award / regret letters "
     "(PDFs on the package - open them to edit), then <b>Send Award "
     "Letters</b>. <b>Bidding Reports</b> exports package status, bidder "
     "coverage, buyout against budget and bidder history."],
    ["Your Company Directory stays on this computer - it's never part of a "
     "shared project or an installer.",
     "The relay won't open a sealed bid before the due time, and the "
     "opening is logged."],
    practice=False)

tut("prebid", "Estimating", "Pre-bid checklist: nothing missed before "
    "you lock", 5,
    "Make sure every sheet, markup and revision is accounted for before "
    "the bid goes out.",
    ["Estimate > <b>Pre-bid Checklist</b>: three checks - sheets reviewed, "
     "markups priced / excluded / RFI, revision clouds accounted for.",
     "Right-click any markup on the drawing > <b>Pre-bid Scope</b>: Priced,"
     " <b>Link to Estimate Line</b> (it stays priced only while that line "
     "is in the estimate), Excluded (with a reason) or Sent as an RFI "
     "(logs the RFI too).",
     "Takeoff > <b>Show Unpriced Markups</b> outlines everything still "
     "open in red.",
     "Compare Revisions > Cloud clouds only the changes your takeoff "
     "doesn't cover yet; decisions carry to the new set, and anything on a "
     "changed area goes back to open.",
     "<b>Missed-Item Report</b> (Excel/PDF), <b>Print One Page</b> for the "
     "bid file, then <b>Lock Bid</b> - it records the total and the "
     "estimate as bid."],
    ["Create Proposal warns you when the bid isn't locked.",
     "Command line: quantisheet prebid FILE.pdf (exit code 0 = ready)."],
    practice=False)

tut("jobcost", "Estimating", "Job cost feedback: price from what jobs "
    "really cost", 4,
    "Feed actual costs back into your cost book.",
    ["Estimate > <b>Job Cost Feedback</b> > <b>Add This PDF's Bid as a "
     "Job</b> (uses the estimate saved when you locked the bid).",
     "Bring in the actual costs: <b>Actuals from Project Center</b> (direct "
     "costs - enter the quantity installed for unit costs) or <b>Import "
     "Actual Costs (CSV)</b> from QuickBooks or Sage.",
     "<b>Bid vs Actual</b> shows every cost code; over 10% off is red.",
     "<b>Close Job</b> records its unit costs. <b>Suggested Prices</b> "
     "shows a weighted median of your recent jobs next to the book price - "
     "tick the ones you agree with and <b>Apply</b>. The change is logged "
     "with who, when and which job."],
    practice=False)

tut("civilest", "Estimating", "Civil estimate: crews, production and the "
    "owner's bid schedule", 6,
    "Price heavy civil work the way it's built, then fill in the owner's "
    "unit-price schedule.",
    ["On the <b>Civil</b> tab, set up <b>Equipment</b> (own or rent, fuel), "
     "<b>Labor</b> (base, fringe, taxes, comp) and <b>Crews</b>. The "
     "starting rates are samples - replace them with yours.",
     "<b>Crew Estimate</b> > <b>Add From Takeoff Group</b>: pick a crew and "
     "a production rate (per hour or per day). Crew hours = quantity / "
     "rate; add material $/unit or a sub price.",
     "Add <b>Indirects</b> (super, trailer, traffic control...) by week, "
     "month or lump sum, and markup and bond on the Bid Schedule tab.",
     "<b>Import Owner Bid Schedule</b> (CSV or Excel), type each activity's "
     "pay item, and the indirects and markup spread over the items. A "
     "weight above 1 front-loads an item. Quantities 10% off the owner's "
     "are red. <b>Export Priced Bid Schedule</b> when you're done.",
     "<b>Haul Calculator</b> works out trucks, hours and $/bank CY; "
     "<b>Import Prevailing Wages</b> replaces base and fringe from a wage "
     "determination CSV; <b>Save Bid Version</b> and compare two.",
     "<b>Quotes</b> holds each vendor's and sub's price per activity (the "
     "lowest is used unless you pick another); <b>Crew Schedule</b> chains "
     "activities by crew days and sets the job length for indirects; "
     "<b>Resources</b> totals hours by labor class and equipment; "
     "<b>Export Cash Flow</b> spreads the bid by month.",
     "<b>Save to Library</b> keeps an activity's crew, production and "
     "materials for the next bid (<b>Add From Library</b>); <b>Save "
     "Estimate as Master</b> keeps the whole estimate, and <b>Start From "
     "Master</b> rebuilds it with quantities from takeoff groups of the "
     "same name.",
     "While the job runs, the <b>Forecast</b> tab (Civil > Cost to "
     "Complete) compares the budget with the project's time cards and "
     "costs: % done, earned hours, productivity and projected final cost "
     "by cost code.",
     "In the field, foremen fill in <b>Time</b> on the phone page: crew "
     "hours, equipment hours and quantities by cost code. A PM approves "
     "them; <b>Production History</b> then suggests rates and Job Cost "
     "Feedback picks up the actual costs."],
    practice=False)

tut("logins", "Project management", "Logins and roles on a shared project",
    3, "Give each person their own login and only the access they need.",
    ["Share the project (Project Center > Share), then project menu > "
     "<b>Users and roles</b> > <b>Turn On Logins</b> - your own login comes "
     "first, as admin.",
     "<b>Add Login</b> for each person: Admin, Project manager, Estimator, "
     "Subcontractor or Viewer. Send them the project name, relay address "
     "and the password shown.",
     "They open the project with their email and password (desktop: Share "
     "dialog; phone: the project page). The shared project password stops "
     "working.",
     "Every record and the activity log show who really made each change. "
     "A viewer can read but not change anything; a sub changes only their "
     "own items or ones assigned to them."],
    practice=False)

# ------------------------------------------------------------- project
tut("project", "Project management", "Project Center: RFIs, submittals, "
    "punch, daily logs", 6,
    "Run the job after the bid - everyone on one shared list.",
    ["Project > <b>Project Center</b> (Ctrl+Shift+P); open or create the "
     "job folder.",
     "Left side: Home (what's waiting on you), then each tool - RFIs, "
     "Submittals, Punch List, Daily Log, Meetings and more.",
     "<b>+ New</b> on any list; fill the few fields shown, Create. The "
     "number is given for you (RFI-007).",
     "Buttons on each item move it along: Send RFI, Close with Response, "
     "Send for Review ... and email through Outlook.",
     "<b>Ball in court</b> shows who has to act next.",
     "Share (top right) puts the project on your server so the team and "
     "the phone page see the same lists.",
     "Ctrl+K inside Project Center jumps to any item by number."],
    try_=["Project Center"], practice=False)

tut("schedule", "Project management", "Schedule, Gantt and lookaheads", 5,
    "Build a critical-path schedule and print a 3-week lookahead.",
    ["Project Center > <b>Schedule</b> > + New: name, duration in "
     "workdays, and predecessors (activity numbers; FS unless you type "
     "SS, FF or SF, with a lag).",
     "<b>Gantt Chart</b> shows the critical path in red. Drag a bar to "
     "move it, drag its end to change the duration.",
     "<b>3-Week Lookahead</b> makes the PDF for the field meeting.",
     "More > Set Baseline saves today's dates; late work shows behind "
     "baseline.",
     "More > Import from Microsoft Project (XML) or Primavera P6 (XER), "
     "and Export back to MS Project.",
     "On an activity: Started Today / Finished Today record actual dates."],
    try_=["Project Center"], practice=False)

tut("calendar", "Project management", "Project Calendar: the job by "
    "month or week", 3,
    "See everything dated on the job in one place, and move meetings, "
    "inspections and deliveries by dragging.",
    ["Project Center > Project > <b>Calendar</b>. Month view opens on "
     "today; the arrows step months, <b>Week</b> shows one week.",
     "It shows schedule activities and milestones (critical-path items "
     "marked ●), inspections, meetings and expected deliveries. Tick "
     "the boxes at the top to show or hide each kind.",
     "Drag a meeting, inspection or delivery to another day to move it.",
     "Drag across days (or double-click a day) to add a meeting or an "
     "inspection on that day.",
     "Click anything to open it. Schedule activities open the Gantt chart: "
     "they move there, where their links and float are shown."],
    ["A delivery marked delivered drops off the calendar."],
    try_=["Project Center"], practice=False)

tut("master", "Project management", "Master Schedule: monthly sub "
    "updates", 8,
    "Keep the master schedule current from each subcontractor's monthly "
    "update, seeing the impact of every change before it goes in.",
    ["Set it up once: Module > <b>Master Schedule (Sub Updates)</b> > "
     "Settings. Pick the inbox folder (a shared folder with one subfolder "
     "per sub) and the update day (last Thursday of the month unless you "
     "change it). Assign subs gives each activity its owning sub.",
     "Each cycle, <b>Prepare update packets</b> writes every sub an Excel "
     "update sheet with only their activities (other trades' activities "
     "around them shown locked) and a reminder e-mail draft.",
     "Subs send back the Excel sheet, an MS Project XML or P6 XER file, or "
     "the schedule printed to PDF. Files in the inbox are picked up "
     "every minute; Add submission takes one by hand.",
     "A file with any error is <b>Rejected</b> with every reason listed - "
     "nothing from it is applied. A .mpp file is rejected with a note: in "
     "MS Project use File > Save As > XML (or print to PDF).",
     "Progress-only updates (%, actual dates, notes) that move nothing "
     "later are accepted on their own. Everything else waits in the "
     "<b>Review queue</b> with what changed and its impact on the finish "
     "date and Substantial Completion.",
     "<b>Before / after</b> shows the bars the update moves. <b>Approve</b> "
     "takes it all; <b>Approve lines</b> takes only the activities you "
     "tick; <b>Edit and approve</b> lets you change values first; "
     "<b>Decline</b> asks for a reason. Approved updates can be reverted.",
     "Rows the program can't match to a master activity: <b>Map rows</b> "
     "once - the mapping is remembered for later cycles.",
     "An approved update that made work finish later: <b>To Delay Log</b> "
     "makes an Open delay entry listing each activity and its added "
     "workdays - check the cause and responsibility.",
     "Baseline tab: <b>Lock baseline</b> stops Set Baseline overwriting it; "
     "Re-baseline makes a new one on purpose."],
    ["E-mails are only ever drafts - nothing is sent.",
     "A PDF printout has no % complete or logic: % is worked out from the "
     "original and remaining durations, and a PDF update always waits for "
     "your review.",
     "Edit a template and it is rejected: each sheet is signed."],
    practice=False)

tut("cost", "Project management", "Cost, pay apps and cash flow", 6,
    "Track budget, commitments, changes and billing.",
    ["Project Center > Cost: <b>Budget</b> by cost code, <b>Prime "
     "Contract</b> schedule of values, <b>Commitments</b> for subs and "
     "POs.",
     "<b>Change Events</b> carry cost and price; approved ones flow to the "
     "budget and the contract.",
     "<b>Direct Costs &amp; Invoices</b>: Approve, then Mark Paid. "
     "Missing insurance, license, W-9 or lien waiver is flagged first.",
     "<b>Owner Pay Apps</b> fill from the contract and print the application for payment.",
     "<b>Cost Summary</b> and <b>Forecast</b> show margin and forecast at "
     "completion; <b>Cash Flow</b> spreads the budget over the schedule.",
     "Cost Summary > Export for Sage 300 writes the import file."],
    try_=["Project Center"], practice=False)

# ------------------------------------------------------------- safety
tut("collab", "Working together", "Live collaboration", 3,
    "Mark up the same drawing with others at the same time.",
    ["Tools > <b>Live Collaboration</b>: Start a session and share the "
     "code, or Join with a code.",
     "Everyone sees each other's markups and cursors as they work.",
     "The relay runs on one office PC (Start Relay) or on a hosted server "
     "for people outside the office."],
    try_=["Live Collaboration"], practice=False)

tut("autosave", "Working together", "AutoSave, recovery and versions", 2,
    "Never lose work.",
    ["AutoSave (status bar, bottom right) saves your open files every "
     "couple of minutes. Click it to change how often or turn it off.",
     "A file that can't be saved where it is (new, read-only) gets a "
     "recovery copy instead.",
     "If QuantiSheet closes unexpectedly, the next start offers to recover "
     "your work - or File > Recover Unsaved Files.",
     "File > <b>Version History</b> lists earlier saved versions to "
     "compare or restore."],
    try_=["AutoSave"], practice=False)


tut("genset", "Getting started", "Generate a starter set", 3,
    "Turn a short brief into a ten-sheet starter set: cover, notes, site "
    "plan, floor plan, roof plan, elevations, section, schedules and a "
    "quantity summary for the estimate (eleven sheets for a two-story "
    "house: a plan for each floor). The quantities are also saved as a "
    ".quantities.csv beside the PDF, and they travel inside the PDF: open "
    "it and the Quantities panel lists them as Set lines, ready for a unit "
    "cost and waste.",
    ["File > <b>Generate Set…</b> (or Project > More > Generate Set).",
     "Type a brief such as <i>3 bed 2 bath ranch, about 1,600 sf, new</i>. "
     "The fields below the brief win over the brief: building type, new or "
     "existing, gross area (400 - 8,000 SF), occupancy label, name, address "
     "and firm.",
     "A sketch (PDF or image) is optional; v1 reads only its outline "
     "proportions and any typed room names.",
     "Add <i>2-car garage</i> (or 1- / 3-car) for an attached garage beside "
     "the house, with its own door into the kitchen, laundry or a hall; "
     "<i>covered porch</i> and <i>rear deck</i> add those too.",
     "Write <i>two story</i> (or pick Stories: 2) for a two-story house: a "
     "center stair hall, living rooms downstairs, bedrooms upstairs. Add "
     "the lot (<i>lot 80 x 120</i>, <i>setbacks 25 front, 10 side</i>) for "
     "the site plan; anything missing is marked ASSUMED.",
     "Pick where to save. The set opens when it is done, with the plan "
     "data saved next to it (.genset.json).",
     "Every sheet says <b>FOR REVIEW - NOT FOR SEALING</b>. It is a "
     "starting point for a licensed design professional, not a permit set."],
    tips=["One-story rectangles only in v1.",
          "Warnings (missing windows, multi-story briefs, AI not running) "
          "are listed on the cover sheet."],
    try_=["Generate Set"], practice=False)


# ------------------------------------------------------------- more lessons
tut("bigsets", "Getting started", "Big plan sets: find, jump and stay fast",
    4, "Work smoothly in a 300- or 800-sheet set.",
    ["Open the set as usual. Sheets ahead of you are drawn in the "
     "background, so paging with <b>PgDn</b> doesn't wait.",
     "<b>Ctrl+G</b> jumps straight to a page; a sheet that wasn't drawn "
     "yet shows at once and fills in a moment later.",
     "<b>Ctrl+F</b> finds text across the whole set. The first match shows "
     "right away and the rest are found a few sheets at a time - the bar "
     "says how far it has got. Typing something new starts over.",
     "Pages > <b>Auto Bookmark Sheets</b> bookmarks every sheet by number "
     "and title from its title block; then the Bookmarks panel is your "
     "sheet index.",
     "Pages > <b>Link Sheet References</b> turns callouts like 5/A-501 into "
     "links. Click to jump; <b>Alt+Left</b> comes back.",
     "Snap to lines turns on in the background on dense sheets - you can "
     "start measuring straight away (<b>Shift+F9</b> turns snap on or off)."],
    ["Use File > <b>Open Project Folder</b> to list every PDF of a job in "
     "the Documents panel; page counts fill in without slowing you down.",
     "If the window ever stops responding for 10 seconds, QuantiSheet writes "
     "what it was doing to crash.log in your .quantisheet folder - send it "
     "to Jon."],
    ["Find…"])

tut("sets", "Getting started", "Sets, revisions and slip sheets", 5,
    "Keep the current drawings together as revisions come in.",
    ["Project tab > <b>New Set From Files</b>: pick the PDFs of a job; they "
     "become one set with a sheet list.",
     "When a revision or addendum arrives: <b>Batch Slip Sheet</b> matches "
     "the new sheets to the old by sheet number and swaps them in. Your "
     "markups and takeoff carry over to the new sheet.",
     "Nothing is dropped silently: sheets that couldn't be matched are "
     "listed for you to place by hand.",
     "File > <b>Compare Revisions (Overlay)</b> shows old and new in two "
     "colours and clouds the changes; <b>Revision Changes (Old → New)</b> "
     "lists what changed in quantities and dollars.",
     "Project > <b>Drawing Register</b> keeps the current revision of every "
     "sheet; <b>Transmittals</b> records what was sent to whom."],
    ["Open a set any time with Project > Open Set; the Sets panel on the "
     "left lists its sheets."],
    ["Batch Slip Sheet…"], practice=False)

tut("aerial", "Takeoff", "Aerial photo takeoff (paving, grading, "
    "sitework)", 4, "Measure a site from a free aerial photo.",
    ["Civil tab > Takeoff > <b>Aerial Photo Page</b> (or Ctrl+K, "
     "\"aerial\").",
     "<b>From the Plans</b> reads the project address or latitude/longitude "
     "off the open set; or type an address or \"33.78, -79.09\".",
     "Pick the area to show (500 ft for a pad up to 4,000 ft for a "
     "corridor) and click <b>Preview</b>. A quick overview appears in a "
     "second or two; the sharp USGS photo follows (USGS can take 20-80 s - "
     "the timer shows it and Cancel stops it).",
     "Get the site inside the yellow box: drag the photo, use the arrows, "
     "roll the wheel to zoom the preview, Wider / Closer to change the box. "
     "None of this downloads again.",
     "Click <b>OK</b>. The photo is added after the sheet you're on, with "
     "its scale set: Area, Length and Count read real feet.",
     "Check the scale against something you know (a parking stall, a "
     "building dimension) before you rely on it."],
    ["Free USGS NAIP imagery is about 2 ft per pixel; the page is enlarged "
     "to 1 ft per pixel and its credit line says so.",
     "Have a county GIS or drone photo? Use the <b>Photo file</b> tab; a "
     "world file (.jgw, .pgw, .tfw) gives the ground size per pixel.",
     "Photos are kept, so reopening the same site is instant."],
    ["Aerial Photo Page"], practice=False)

tut("exports", "Working together", "Export: Excel, Word, CAD and images",
    3, "Get drawings, markups and quantities into other programs.",
    ["File > <b>Export To</b>: Word, Excel, PowerPoint, web page, text, "
     "AutoCAD DXF (this page), PDF/A, PNG or JPEG images.",
     "Quantities: Takeoff tab > <b>Export Quantities (CSV)</b> or "
     "<b>Link Quantities to Excel</b> (the workbook updates when the "
     "takeoff changes).",
     "Markups for another PDF program: File > <b>Export Markups "
     "(XFDF)</b>; Import Markups reads them back.",
     "For people outside the company: File > Export > <b>External Issue "
     "(strip pricing)</b> keeps markups and removes prices, margins and job "
     "data.",
     "PDF Management > <b>Remove Hidden Information</b> removes metadata, "
     "scripts, attachments and hidden text before you send a file; it tells "
     "you if a damaged file kept anything."],
    ["Reduce File Size makes big scanned sets easier to email. It only "
     "writes a copy when the copy is smaller.",
     "File > Protect & Repair > Check / Repair PDF checks a damaged file page by page and "
     "saves a repaired copy next to it; Pages > Booklet / N-up lays pages "
     "out for printing in a new PDF."],
    ["Excel Workbook (.xlsx)…"])

tut("ocr", "Editing PDFs", "Scanned sets: make them searchable", 3,
    "Turn scanned drawings and specs into searchable text.",
    ["Document > <b>Make Searchable (OCR)</b>. Only pages without text are "
     "read; drawings that already have text are skipped quickly.",
     "When it finishes, Ctrl+F, Auto Bookmark Sheets and Link Sheet "
     "References work on the scanned pages too.",
     "Document > <b>Accessibility Check</b> lists what a screen reader "
     "would miss; Spec Book Sections splits a spec book by section."],
    ["OCR uses Tesseract, which must be installed on the PC."],
    ["Make Searchable (OCR)…"], practice=False)


MORE_TIPS = {
    "pages": ["Each sheet keeps its scale and takeoff when pages move, are "
              "inserted or are deleted.",
              "Replace Pages swaps in a revised sheet; it keeps that "
              "sheet's scale.",
              "File > Print Preview shows each page on its paper before it "
              "prints; pick all, this page or a list (1-4, 7), change the "
              "paper, then Print. While printing, a window shows which "
              "page is going out, with Cancel."],
    "sign": ["Verify Signatures (File menu) checks digital signatures on a "
             "PDF you received.",
             "Fill Form From Job fills Project, Owner and Contractor fields "
             "from the job details."],
    "markup": ["Save a styled markup to the Tool Chest (right-click > Add to "
               "Tool Chest) to reuse it with one click.",
               "Click a row in the Markups List to jump to that markup; "
               "Group by a column to see each group's total.",
               "Export Summary saves the list as CSV, Excel or XML.",
               "A Choice column can carry a hidden number (Carpet = 4.50); "
               "formulas use the number, the list shows the name.",
               "Make your own statuses (Lack of information, Oversized) "
               "under Columns & Statuses; a checker sets one instead of "
               "deleting someone's markup."],
    "compare": ["Quick Compare (Same Sheets) is fastest when old and new are "
                "the same sheet at the same size."],
    "scale": ["<b>Auto Scale</b> reads the scale printed on every sheet at "
              "once; Check Against Dimensions confirms it from the drawing's "
              "own dimension strings.",
              "Sheets with details at different scales: Viewports on This "
              "Page gives each detail its own scale.",
              "Always check one known dimension before trusting quantities."],
    "check": ["Accept or reject each automatic find; only accepted items go "
              "into the takeoff and estimate."],
    "estimate": ["Show Unpriced Markups lists takeoff that isn't in the "
                 "estimate yet - nothing slips through.",
                 "Create Proposal turns the estimate into a proposal "
                 "letter."],
    "bidding": ["Bid tabs are kept in the shared price database, so every "
                "estimator sees past unit prices.",
                "Scope Sheets: a blank amount is \"not priced\" and $0.00 "
                "is priced at nothing. Turn on Leveling to plug what a "
                "bidder excluded with your budget or the other bids' "
                "median; plugged cells are shaded and your entries don't "
                "change. Import Excel reads your existing Scope Sheet "
                "workbooks (a SUB LIST tab is never read)."],
    "jobcost": ["The more jobs you close out, the better the suggested "
                "prices get."],
    "civilest": ["Import Prevailing Wages reads a Davis-Bacon wage "
                 "determination into your labor rates.",
                 "Save Bid Version before big changes to compare later."],
    "logins": ["Give each person their own login so the audit trail "
               "shows who measured and priced what."],
    "project": ["Ctrl+Shift+P opens the Project Center from anywhere.",
                "RFIs and submittals can be emailed through Outlook from "
                "their record."],
    "schedule": ["Build Schedule From Plans drafts activities and the "
                 "contract time from the drawings and specs - review it "
                 "before use."],
    "cost": ["Cost to Complete forecasts the final cost from what's spent "
             "and what's left."],
    "collab": ["Everyone sees each other's markups as they're made; "
               "conflicting edits are merged, not lost."],
    "autosave": ["Version History compares or restores earlier saved "
                 "versions of the file."],
}
for _t in T:
    _t["tips"] += MORE_TIPS.get(_t["id"], [])


# ------------------------------------------------------------- Nov 3
tut("copytext", "Editing PDFs", "Copy text and schedules from a drawing", 3,
    "Copy notes, spec text or a whole schedule off a drawing and paste it "
    "into an email, a Word file or Excel.",
    ["Home > <b>Select Text</b> (or press <b>I</b>). The pointer becomes a "
     "text cursor.",
     "Drag from the first word to the last - everything between is "
     "selected, line by line. Start the drag off the text to box an area "
     "instead (a notes block or a schedule on a busy sheet).",
     "<b>Ctrl+C</b> copies it. <b>Ctrl+A</b> selects all the text on the "
     "page; Edit > <b>Copy All Text on This Page</b> copies it in one go.",
     "For a schedule, box it and press <b>Ctrl+Shift+C</b> (Edit > "
     "<b>Copy as Table</b>): it pastes into Excel with each column in its "
     "own cells.",
     "With the Select tool, double-click a word to select it, or select a "
     "callout or text box and press Ctrl+C to copy its words."],
    ["Shift+click extends the selection.",
     "A scanned sheet has no text to copy until Document > Make Searchable "
     "(OCR) adds it.", "Right-click the page for the same commands."],
    try_=["Select Text"])

tut("reportissue", "Getting started", "Report a problem to support", 2,
    "Send support what went wrong, with a screenshot, in one email.",
    ["Help > <b>Report an Issue</b> (or <b>Report This</b> on an error "
     "message). Say what you were doing, what you expected and what "
     "happened.",
     "Check the screenshot of the window: keep it, <b>Retake</b> it or "
     "untick it to leave it out.",
     "Facts about the open drawing go with it - pages, sheet sizes, how "
     "many markups, file size - never the drawing's content. Tick "
     "<b>Attach this drawing</b> only if you're allowed to share it.",
     "Click <b>Open the Email</b>: your email opens addressed to support "
     "with everything attached. Nothing is sent until you click Send."],
    ["After the program stopped responding, the next start asks whether "
     "you want to tell us about it (Don't Ask About Freezes turns that "
     "off).", "The logs that go along have names, emails and network "
     "paths taken out."],
    try_=["Report an Issue"], practice=False)

tut("packages", "Project management", "Track deliveries (FedEx, UPS, USPS, "
    "DHL)", 2,
    "Keep every tracking number for a job's material in one list and "
    "check them with a click.",
    ["Tools > <b>Package Tracker</b>. Type or paste tracking numbers - or "
     "paste a whole shipping email and the numbers are picked out.",
     "Add what it is, who it's from, the job and the day it's expected, "
     "then <b>Add</b>. The carrier is recognised from the number.",
     "Select a package and click <b>Track</b> (or double-click it): the "
     "carrier's own tracking page opens. <b>Track All Not Delivered</b> "
     "opens each one still on its way.",
     "Tick <b>Delivered</b> when it arrives. A package past its expected "
     "day shows <b>LATE</b> in red; pick a job at the bottom to see just "
     "that job's packages."],
    ["If a number is recognised as the wrong carrier, select it > "
     "<b>Change Carrier</b>.", "No carrier accounts are needed; the "
     "status is read on the carrier's page."],
    try_=["Package Tracker"], practice=False)


tut("bidgate", "Estimating", "Before the bid goes out: the bid gate", 4,
    "Catch old prices, expired quotes, unpriced addenda, placeholders and "
    "double counts before the number leaves the office.",
    ["Estimate > <b>Estimate Error Check</b> now also flags: prices older "
     "than 90 days, quotes past their valid-until day, addenda not marked "
     "priced, placeholders / plugs / allowances still in the bid, two areas "
     "of the same item on top of each other, a count clicked twice, and a "
     "subtotal typed in as a line.",
     "Project > <b>Addenda</b> > <b>Mark Priced</b>: its cost impact ($0 if "
     "none) and the estimate line it went into. Until every addendum is "
     "priced the bid form won't fill and the proposal warns.",
     "Right-click an estimate line > <b>Price Still Good (Today)</b> when "
     "the supplier confirms an old price.",
     "Estimate > <b>Placeholders & Allowances</b> lists everything still to "
     "replace - before the bid and again at buyout.",
     "Estimate > <b>Escalation to Buy Date</b>: % a year per cost type from "
     "the bid day to the day you'll buy; <b>Add to Estimate</b> puts the "
     "rise in as a line."],
    ["Estimate > Bid Gate Settings sets the price age.",
     "Every check can be switched off in Error Check like the others."],
    try_=["Placeholders & Allowances"], practice=False)

tut("levelboard", "Estimating", "Leveling Board and trade scope sheets", 4,
    "Level sub quotes against your own scope, with every gap plugged from "
    "your own takeoff.",
    ["Estimate > <b>Leveling Board</b> > <b>New From Trade</b>: pick the "
     "trade (CSI division) and, if you have it, the spec book. The scope "
     "is that trade's takeoff items plus its spec section's items.",
     "<b>Export Scope Sheet</b> gives the checklist to send with the bid "
     "invitation.",
     "<b>Add Sub Quote PDF</b> for each quote: its lines are matched to "
     "your scope rows. Green = confirmed, yellow = unclear (a loose "
     "match), red = a gap (excluded or not quoted).",
     "A gap is plugged with your quantity x your unit price. Right-click a "
     "cell to change it or type their price.",
     "<b>Use Low in Estimate</b> puts the leveled low into the estimate."],
    ["Scanned quotes and phone photos of quotes are read with OCR "
     "(Tesseract) - check the numbers it reads.",
     "Bid Leveling and Bid-Day packages still work as before."],
    try_=["Leveling Board"], practice=False)

tut("worknotes", "Takeoff", "Work Notes Takeoff: what the sheets say", 4,
    "Rehab and upfit drawings often give the quantities in words - "
    "'INSTALL: 2 - 6-INCH PLUG VALVE', 'REMOVE AND REPLACE: 105 LF SITE "
    "FENCING' - not in linework. This reads them into a list.",
    ["Open the drawing set, then Civil > <b>Work Notes Takeoff</b> and "
     "<b>Read the Drawings</b>. <b>Totals</b> adds the same item up "
     "across the sheets; <b>Every row</b> lists each one with its sheet. "
     "Double-click a row to go to that sheet.",
     "The <b>From</b> column says where a row came from: a sheet note, "
     "the summary table (an X for a station with no note on its sheet), "
     "a numbered or keyed note, the fence line measured as drawn, or "
     "worked out (the removal half of a 'remove and replace').",
     "<b>Choose Specification</b> to work out fence posts and barbed "
     "wire strands from the specification's own rules (post spacing, "
     "number of strands). A rule the specification doesn't give is not "
     "applied.",
     "Yellow rows need a look, and <b>Check</b> says why: no number in "
     "the note (counted as 1), marked approximate, the same note twice "
     "on a sheet (two views of one item look the same), a count taken "
     "from symbols, or a measured length that differs from the note.",
     "<b>Export to Excel</b> writes the totals and every row."],
    ["It reads what is written. Conduit and wire routes that aren't "
     "drawn, and sizes that are on a standard detail outside the set, "
     "are not in the list.",
     "A length shown as 'measure' has its make-up from the notes but no "
     "length: measure the run yourself.",
     "Nothing is added to your takeoff or estimate from this window."],
    try_=["Work Notes Takeoff"], practice=False)

tut("bidboard", "Estimating", "Bid Board: the invitations you get", 4,
    "Keep every invitation to bid in one list: when it is due, who is "
    "pricing it, whether to go after it and how it came out.",
    ["Estimate > <b>Bid Board</b>. <b>Add</b> an invitation by typing it "
     "in, or <b>From Email</b> to read a saved invitation email (.eml - "
     "you can drag the file onto the window). The fields it found are "
     "listed; check each one, then Save. Nothing is sent and the email is "
     "not changed.",
     "If it looks like a project already on the board - a similar name "
     "with a close due date, or the same address, even from another GC - "
     "you are told why before it is saved. Rows for the same project are "
     "marked, so it is priced once and every GC gets the same number.",
     "<b>Go / No-Go</b>: answer what you know (scope, location, the GC, "
     "your results with them, workload, bonding). It gives a score and a "
     "recommendation; you decide and give the reason, which is kept. "
     "<b>Weights</b> changes how much each answer counts.",
     "<b>Set Status</b> as it moves: Accepted, Submitted, then Won or "
     "Lost (or Declined). The <b>Calendar</b> tab lists bids due, job "
     "walks and question cutoffs; <b>Export Calendar File</b> makes an "
     ".ics file to import into your calendar.",
     "The <b>Results</b> tab shows win rate by GC, bids per month and "
     "each estimator's open bids. The same results are in Estimate > "
     "<b>Estimating Dashboard</b> > Hit Rate, grouped by <b>GC (bid "
     "to)</b>."],
    ["Win rate counts Won and Lost only.",
     "An Outlook .msg file isn't read: save the email as .eml, or copy "
     "its text and use Paste Email Text.",
     "The board is kept on this PC."],
    try_=["Bid Board"], practice=False)

tut("bidforms", "Estimating", "Bid form, bid results and change orders", 4,
    "Fill the owner's bid form from the estimate, track how you did, and "
    "price a revised sheet as a change order.",
    ["Estimate > <b>Bid Form Autopilot</b>: pick the owner's bid form "
     "(with fields), add alternates and unit prices, and <b>Fill the "
     "Form</b>. Base bid, the amount in words and the addenda go in; then "
     "it checks the bid bond, the signature and the deadline.",
     "Estimate > <b>Estimating Dashboard</b> > Jobs > <b>Low Bid</b> "
     "records the low number; <b>Bid Results (CSV)</b> lists ours, the low "
     "and the gap. Hit Rate can now be grouped by job size and markup.",
     "Billing > <b>Change Order From Revision</b>: open the revised sheet, "
     "pick the earlier set and the sheet it replaces, set the markup - a "
     "change order proposal opens with the priced changes and the revised "
     "sheet clouded as backup."],
    ["Fields are found by their names (Base Bid, Alternate 1, Addendum "
     "2...). Fields it couldn't fill are listed.",
     "Unit prices you don't type are matched to your estimate by each "
     "row's description - they're listed in the check so you can confirm "
     "them.", "The Dashboard's Jobs tab shows each job's estimating "
     "hours from the Time Log."],
    try_=["Bid Form Autopilot"], practice=False)

tut("jobsetup", "Getting started", "Bid downloads, spec risks, time log and "
    "right-click actions", 4,
    "Get a new bid set up in a minute and keep an eye on what it costs.",
    ["File > <b>Open Bid Download (.zip) as a Job</b>: the plan room's zip "
     "is unpacked into Drawings, Specs, Addenda and Other (zips inside "
     "zips too, duplicates kept once, non-PDFs listed), the drawings are "
     "combined and opened, Sheet Setup reads names and scales, and the "
     "folder becomes a Project Center job.",
     "Review > <b>Spec Book Risk Scanner</b>: bonds, liquidated damages, "
     "prevailing wage, insurance limits, long warranties and testing you "
     "pay for, on one page with the section and page of each.",
     "Review > <b>AI: Find RFIs</b> now also flags sheet index entries "
     "with no sheet and spec references to drawings that aren't in the "
     "set - one click makes the RFI.",
     "Tools > <b>Time Log</b>: active time per job and sheet (takeoff vs "
     "review), paused when you step away; Export CSV.",
     "In File Explorer, right-click a PDF for <b>Reduce size</b>, a Word / "
     "Excel / image file for <b>Convert to PDF</b>, or a folder for "
     "<b>Combine PDFs in QuantiSheet</b>."],
    ["Submittals made From Spec Book now list the drawing sheets their "
     "work is on.",
     "Takeoff > Count From a Picture counts a symbol from a picture of it "
     "(a legend snip, a cut sheet, a photo of a printed sheet) - checked "
     "in the review list before anything is counted."],
    try_=["Spec Book Risk Scanner"], practice=False)

tut("bidworkbook", "Estimating", "Bid form workbook, addenda and builder's "
    "risk", 4,
    "Price the owner's bid form in Excel, put it on the PDF with one click "
    "and get builder's risk priced.",
    ["Estimate > <b>Bid Form Workbook</b>: pick the spec book or the bid "
     "form PDF. <b>Make Excel Workbook</b> lists every bid item, quantity "
     "and alternate. Type unit prices and alternate amounts in the yellow "
     "cells only - line totals, the subtotal, add / deduct alternates and "
     "the base bid are formulas.",
     "Save the workbook, then <b>Transfer to PDF</b>: the bid form pages "
     "are filled and a bid schedule page is added whose fields add and "
     "subtract on their own if a number is changed in the PDF.",
     "When an addendum comes in, <b>Check an Addendum</b>: if it reissues "
     "the bid form you see what changed and get a new workbook, with "
     "prices kept for the items that didn't change. Addendum summaries "
     "also say when an addendum has a bid form.",
     "The Spec Book Risk Scanner saves a <b>Bid Form & Insurance "
     "Review</b> PDF beside the spec book: the bid form, insurance and "
     "builder's risk pages behind a cover page.",
     "Estimate > <b>Builder's Risk Quote Request</b>: project, address, "
     "summary of work and estimated amount (from the estimate) on one "
     "page with the spec's builder's risk pages. Check the fields, type "
     "the agent's email and click <b>Email to Insurance</b>."],
    ["Items whose quantity changed in an addendum are left blank in the "
     "new workbook so they get re-priced.",
     "The base bid in the quote request comes from the estimate; change it "
     "before sending if the bid moves."],
    try_=["Bid Form Workbook"], practice=False)


# ------------------------------------------------------------- shortcuts
SHORTCUTS = [
    ("Find any command", "Ctrl+K"), ("Open", "Ctrl+O"), ("Save", "Ctrl+S"),
    ("Undo / Redo", "Ctrl+Z / Ctrl+Y or Ctrl+Shift+Z"),
    ("Find text", "Ctrl+F"),
    ("Fit page / width / actual size", "Ctrl+0 / Ctrl+2 / Ctrl+1"),
    ("Previous view", "Alt+Left"), ("Go to page", "Ctrl+G"),
    ("Next / previous page", "PgDn / PgUp"), ("Select tool", "V"),
    ("Marquee zoom", "Z"), ("Pan", "Hold the wheel button and drag"),
    ("Select Text tool", "I"),
    ("Copy text from the drawing", "Select Text, drag, Ctrl+C (or "
     "double-click a word)"),
    ("Copy a schedule for Excel", "Select Text, box it, Ctrl+Shift+C"),
    ("Select all text on the page", "Ctrl+A"),
    ("Snap on or off", "Shift+F9"), ("Bottom panels", "F9"),
    ("Cloud / Rectangle / Arrow / Text box", "C / R / A / T"),
    ("Callout / Highlight / Pen / Sticky note", "Q / H / P / N"),
    ("Length / Polylength / Area", "Shift+L / Shift+P / Shift+A"),
    ("Cutout / Volume / Count", "Shift+X / Shift+V / Shift+C"),
    ("Wall Area (length x height)", "Shift+W"),
    ("Auto Area / Trace Length", "Shift+R / Shift+T"),
    ("Trace Outline", "Shift+O"),
    ("Auto takeoff rooms / walls", "Ctrl+Shift+R / Ctrl+Shift+W"),
    ("Trade Takeoff / Check Takeoff", "Ctrl+Alt+T / Ctrl+Alt+K"),
    ("Accept / deny a selected AI markup", "A / D"),
    ("Select several markups", "Ctrl+click, or drag a box"),
    ("Reshape: remove a corner", "Ctrl+click the corner"),
    ("Organize Pages", "Ctrl+Shift+G"), ("Project Center", "Ctrl+Shift+P"),
    ("Help Center", "F1"), ("Finish a polyline or area", "Enter or "
                            "double-click"),
    ("Back to Select / cancel", "Esc")]

# 1.1.1 lessons (one window, roles, quick bar, takeoff, Service, Back
# Office, safer files); help_111 registers itself on import
from . import help_111  # noqa: E402,F401


def shortcuts_html():
    rows = "".join(f"<tr><td style='padding:4px 18px 4px 0'>{html.escape(a)}"
                   f"</td><td><b>{html.escape(k)}</b></td></tr>"
                   for a, k in SHORTCUTS)
    return (f"<h2>Keyboard shortcuts</h2><table cellspacing=0>{rows}"
            "</table><p>Every command is also in Ctrl+K command search, "
            "with its shortcut shown.</p>")


def tutorial_html(t, n=None, total=None):
    steps = "".join(f"<li style='margin-bottom:6px'>{s}</li>"
                    for s in t["steps"])
    tips = "".join(f"<li>{s}</li>" for s in t["tips"])
    pos = f"Tutorial {n} of {total} · " if n else ""
    return (f"<p style='color:#888'>{pos}{html.escape(t['group'])} · about "
            f"{t['minutes']} min</p>"
            f"<h2 style='margin-top:0'>{html.escape(t['title'])}</h2>"
            f"<p><b>{html.escape(t['goal'])}</b></p>"
            f"<ol>{steps}</ol>"
            + (f"<h3>Tips</h3><ul>{tips}</ul>" if tips else "")
            + ("<p style='color:#888'>Show Me opens the practice drawings "
               "and starts this for you.</p>" if t["try"] else ""))


def practice_path():
    return os.path.join(settings.DIR, "Practice Drawings.pdf")


class HelpCenter(QDialog):
    def __init__(self, win, start="first"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("QuantiSheet Help Center")
        self.setModal(False)
        self.resize(980, 680)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the tutorials (e.g. scale, "
                                       "RFI, overlay)")
        self.search.textChanged.connect(self.filter)
        top.addWidget(self.search, 1)
        for label, fn in (("Keyboard Shortcuts", self.show_shortcuts),
                          ("Open Practice Drawings", self.open_practice)):
            b = QPushButton(label)
            b.setAutoDefault(False)
            b.clicked.connect(fn)
            top.addWidget(b)
        v.addLayout(top)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._picked)
        split.addWidget(self.tree)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        rv.addWidget(self.body, 1)
        nav = QHBoxLayout()
        self.prev_b = QPushButton("‹ Previous")
        self.prev_b.clicked.connect(lambda: self.step(-1))
        self.next_b = QPushButton("Next ›")
        self.next_b.clicked.connect(lambda: self.step(1))
        self.show_b = QPushButton("Show Me")
        self.show_b.setObjectName("primary")
        self.show_b.setDefault(True)
        for b in (self.prev_b, self.next_b):
            b.setAutoDefault(False)
        self.show_b.clicked.connect(self.show_me)
        self.status = QLabel()
        self.status.setObjectName("muted")
        nav.addWidget(self.prev_b)
        nav.addWidget(self.next_b)
        nav.addWidget(self.status, 1)
        nav.addWidget(self.show_b)
        rv.addLayout(nav)
        split.addWidget(right)
        v.addWidget(split, 1)
        self.items = {}
        self.fill()
        # wide enough for the longest title (Chief's user test, Nov 6:
        # entries were cut off); the rest goes to the page
        fm = self.tree.fontMetrics()
        longest = max((fm.horizontalAdvance(t["title"]) for t in T),
                      default=200)
        left = min(max(280, longest + 70), 440)
        if self.width() < left + 640:
            self.resize(left + 640, self.height())
        split.setSizes([left, self.width() - left])
        self.open_tutorial(start)

    def fill(self):
        self.tree.clear()
        groups = {}
        for t in T:
            g = groups.get(t["group"])
            if g is None:
                g = groups[t["group"]] = QTreeWidgetItem([t["group"]])
                f = g.font(0)
                f.setBold(True)
                g.setFont(0, f)
                g.setFlags(Qt.ItemIsEnabled)
                self.tree.addTopLevelItem(g)
            it = QTreeWidgetItem([t["title"]])
            it.setToolTip(0, t["title"])
            it.setData(0, Qt.UserRole, t["id"])
            g.addChild(it)
            self.items[t["id"]] = it
        self.tree.expandAll()

    def filter(self, text):
        q = text.lower().strip()
        for t in T:
            hay = " ".join([t["title"], t["goal"], t["group"]] + t["steps"] +
                           t["tips"]).lower()
            self.items[t["id"]].setHidden(bool(q) and q not in hay)

    def _picked(self, cur, _prev=None):
        if cur is None:
            return
        tid = cur.data(0, Qt.UserRole)
        if tid:
            self._show(tid)

    def _show(self, tid):
        t = next(x for x in T if x["id"] == tid)
        n = T.index(t) + 1
        self.current = t
        self.body.setHtml(tutorial_html(t, n, len(T)))
        self.show_b.setEnabled(bool(t["try"]) or t["practice"])
        self.prev_b.setEnabled(n > 1)
        self.next_b.setEnabled(n < len(T))
        self.status.setText("")
        done = set(settings.get("tutorials_seen") or [])
        if tid not in done:
            settings.set("tutorials_seen", sorted(done | {tid}))

    def open_tutorial(self, tid):
        it = self.items.get(tid)
        if it is not None:
            self.tree.setCurrentItem(it)
            self._show(tid)
        return it is not None

    def step(self, d):
        i = T.index(self.current) + d
        if 0 <= i < len(T):
            self.open_tutorial(T[i]["id"])

    def show_shortcuts(self):
        self.tree.setCurrentItem(None)
        self.body.setHtml(shortcuts_html())
        self.current = self.current if hasattr(self, "current") else T[0]

    def open_practice(self):
        from . import practice
        path = practice_path()
        practice.make(path)              # fresh each time: safe to mess up
        self.win.open_path(path)
        return path

    def show_me(self):
        t = self.current
        ran = []
        if t["practice"]:
            self.open_practice()
            v = self.win._view
            if v is not None and t.get("page"):
                v.go_to(t["page"])
                self.win.fit_page()
        for name in t["try"]:
            a = self.win.command(name)
            if a is not None and a.isEnabled():
                a.trigger()
                ran.append(name)
        self.status.setText(("Started: " + ", ".join(ran)) if ran else
                            "Practice drawings opened.")
        return ran
