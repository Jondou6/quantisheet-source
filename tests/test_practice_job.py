"""Permanent practice job: sandbox plan, made-up estimate, resumable steps."""
import hashlib
import json
import os

import fitz
import pytest

from app import practice, practice_job, settings
from app.annotate import read_scales


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "settings.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _snapshot(root):
    """{abspath: sha256} for every file under root."""
    out = {}
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                data = open(path, "rb").read()
            except OSError:
                continue
            out[os.path.abspath(path)] = hashlib.sha256(data).hexdigest()
    return out


def test_steps_are_a_ten_minute_first_job():
    ids = [item["id"] for item in practice_job.STEPS]
    assert ids == ["open", "scale", "measure", "price", "export"]
    assert sum(item["minutes"] for item in practice_job.STEPS) == 10
    for item in practice_job.STEPS:
        assert item["title"] and item["what"] and item["how"] and item["call"]
    assert practice_job.step("measure")["length_ft"] == 60.0
    assert practice_job.known_scale()["ppu"] == practice.PPU
    assert practice_job.known_scale()["name"] == '1/4" = 1\'-0"'


def test_sample_estimate_is_made_up_and_prices_the_known_wall():
    est = practice_job.sample_estimate()
    assert est["made_up"] is True
    assert est["job"] == "Practice Clinic"
    assert est["wall"]["length_ft"] == 60.0
    assert est["price"]["unit"] == "ft"
    assert est["price"]["type"] == "length"
    assert est["price"]["unit_cost"] == 18.75
    assert est["total"] == 1125.00
    start, end = est["wall"]["pdf_points"]["start"], est["wall"]["pdf_points"]["end"]
    assert end[0] - start[0] == pytest.approx(60.0 * practice.PPU)
    assert end[1] == start[1]


def test_plan_set_uses_the_practice_sheets_and_scale(tmp_path):
    root = tmp_path / "sandbox"
    path = practice_job.generate_plan_set(root)
    assert os.path.abspath(path) == os.path.abspath(
        os.path.join(root, practice_job.PLAN_NAME))
    doc = fitz.open(path)
    try:
        assert doc.page_count == 4
        text = doc[0].get_text()
        assert "PRACTICE CLINIC" in text
        assert "A-101" in text
        assert '1/4" = 1\'-0"' in text
        scales = read_scales(doc)
        for page in (0, 1, 2):
            assert scales[page]["ppu"] == practice.PPU
            assert scales[page]["unit"] == "ft"
        # the south wall's outside face is a 60 ft line at the known origin
        want = practice_job.wall_points()
        found = False
        for drawing in doc[0].get_drawings():
            for item in drawing.get("items") or []:
                if item[0] != "l":
                    continue
                a, b = item[1], item[2]
                if (abs(a.x - want["start"][0]) < 1 and
                        abs(a.y - want["start"][1]) < 1 and
                        abs(b.x - want["end"][0]) < 1 and
                        abs(b.y - want["end"][1]) < 1):
                    found = True
        assert found
    finally:
        doc.close()


def test_prepare_keeps_an_existing_plan_until_refresh(tmp_path):
    root = tmp_path / "sandbox"
    info = practice_job.prepare(root)
    kept = info["plan"]
    with open(kept, "wb") as f:
        f.write(b"keep-this-plan")
    again = practice_job.prepare(root)
    assert again["plan"] == kept
    with open(kept, "rb") as f:
        assert f.read() == b"keep-this-plan"
    practice_job.prepare(root, refresh=True)
    with open(kept, "rb") as f:
        assert f.read().startswith(b"%PDF")


def test_price_and_export_stay_on_the_sample_line(tmp_path):
    root = tmp_path / "sandbox"
    info = practice_job.prepare(root)
    doc = fitz.open(info["plan"])
    try:
        practice_job.place_sample_wall(doc)
        prices = practice_job.apply_sample_price(doc)
        key = "South Exterior Wall|length|ft"
        assert prices[key]["unit_cost"] == 18.75
        assert prices[key]["code"] == "PRACTICE"
        practice_job.save_plan(doc, root)
        csv_path = practice_job.export_csv(doc, root)
    finally:
        doc.close()
    assert os.path.abspath(csv_path).startswith(os.path.abspath(root) + os.sep)
    text = open(csv_path, encoding="utf-8-sig").read()
    assert "South Exterior Wall" in text
    assert "1125.00" in text or "1125" in text
    saved = fitz.open(info["plan"])
    try:
        from app import estimate
        assert estimate.read_prices(saved)[key]["unit_cost"] == 18.75
    finally:
        saved.close()


