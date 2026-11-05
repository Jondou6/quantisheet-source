"""OCR quality checks. TSV text is made up. Images are drawn in the test."""
import numpy as np
import pytest
from PIL import Image

from app import ocr_quality as oq


HEADER = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
          "left\ttop\twidth\theight\tconf\ttext")


def _tsv(*rows):
    body = "\n".join(rows)
    return HEADER + ("\n" + body if body else "") + "\n"


def _word(page, text, conf, level=5):
    return (f"{level}\t{page}\t1\t1\t1\t1\t10\t20\t30\t12\t{conf}\t{text}")


def _bars(angle):
    """A made-up page of horizontal rules, rotated by `angle` degrees.

    OpenCV's positive angle is counter-clockwise, which is the sign
    estimate_skew_degrees reports.
    """
    height, width = 700, 900
    image = np.full((height, width), 255, np.uint8)
    for y in range(140, height - 140, 34):
        image[y:y + 5, 70:width - 70] = 0
    if angle:
        center = (width / 2.0, height / 2.0)
        matrix = oq.cv2.getRotationMatrix2D(center, angle, 1.0)
        image = oq.cv2.warpAffine(image, matrix, (width, height),
                                  flags=oq.cv2.INTER_LINEAR, borderValue=255)
    return image


def _pillow(array, dpi=None):
    image = Image.fromarray(array, mode="L")
    if dpi is not None:
        image.info["dpi"] = (dpi, dpi)
    return image


GOOD = _tsv(
    _word(1, "FOOTING", 96.2),
    _word(1, "DETAIL", 91.0),
    _word(1, "SCALE", 88.4),
    # a line row and an empty word must not move the average
    "4\t1\t1\t1\t1\t0\t10\t20\t80\t12\t-1\t",
    _word(1, "", 99),
    _word(1, "NOPE", -1),
)
POOR = _tsv(
    _word(1, "F00T1NG", 40),
    _word(1, "D3TAIL", 55),
)
TWO = _tsv(
    _word(1, "FOOTING", 96.2),
    _word(1, "DETAIL", 91.0),
    _word(1, "SCALE", 88.4),
    _word(2, "F00T1NG", 40),
    _word(2, "D3TAIL", 55),
)
LANG_TEXT = """List of available languages (4):
eng
osd
spa
chi_sim
Error opening data file /made/up/tessdata
script/Latin
"""


def _codes(flags):
    return [flag.code for flag in flags]


def test_good_page_average_ignores_non_words():
    scores = oq.page_confidence(GOOD)
    assert len(scores) == 1
    score = scores[0]
    assert score.page == 1
    assert score.word_count == 3
    assert score.low_word_count == 0
    assert score.mean_confidence == pytest.approx((96.2 + 91.0 + 88.4) / 3)
    assert score.flags == ()
    assert score.poor is False


def test_poor_page_says_why_in_plain_language():
    score = oq.page_confidence(POOR)[0]
    assert score.mean_confidence == pytest.approx(47.5)
    assert score.word_count == 2
    assert score.low_word_count == 1
    assert _codes(score.flags) == ["low_confidence"]
    reason = score.flags[0].reason
    assert "47.5 out of 100" in reason
    assert "1 of 2 words was under 50" in reason
    assert "too unclear to trust" in reason
    assert "TSV" not in reason
    assert score.flags[0].severity == "poor"


def test_confidence_boundary_is_70():
    clear = oq.page_confidence(_tsv(_word(1, "WALL", 70), _word(1, "A", 70)))
    assert clear[0].flags == ()
    poor = oq.page_confidence(_tsv(_word(1, "WALL", 69.9)))
    assert _codes(poor[0].flags) == ["low_confidence"]
    assert "69.9 out of 100" in poor[0].flags[0].reason


def test_pages_come_out_in_number_order_with_a_gap():
    text = _tsv(_word(3, "EAST", 80), _word(1, "WEST", 90))
    pages = [score.page for score in oq.page_confidence(text)]
    assert pages == [1, 3]


def test_a_page_with_no_words_is_flagged():
    text = _tsv("1\t2\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t")
    score = oq.page_confidence(text)[0]
    assert score.page == 2
    assert score.word_count == 0
    assert score.mean_confidence is None
    assert _codes(score.flags) == ["no_words"]
    assert "No words were read" in score.flags[0].reason


def test_crlf_and_a_blank_document():
    text = GOOD.replace("\n", "\r\n")
    assert oq.page_confidence(text)[0].word_count == 3
    assert oq.page_confidence("") == []
    assert oq.page_confidence("\n") == []


def test_tsv_without_a_header_is_refused():
    with pytest.raises(oq.TSVError):
        oq.page_confidence("5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\tHI\n")
    with pytest.raises(oq.TSVError):
        oq.page_confidence(b"level\tpage_num")


def test_two_pages_keep_their_own_scores():
    scores = oq.page_confidence(TWO)
    assert [score.page for score in scores] == [1, 2]
    assert scores[0].poor is False
    assert scores[1].poor is True


