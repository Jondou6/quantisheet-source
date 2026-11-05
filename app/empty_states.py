"""Plain empty-state text for every dock and panel.

Keys are object names the window already uses. A dock's object name is
its title in lower case, with spaces turned into underscores
(MainWindow._dock). The page list inside the Pages dock is also named
"thumbs".

Claude calls apply_empty_state(widget) when a panel has nothing to show.
The label it adds is named "empty_state", so it can be hidden once the
panel has rows.
"""
EMPTY_LABEL = "empty_state"

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


def object_name_for(widget):
    """The panel or dock object name for `widget`, walking up to a dock."""
    if widget is None:
        return ""
    w = widget
    for _ in range(12):
        if w is None:
            break
        name = str(w.objectName() or "")
        if name in EMPTY:
            return name
        w = w.parent() if hasattr(w, "parent") else None
    return ""


def _content(widget):
    """The panel inside a dock or its scroll wrapper."""
    from PySide6.QtWidgets import QDockWidget, QScrollArea
    w = widget
    if isinstance(w, QDockWidget):
        inner = w.widget()
        if inner is not None:
            w = inner
    if isinstance(w, QScrollArea) and w.objectName() == "DockScroll":
        inner = w.widget()
        if inner is not None:
            w = inner
    return w


def _ensure_label(host, text):
    from PySide6.QtWidgets import (
        QAbstractItemView, QAbstractScrollArea, QBoxLayout, QLabel,
    )
    if isinstance(host, QLabel):
        if host.objectName() not in EMPTY:
            host.setObjectName(EMPTY_LABEL)
        host.setWordWrap(True)
        host.setText(text)
        return host
    for child in host.findChildren(QLabel, EMPTY_LABEL):
        if child.parent() is host:
            child.setWordWrap(True)
            child.setText(text)
            child.setVisible(True)
            return child
    # A list or the page thumbnails already scrolls. A label dropped
    # into it would not show with the rows, so the tool tip carries
    # the sentence instead.
    if isinstance(host, (QAbstractScrollArea, QAbstractItemView)):
        return None
    lay = host.layout()
    if not isinstance(lay, QBoxLayout):
        return None
    label = QLabel(text, host)
    label.setObjectName(EMPTY_LABEL)
    label.setWordWrap(True)
    lay.insertWidget(0, label)
    return label


def apply_empty_state(widget):
    """Show the empty-state sentence for this panel.

    Uses the widget's object name, or a parent dock's object name.
    Returns the sentence, or None when the widget is not one of these
    panels. A label named "empty_state" is filled in when the panel has
    a box layout. The same text is also stored on the widget as the
    tool tip and the "emptyState" property.
    """
    if widget is None:
        return None
    text = sentence(object_name_for(widget))
    if not text:
        return None
    widget.setProperty("emptyState", text)
    if hasattr(widget, "setToolTip"):
        widget.setToolTip(text)
    host = _content(widget)
    if host is not widget:
        host.setProperty("emptyState", text)
        if hasattr(host, "setToolTip"):
            host.setToolTip(text)
    _ensure_label(host, text)
    return text
