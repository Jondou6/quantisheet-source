"""Plain empty-state text for every dock and panel.

Keys are object names the window already uses. A dock's object name is
its title in lower case, with spaces turned into underscores
(MainWindow._dock). The page list inside the Pages dock is also named
"thumbs".

The window puts the sentence on each panel's View-menu item and What's
This (MainWindow._empty_state_tips); panels keep their own empty-list
text. (A label inside the empty panel was planned and dropped, Nov 16.)
"""

# (what goes here, how to start)
EMPTY = {
    "pages": (
        "Small pictures of each page in the open PDF show up here.",
        "Open a PDF with File > Open, then click a page to jump to it.",
    ),
    "bookmarks": (
        "Bookmarks in the PDF show up here.",
        "Open a PDF. Click Add to bookmark the page you are on, or "
        "click a bookmark to jump to it.",
    ),
    "documents": (
        "The PDFs in the job folder show up here.",
        "Click Choose Folder and pick the folder for this job. "
        "Double-click a file to open it.",
    ),
    "sets": (
        "Every sheet in a drawing set shows up here.",
        "Start a set from your PDF files, or open a set you already "
        "saved. The buttons along the top do both.",
    ),
    "takeoff": (
        "The items you measure show up here, with a total for each one.",
        "Open a PDF, set the scale, then click + New Item and measure "
        "on the drawing.",
    ),
    "tool_chest": (
        "Saved tools show up here.",
        "Right-click a markup on the page and choose Add to Tool Chest. "
        "Click a tool here to draw with it.",
    ),
    "properties": (
        "The color, line, and comment for the selected markup show up here.",
        "Click a markup on the page. Before you select one, this shows "
        "the style the next markup will use.",
    ),
    "markups_list": (
        "Every markup and measurement in the PDF shows up here.",
        "Open a PDF and draw or measure. Double-click a row to jump to "
        "it on the page.",
    ),
    "estimate": (
        "Prices for what you measured show up here.",
        "Measure something on the drawing, then type a unit cost in "
        "this table.",
    ),
    "quantities": (
        "Totals for what you measured show up here.",
        "Open a PDF and measure on the drawing. Export CSV saves the list.",
    ),
    "assemblies": (
        "Assemblies for this job show up here, with material and labor.",
        "Open a PDF, then click Assembly Library to pick an assembly "
        "and take it off.",
    ),
    # _dock only replaces spaces, so the slash in "RFI / Submittal Log"
    # stays in the object name.
    "rfi_/_submittal_log": (
        "RFIs and submittals for this job show up here.",
        "Open a PDF, then click New RFI or New Submittal.",
    ),
    "thumbs": (
        "Small pictures of each page in the open PDF show up here.",
        "Open a PDF with File > Open, then click a page to jump to it.",
    ),
}


def sentence(name):
    """The two parts joined, or None when `name` is not a known panel."""
    pair = EMPTY.get(name)
    if not pair:
        return None
    return f"{pair[0]} {pair[1]}"