def test_dpi_boundary_and_wording():
    assert oq._dpi_flags(200) == []
    low = oq._dpi_flags(199)
    assert low[0].code == "low_dpi"
    assert "199 DPI" in low[0].reason
    assert "dots per inch" in low[0].reason
    assert "300 DPI" in low[0].reason
    missing = oq._dpi_flags(None)
    assert missing[0].code == "no_dpi"
    assert "doesn't say how fine" in missing[0].reason


def test_skew_flag_starts_at_two_degrees():
    assert oq._skew_flags(None) == []
    assert oq._skew_flags(1.9) == []
    flagged = oq._skew_flags(2)
    assert flagged[0].code == "skew"
    assert "about 2.0 degrees" in flagged[0].reason
    assert "Lay the sheet flat" in flagged[0].reason
    assert "at least 12 degrees" in oq._skew_flags(12)[0].reason
    assert "about 3.5 degrees" in oq._skew_flags(-3.5)[0].reason


def test_level_drawing_is_not_tilted(tmp_path):
    path = tmp_path / "level.png"
    _pillow(_bars(0)).save(path, dpi=(300, 300))
    check = oq.check_image(str(path))
    assert check.dpi == 300
    assert check.skew_degrees == pytest.approx(0, abs=0.5)
    assert check.flags == ()
    assert check.poor is False


def test_png_jpeg_and_split_dpi(tmp_path):
    array = _bars(0)
    png = tmp_path / "a.png"
    jpg = tmp_path / "a.jpg"
    Image.fromarray(array, mode="L").save(png, dpi=(300, 300))
    Image.fromarray(array, mode="L").save(jpg, format="JPEG", dpi=(300, 300),
                                          quality=95)
    assert oq.image_dpi(png) == 300
    assert oq.check_image(jpg).dpi == 300
    split = tmp_path / "split.png"
    Image.fromarray(array, mode="L").save(split, dpi=(300, 72))
    check = oq.check_image(split)
    assert check.dpi == 72
    assert _codes(check.flags) == ["low_dpi"]


def test_made_up_tilt_is_recovered_and_flagged():
    tilted = _pillow(_bars(4.0), dpi=300)
    check = oq.check_image(tilted)
    assert check.skew_degrees == pytest.approx(4.0, abs=0.8)
    assert "skew" in _codes(check.flags)
    other = oq.estimate_skew_degrees(_bars(-3.5))
    assert other == pytest.approx(-3.5, abs=0.8)


def test_blank_solid_and_missing_dpi():
    blank = _pillow(np.full((400, 400), 255, np.uint8), dpi=300)
    blank_check = oq.check_image(blank)
    assert blank_check.skew_degrees is None
    assert _codes(blank_check.flags) == ["blank_scan"]
    assert "looks blank" in blank_check.flags[0].reason
    solid = _pillow(np.zeros((400, 400), np.uint8), dpi=300)
    assert _codes(oq.check_image(solid).flags) == ["solid_scan"]
    bare = oq.check_image(_bars(0))
    assert bare.dpi is None
    assert "no_dpi" in _codes(bare.flags)
    assert "blank_scan" not in _codes(bare.flags)


def test_color_array_and_a_missing_file(tmp_path):
    gray = _bars(0)
    color = np.dstack([gray, gray, gray])
    check = oq.check_image(color, dpi=300)
    assert check.dpi == 300
    assert check.skew_degrees == pytest.approx(0, abs=0.5)
    assert check.flags == ()
    missing = tmp_path / "no-such.png"
    with pytest.raises(oq.ScanError, match="Can't read"):
        oq.check_image(missing)


def test_caller_dpi_overrides_a_coarse_file(tmp_path):
    path = tmp_path / "coarse.png"
    _pillow(_bars(0)).save(path, dpi=(72, 72))
    check = oq.check_image(path, dpi=300)
    assert check.dpi == 300
    assert "low_dpi" not in _codes(check.flags)


def test_parse_list_langs_skips_the_header_and_errors():
    assert oq.parse_list_langs(LANG_TEXT) == ["chi_sim", "eng", "osd", "spa"]
    # Same shape Tesseract 5 prints, with a made-up data folder.
    shaped = ('List of available languages in "/made/up/tessdata/" (2):\n'
              "eng\nosd\n")
    assert oq.parse_list_langs(shaped) == ["eng", "osd"]
    assert oq.parse_list_langs("ENG\neng\n") == ["eng"]


def test_language_flags_name_the_missing_pack():
    packs = oq.installed_languages(runner=lambda: LANG_TEXT)
    assert packs.tesseract_found is True
    assert packs.codes == ("chi_sim", "eng", "osd", "spa")
    assert oq.language_flags(packs, "eng") == ()
    spanish = oq.language_flags(["eng"], "spa")
    assert spanish[0].code == "missing_language"
    assert "Spanish (spa)" in spanish[0].reason
    assert "Installed packs: eng." in spanish[0].reason
    both = oq.language_flags(packs, "eng+deu")
    assert "German (deu)" in both[0].reason
    assert "French" not in both[0].reason
    none = oq.language_flags([], "eng")
    assert "Installed packs: none." in none[0].reason
    assert oq.language_flags(["eng"], "") == ()


