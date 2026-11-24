"""Nov 6 (Jon): the blue accent is now the ribbon's tile green. Fills use
the tile green itself; green text and lines on the background use a shade
of it that stays readable (4.5:1) in dark and light mode."""
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


def test_accent_is_the_tile_green_in_both_modes():
    for t in (theme.DARK, theme.LIGHT):
        assert t["accent"].lower() == ribbon.GREEN_FILL.lower()


def test_green_text_and_fills_are_readable():
    for t in (theme.DARK, theme.LIGHT):
        for bg in ("window", "surface", "surface2"):
            assert _cr(t["accent_text"], t[bg]) >= 4.5, (bg, t["accent_text"])
        assert _cr(t["on_accent"], t["accent"]) >= 4.5
        assert _cr(t["on_accent"], t["accent2"]) >= 4.5      # hover


def test_no_blue_left_in_the_theme():
    import inspect
    src = inspect.getsource(theme).lower()
    for old in ("#4c8dff", "#77a8ff", "#2563eb", "#1d4ed8", "#25344f",
                "#e8efff"):
        assert old not in src
