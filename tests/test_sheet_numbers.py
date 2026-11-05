"""Sheet numbers on standard-detail sheets (MD2, SD3, HD1, ED4): a detail
callout elsewhere on the sheet used to win over the title block."""
from app import sheets

W, H = 2592.0, 1728.0


def test_standard_detail_sheet_number_from_the_title_block():
    words = [(400, 300, 420, 312, "S5"),           # a detail callout
             (900, 700, 930, 712, "E3"),
             (2300, 1600, 2400, 1620, "DRAWING"),
             (2400, 1600, 2480, 1620, "NUMBER:"),
             (2380, 1640, 2440, 1680, "MD2"),      # the sheet number
             (2300, 1690, 2500, 1700, "MECHANICAL")]
    num, _title = sheets.sheet_info(words, W, H)
    assert num == "MD2"
    for code in ("SD3", "HD1", "ED4", "SD8"):
        assert sheets.DISCIPLINE.match(code)
    assert not sheets.DISCIPLINE.match("XD1")