def test_missing_tesseract_is_its_own_flag(monkeypatch):
    monkeypatch.setattr("app.ocr.find_tesseract", lambda: None)
    packs = oq.installed_languages()
    assert packs.tesseract_found is False
    assert packs.codes == ()
    flag = oq.language_flags(packs)[0]
    assert flag.code == "no_tesseract"
    assert "Tesseract OCR is not installed" in flag.reason


def test_list_langs_uses_stderr_and_does_not_use_a_shell(monkeypatch):
    seen = {}

    class Out:
        stdout = b""
        stderr = b"List of available languages (1):\neng\n"
        returncode = 0

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return Out()

    monkeypatch.setattr("app.ocr.find_tesseract",
                        lambda: r"C:\Tesseract-OCR\tesseract.exe")
    monkeypatch.setattr(oq.subprocess, "run", fake_run)
    packs = oq.installed_languages()
    assert seen["cmd"] == [r"C:\Tesseract-OCR\tesseract.exe", "--list-langs"]
    assert seen["kwargs"].get("shell", False) is False
    assert packs.codes == ("eng",)
    assert packs.tesseract_found is True


def test_a_runner_does_not_start_tesseract(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("tesseract was started")

    monkeypatch.setattr(oq.subprocess, "run", boom)
    packs = oq.installed_languages(runner=lambda: "eng\nosd\n")
    assert packs.codes == ("eng", "osd")


def test_assess_a_clean_page_has_no_flags():
    image = _pillow(_bars(0), dpi=300)
    reports = oq.assess(GOOD, image=image, languages=["eng", "osd"])
    assert len(reports) == 1
    report = reports[0]
    assert report.poor is False
    assert report.flags == ()
    assert report.dpi == 300
    assert report.skew_degrees == pytest.approx(0, abs=0.5)
    assert report.word_count == 3


def test_assess_stacks_every_reason():
    image = _pillow(_bars(4.0), dpi=72)
    reports = oq.assess(POOR, image=image, languages=[])
    assert len(reports) == 1
    codes = _codes(reports[0].flags)
    assert codes == ["low_confidence", "low_dpi", "skew", "missing_language"]
    for flag in reports[0].flags:
        assert flag.reason.endswith(".")
        assert "TSV" not in flag.reason
        assert flag.severity == "poor"
    assert reports[0].dpi == 72
    assert reports[0].skew_degrees == pytest.approx(4.0, abs=0.8)


def test_explicit_dpi_applies_to_every_page_and_languages_can_be_skipped():
    reports = oq.assess(TWO, dpi=72)
    assert [report.dpi for report in reports] == [72, 72]
    assert reports[0].skew_degrees is None
    assert _codes(reports[0].flags) == ["low_dpi"]
    assert _codes(reports[1].flags) == ["low_confidence", "low_dpi"]
    assert oq.assess(TWO, dpi=200)[0].flags == ()


def test_one_image_for_many_pages_is_refused():
    with pytest.raises(ValueError, match="one page"):
        oq.assess(TWO, image=_pillow(_bars(0), dpi=300))


def test_blank_scan_with_no_words():
    blank = _pillow(np.full((300, 300), 255, np.uint8), dpi=300)
    text = _tsv("1\t1\t0\t0\t0\t0\t0\t0\t10\t10\t-1\t")
    report = oq.assess(text, image=blank, languages=("eng",))[0]
    assert _codes(report.flags) == ["no_words", "blank_scan"]
    assert report.mean_confidence is None


def test_bad_dpi_argument_is_refused():
    with pytest.raises(oq.ScanError):
        oq.assess(GOOD, dpi=0)
    with pytest.raises(oq.ScanError):
        oq.check_image(_bars(0), dpi=True)


def test_module_imports_when_opencv_is_missing(monkeypatch):
    """A PC without OpenCV can still import the module. A scan check
    says why, instead of crashing on a missing name."""
    import importlib
    import sys
    real = sys.modules.get("cv2")
    monkeypatch.setitem(sys.modules, "cv2", None)
    try:
        importlib.reload(oq)
        assert oq.cv2 is None
        assert oq.page_confidence(GOOD)[0].word_count == 3
        # confidence and a caller-supplied DPI do not need OpenCV
        reports = oq.assess(GOOD, dpi=300, languages=["eng"])
        assert reports[0].poor is False
        assert reports[0].dpi == 300
        gray = _bars(0)
        with pytest.raises(oq.ScanError, match="can't be checked") as caught:
            oq.check_image(gray)
        message = str(caught.value)
        assert "OpenCV" in message
        assert "NameError" not in message
        with pytest.raises(oq.ScanError, match="OpenCV"):
            oq.estimate_skew_degrees(gray)
        with pytest.raises(oq.ScanError, match="OpenCV"):
            oq.assess(GOOD, image=gray)
        assert oq.image_dpi(gray) is None
        with pytest.raises(oq.ScanError, match="OpenCV"):
            oq.image_dpi(np.dstack([gray, gray, gray]))
    finally:
        if real is not None:
            sys.modules["cv2"] = real
        else:
            sys.modules.pop("cv2", None)
        importlib.reload(oq)
    assert oq.cv2 is real
