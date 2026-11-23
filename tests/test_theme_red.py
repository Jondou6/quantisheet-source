"""Nov 23 (Jon): QuantiSheet red everywhere, the logo's red, so the
programs match (Nov 6 it was the tile green, before that blue). Fills use
the tile red itself; red text and lines on the background use a shade of
it that stays readable (4.5:1) in dark and light mode."""
from app import ribbon, theme


def _lum(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
         for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _cr(a, b):
    a, b = _lum(a), _lum(b)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def test_accent_is_the_tile_red_in_both_modes():
    for t in (theme.DARK, theme.LIGHT):
        assert t["accent"].lower() == ribbon.TILE_FILL.lower()
    assert ribbon.TILE_FILL.lower() == "#bd2322"        # the logo's red


def test_red_text_and_fills_are_readable():
    for t in (theme.DARK, theme.LIGHT):
        for bg in ("window", "surface", "surface2"):
            assert _cr(t["accent_text"], t[bg]) >= 4.5, (bg, t["accent_text"])
        assert _cr(t["on_accent"], t["accent"]) >= 4.5
        assert _cr(t["on_accent"], t["accent2"]) >= 4.5      # hover


def test_no_blue_or_green_accent_left():
    import inspect
    for mod in (theme, ribbon):
        src = inspect.getsource(mod).lower()
        for old in ("#4c8dff", "#77a8ff", "#2563eb", "#1d4ed8", "#25344f",
                    "#e8efff", "#0e6a60", "#1f746b", "#3dbba9", "#0b5a51",
                    "#e2f1ee", "#173430"):
            assert old not in src, (mod.__name__, old)


def test_good_states_are_red_not_green():
    """Nov 23 (Jon): done / won / ready / OK use QuantiSheet red and its pale
    tint, like QuantiLink; problems keep their own look."""
    import inspect
    from app import (accessibility_ui, ada_ui, betalicense, bidboard_ui,
                     prebid_ui,
                     calculators_ui, coverage_ui, exclusions_ui, fillsign_ui,
                     leveling_ui, qualify)
    from app.pm import recovery_ui
    from app.service import visit_calendar_ui
    assert theme.LIGHT["ok"] == theme.GOOD == ribbon.TILE_FILL.lower()
    assert _cr(theme.DARK["ok"], theme.DARK["window"]) >= 4.5
    assert _cr(theme.LIGHT["ok"], theme.LIGHT["window"]) >= 4.5
    assert bidboard_ui.STATUS_BG["Won"] == qualify.COLORS[qualify.OK] \
        == theme.GOOD_SOFT
    for mod in (accessibility_ui, ada_ui, betalicense, bidboard_ui,
                calculators_ui, coverage_ui, exclusions_ui, fillsign_ui,
                leveling_ui, qualify, recovery_ui, visit_calendar_ui,
                prebid_ui,
                ribbon):
        src = inspect.getsource(mod).lower()
        for old in ("#cdf0cd", "#12865a", "#2e7d32", "#3fb27f", "#1e8449",
                    "#28a745", "#2ea043", "#1b7f3b", "#d9f5e3",
                    "222, 244, 222", "46, 160, 67", "20, 130, 50",
                    "#232b2b", "#eef1f1", "35, 43, 43", "#d3dcdc"):
            assert old not in src, (mod.__name__, old)