def test_progress_resumes_the_step_the_user_reached():
    assert practice_job.progress() is None
    assert practice_job.resume()["id"] == "open"
    practice_job.record_step("measure")
    settings._cache = None
    assert practice_job.progress() == "measure"
    assert practice_job.resume()["id"] == "measure"
    assert json.loads(open(settings.PATH, encoding="utf-8").read())[
        practice_job.SETTINGS_KEY] == "measure"
    practice_job.reset_progress()
    settings._cache = None
    assert practice_job.progress() is None
    with pytest.raises(ValueError):
        practice_job.record_step("publish")


def test_default_sandbox_is_its_own_folder():
    path = practice_job.sandbox_dir()
    assert os.path.basename(path) == "practice-job"
    assert os.path.dirname(path) == os.path.abspath(settings.DIR)
    assert not path.endswith("Practice Drawings.pdf")
    with pytest.raises(practice_job.SandboxError):
        practice_job.sandbox_dir(settings.DIR)


def test_refuses_user_folders_and_paths_outside_the_sandbox(tmp_path):
    home = os.path.abspath(os.path.expanduser("~"))
    for name in ("Documents", "Desktop", "Downloads"):
        with pytest.raises(practice_job.SandboxError):
            practice_job.prepare(os.path.join(home, name, "practice-job"))
        assert not os.path.exists(os.path.join(
            home, name, "practice-job", practice_job.PLAN_NAME))
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = str(tmp_path / "outside.pdf")
    with pytest.raises(practice_job.SandboxError):
        practice_job._require_inside(outside, str(root))
    with pytest.raises(practice_job.SandboxError):
        practice_job._require_inside(str(root / ".." / "outside.pdf"), str(root))


def test_nothing_is_written_outside_the_sandbox(tmp_path):
    """Job files stay in the sandbox. Settings may hold only the step id."""
    home = os.path.abspath(os.path.expanduser("~"))
    for name in ("Documents", "Desktop", "Downloads", "Jobs"):
        folder = os.path.join(home, name)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "leave-me.txt"), "w", encoding="utf-8") as f:
            f.write("untouched")
    project = os.path.join(home, "Jobs", "River Clinic")
    os.makedirs(project, exist_ok=True)
    with open(os.path.join(project, "real.pdf"), "wb") as f:
        f.write(b"%PDF-real")

    sandbox = tmp_path / "sandbox"
    before_home = _snapshot(home)
    before_tmp = _snapshot(str(tmp_path))

    info = practice_job.prepare(sandbox)
    doc = fitz.open(info["plan"])
    try:
        practice_job.place_sample_wall(doc)
        practice_job.apply_sample_price(doc)
        practice_job.save_plan(doc, sandbox)
        practice_job.export_csv(doc, sandbox)
    finally:
        doc.close()
    practice_job.record_step("export")
    practice_job.write_estimate(sandbox)

    after_home = _snapshot(home)
    after_tmp = _snapshot(str(tmp_path))
    sandbox_abs = os.path.abspath(sandbox)
    settings_abs = os.path.abspath(settings.PATH)

    def _allowed(path):
        path = os.path.abspath(path)
        if path == settings_abs:
            return True
        return os.path.commonpath([sandbox_abs, path]) == sandbox_abs

    home_changed = {p for p in set(before_home) | set(after_home)
                    if before_home.get(p) != after_home.get(p)}
    tmp_changed = {p for p in set(before_tmp) | set(after_tmp)
                   if before_tmp.get(p) != after_tmp.get(p)}
    changed = home_changed | tmp_changed
    leaked = [p for p in changed if not _allowed(p)]
    assert leaked == [], leaked

    written = json.loads(open(settings.PATH, encoding="utf-8").read())
    assert list(written) == [practice_job.SETTINGS_KEY]
    assert written[practice_job.SETTINGS_KEY] == "export"
    cfg_files = []
    for dirpath, _dirs, filenames in os.walk(settings.DIR):
        for name in filenames:
            cfg_files.append(os.path.join(dirpath, name))
    assert cfg_files == [settings.PATH]
    assert os.path.isfile(os.path.join(
        home, "Documents", "leave-me.txt"))
    assert not os.path.exists(os.path.join(
        settings.DIR, "Practice Drawings.pdf"))
