"""Ribbon tiles: every button has an icon, labels in a group share a
baseline, and the Tool Chest follows takeoff mode."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint                              # noqa: E402

from app import icons                                          # noqa: E402
from app.ribbon import RibbonButton, tile_contrast             # noqa: E402
from test_gui import win, qapp                                 # noqa: E402,F401


def test_green_tile_glyph_clears_aa(qapp):
    """White glyphs clear 4.5:1 on the green tile, including the lighter
    gradient end and hover. The fill is the same in light and dark mode."""
    ratios = tile_contrast()
    for key in ("fill", "top", "hover", "pressed", "disabled"):
        assert ratios[key] >= 4.5, (key, round(ratios[key], 2))


def test_added_commands_and_ai_status_are_on_the_ribbon(win):
    """The menu windows and the AI tab, including the local-model chip."""
    from app.ribbon import ModelStatus

    def labels(tab):
        out = []
        for group in win.ribbon.pages[tab].groups.values():
            for b in group.buttons:
                out.append(b.text().replace("&&", "&"))
        return out

    home = labels("Home")
    for name in ("Generate Set", "Print Preview", "Save As", "Recover",
                 "Dropbox", "Export"):
        assert name in home, name
    ai = labels("AI")
    for name in ("AI Takeoff", "Models", "Voice", "Find RFIs",
                 "Schedule From Plans"):
        assert name in ai, name
    assert win.ribbon.pages["AI"].findChildren(ModelStatus)
    service = labels("Service")
    for name in ("Work Order", "T&M Tag", "Truck Stock", "Customer Quote",
                 "GBB Quote", "Tune-ups", "Warranty", "Changeout",
                 "Load Report"):
        assert name in service, name


def test_every_ribbon_button_has_an_icon(win):
    missing = []
    for name, page in win.ribbon.pages.items():
        for title, group in page.groups.items():
            for b in group.buttons:
                if not isinstance(b, RibbonButton):
                    continue
                glyph = b._icon_name()
                if not icons.has(glyph):
                    missing.append((name, title, b.text(), glyph))
                    continue
                pm = icons.pixmap(glyph, 18, "#ffffff", "#ffffff")
                if pm.isNull() or pm.width() < 1:
                    missing.append((name, title, b.text(), glyph))
    assert not missing, missing


def test_labels_in_a_group_share_a_baseline(win, qapp):
    """One-line and two-line labels sit on the same baseline. The Service
    tab is included (Work Order wraps; T&M Tag does not)."""
    win.resize(1600, 900)
    win.show()
    rb = win.ribbon
    saw_service = False
    for name in list(rb.pages):
        rb.show_page(name)
        if qapp is not None:
            qapp.processEvents()
        page = rb.pages[name]
        page.widget().layout().activate()
        for title, group in page.groups.items():
            group.layout().activate()
            bases = []
            labels = []
            for b in group.buttons:
                if not isinstance(b, RibbonButton) or not b.isVisibleTo(page):
                    continue
                pt = b.mapTo(page.widget(), QPoint(0, b.label_baseline()))
                bases.append(pt.y())
                labels.append(b.text().replace("&&", "&"))
            assert len(set(bases)) <= 1, (name, title, list(zip(labels, bases)))
            if name == "Service" and title == "Calls":
                saw_service = True
                assert "Work Order" in labels and "T&M Tag" in labels
                assert len(bases) >= 2
    assert saw_service


def test_tool_chest_follows_takeoff_mode(win, qapp):
    """Hidden outside takeoff, shown on the Takeoff tab. Every tab change
    closes it unless the new tab is Takeoff (Jon, Nov 6), even with a
    takeoff tool active; picking a takeoff tool opens it. Properties stays
    up either way."""
    win.resize(1400, 900)
    win.show()
    qapp.processEvents()
    rb = win.ribbon

    rb.show_page("Home")
    qapp.processEvents()
    assert not win.chest_dock.isVisible()
    assert win.props_dock.isVisible()

    rb.show_page("Takeoff")
    qapp.processEvents()
    assert win.chest_dock.isVisible()
    assert win.props_dock.isVisible()

    rb.show_page("Service")
    qapp.processEvents()
    assert not win.chest_dock.isVisible()

    win.chest_dock.show()
    qapp.processEvents()
    assert win.chest_dock.isVisible()
    rb.show_page("Markup")
    qapp.processEvents()
    assert not win.chest_dock.isVisible()
    assert win.props_dock.isVisible()

    win.set_tool("calibrate", ask=False)
    qapp.processEvents()
    assert win.chest_dock.isVisible()
    rb.show_page("Help")
    qapp.processEvents()
    # Jon, Nov 6: every tab change closes it, takeoff tool active or not
    assert not win.chest_dock.isVisible()
    rb.show_page("Takeoff")
    qapp.processEvents()
    assert win.chest_dock.isVisible()
    rb.show_page("Estimate")                   # Length-style tool still on
    qapp.processEvents()
    assert not win.chest_dock.isVisible()

    win.set_tool(None, ask=False)
    qapp.processEvents()
    assert not win.chest_dock.isVisible()
    assert win.props_dock.isVisible()
