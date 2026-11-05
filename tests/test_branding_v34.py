"""v34 branding: installer wizard images + app splash (Canva / company)."""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    path = os.path.join(ROOT, rel)
    assert os.path.isfile(path), f"missing {rel}"
    return path


def test_wizard_side_bmp_exists_and_size():
    from PIL import Image
    path = _read(os.path.join("installer", "wizard-side.bmp"))
    im = Image.open(path)
    assert im.format == "BMP"
    assert im.mode in ("RGB", "BGR;24") or im.mode == "RGB"
    assert im.size == (164, 314)


def test_wizard_small_bmp_exists_and_size():
    from PIL import Image
    path = _read(os.path.join("installer", "wizard-small.bmp"))
    im = Image.open(path)
    assert im.format == "BMP"
    assert im.size == (147, 147)


def test_wizard_header_bmp_exists_and_size():
    from PIL import Image
    path = _read(os.path.join("installer", "wizard-header.bmp"))
    im = Image.open(path)
    assert im.format == "BMP"
    assert im.size == (1000, 200)


def test_splash_png_exists_and_size():
    from PIL import Image
    path = _read("splash.png")
    im = Image.open(path)
    assert im.size == (1200, 700)


def test_iss_references_wizard_images():
    text = open(_read(os.path.join("installer", "quantisheet.iss")),
                encoding="utf-8").read()
    assert re.search(r"(?im)^WizardImageFile\s*=\s*wizard-side\.bmp\s*$",
                     text)
    assert re.search(r"(?im)^WizardSmallImageFile\s*=\s*wizard-small\.bmp\s*$",
                     text)


def test_build_installer_mentions_wizard_assets():
    text = open(_read(os.path.join("tools", "build_installer.py")),
                encoding="utf-8").read()
    assert "wizard-side.bmp" in text
    assert "wizard-small.bmp" in text
    assert "splash.png" in text


def test_spec_bundles_splash():
    text = open(_read("quantisheet.spec"), encoding="utf-8").read()
    assert "splash.png" in text


def test_main_shows_splash():
    text = open(_read(os.path.join("app", "main.py")), encoding="utf-8").read()
    assert "QSplashScreen" in text
    assert "splash.png" in text
    assert "_show_splash" in text


def test_splash_never_covers_license_prompt():
    """Shown early only when no license prompt is coming, otherwise after
    it, and not kept on top of other windows (so recovery and other
    prompts are never hidden behind it)."""
    text = open(_read(os.path.join("app", "main.py")), encoding="utf-8").read()
    run = text[text.index("def run("):text.index("def _smoke(")]
    early = run.index("_show_splash(app)")
    assert "None if betalicense.required() else _show_splash(app)" in run
    late = run.index("_show_splash(app)", early + 1)
    assert run.index("betalicense.gate()") < late
    assert "WindowStaysOnTopHint" not in text
    assert text.rstrip().endswith("sys.exit(run())")
