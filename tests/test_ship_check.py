"""Research briefs, reviews, notes for Claude, private/ and Xactimate /
SageSure / EagleView material never ship (review 0.12.35 #21). The check
works on names, so the files needn't exist here."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import ship_check  # noqa: E402

NEVER = ["XACTIMATE_SAGESURE_EAGLEVIEW_DEEP_DIVE.md",
         "XACTIMATE_SAGESURE_EAGLEVIEW_DEEP_DIVE.pdf",
         "ROOF_PLAN_TAKEOFF_BRIEF.md", "ROOF_PLAN_TAKEOFF_BRIEF.pdf",
         "FOR_CLAUDE_NEXT_STEPS.txt", "for_claude_notes.txt",
         "private/Client Job 12.pdf", "app/data/private/plan.pdf",
         "REVIEW_0_12_34.md", "Outside Review 0.12.35.pdf",
         "STRATEGY_NOTES.md", "app/data/claim.esx",
         "_internal/app/data/ROOF_PLAN_TAKEOFF_BRIEF.md",
         "_internal/eagleview_sample.json",
         "app\\data\\XACTIMATE_PRICES.csv"]
OK = ["README.md", "quantisheet.py", "app/genset/brief.py", "app/ai/review.py",
      "app/autotakeoff_review.py", "app/data/ada2010.json",
      "docs/IT_DEPLOYMENT.md", "QuantiSheet 0.12.35 - Whats New.pdf",
      "QuantiSheet-Beta-Setup-0.12.35.exe", "READ ME FIRST.txt",
      "QuantiSheet 0.12.40 - Whats New.pdf",
      "QuantiSheet-Beta-Setup-0.12.40.exe", "QuantiSheet-Beta-0.12.40.msi",
      "QuantiSheet 0.12.40 SHA256.txt",
      "BETA-AGREEMENT.txt", "_internal/app/data/beta_pubkey.txt",
      "_internal/PySide6/Qt6Core.dll", "_internal/LICENSE.txt"]


@pytest.mark.parametrize("name", NEVER)
def test_research_and_private_files_are_refused(name):
    assert ship_check.why(name), name


@pytest.mark.parametrize("name", OK)
def test_program_files_pass(name):
    assert ship_check.why(name) is None, name


def test_require_clean_names_the_files_and_raises():
    with pytest.raises(RuntimeError) as e:
        ship_check.require_clean(OK + NEVER[:3], "the zip")
    msg = str(e.value)
    assert "the zip" in msg and "ROOF_PLAN_TAKEOFF_BRIEF.md" in msg
    assert ship_check.require_clean(OK) == []


def test_scan_tree_finds_them_in_a_built_folder(tmp_path):
    d = tmp_path / "QuantiSheet" / "_internal" / "app" / "data"
    d.mkdir(parents=True)
    (d / "ada2010.json").write_text("{}")
    root = tmp_path / "QuantiSheet"
    assert ship_check.scan_tree(str(root)) == []
    (d / "ROOF_PLAN_TAKEOFF_BRIEF.md").write_text("made-up")
    (root / "FOR_CLAUDE_TODO.txt").write_text("made-up")
    found = ship_check.scan_tree(str(root))
    assert len(found) == 2
    with pytest.raises(RuntimeError):
        ship_check.require_clean(str(root), "the built program")


def test_build_checks_what_it_packages_not_the_whole_source_folder(
        tmp_path, monkeypatch):
    """The source folder on Jon's PC has the briefs at its top level; they
    aren't packaged, so the build passes - until one lands in app/."""
    import build_installer as bi
    (tmp_path / "app" / "data").mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (tmp_path / "quantisheet.py").write_text("")
    for n in NEVER[:5]:
        (tmp_path / n).write_text("made-up")
    monkeypatch.setattr(bi, "ROOT", str(tmp_path))
    srcs = bi.packaged_sources()
    assert "quantisheet.py" in srcs
    assert ship_check.require_clean(srcs) == []
    (tmp_path / "app" / "data" / "ROOF_PLAN_TAKEOFF_BRIEF.pdf").write_text(
        "made-up")
    with pytest.raises(RuntimeError):
        ship_check.require_clean(bi.packaged_sources(), "the program folder")


def test_source_zip_leaves_them_out():
    import zip_source
    for n in NEVER:
        assert not zip_source.wanted(n), n
    assert zip_source.wanted("app/genset/brief.py")
    assert zip_source.wanted("docs/RELEASE_CHECKLIST.md")


def test_installer_scripts_exclude_the_research_names():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for iss in ("quantisheet.iss", "quantisheet_server.iss",
                "quantisheet_claims.iss"):
        with open(os.path.join(root, "installer", iss),
                  encoding="utf-8", errors="replace") as f:
            text = f.read()
        assert f'Excludes: "{ship_check.INNO_EXCLUDES}"' in text, iss
    with open(os.path.join(root, "quantisheet.spec"), encoding="utf-8") as f:
        assert "ship_check.require_clean" in f.read()


# review of tonight's changes #6: private/ folders and reviews outside app/
# and docs/ - every folder zip_source packages, and the built program
ELSEWHERE_NEVER = ["tests/data/private/Smith Residence plans.pdf",
                   "data/private/client.pdf", "server/private/x.pdf",
                   "installer/private/notes.txt",
                   "quantisheet_claims/private/claim.pdf",
                   "tests/private/photo.jpg",
                   "_internal/somepkg/Private/scan.png",
                   "tests/data/review notes.md", "server/REVIEW_0_12_36.md",
                   "quantisheet_claims/Outside-Review.pdf",
                   "data/peer_review.docx"]
ELSEWHERE_OK = ["_internal/somepkg/_private.py",
                "_internal/somepkg/private_api/data.txt",
                "_internal/somepkg/privatedata/x.json",
                "_internal/PySide6/include/QtCore/private/qobject_p.h",
                "_internal/somepkg/private/helpers.py",
                "_internal/somepkg/private/mod.pyd",
                "tests/test_review_queue.py", "server/review.py",
                "_internal/somepkg/templates/preview.html",
                "tests/data/print preview.txt"]


@pytest.mark.parametrize("name", ELSEWHERE_NEVER)
def test_private_and_reviews_refused_in_every_folder(name):
    assert ship_check.why(name), name


@pytest.mark.parametrize("name", ELSEWHERE_OK)
def test_third_party_private_modules_and_code_pass(name):
    assert ship_check.why(name) is None, name


def test_source_zip_leaves_out_private_folders_everywhere():
    import zip_source
    for n in ELSEWHERE_NEVER:
        if not n.startswith("_internal/"):
            assert not zip_source.wanted(n), n
    assert zip_source.wanted("tests/test_review_queue.py")


# review 0.12.38 #11: licensed cost-book data never ships; the RSMeans
# importer module (code) does
LICENSED_NEVER = ["RSMeans assemblies.txt", "rsmeans assemblies.txt",
                  "app/data/RSMeans_2026.csv", "data/RS Means unit costs.xlsx",
                  "_internal/app/data/rs-means.json", "Gordian 2026.pdf",
                  "Craftsman National Estimator 2026.txt",
                  "app/data/national_construction_estimator.csv",
                  "data/bni_unit_costs.csv", "eConverge export.csv",
                  "BNi 2026 Costbook.xlsx", "app/data/building news.json"]
LICENSED_OK = ["app/rsmeans.py", "_internal/app/rsmeans.pyc",
               "app/__pycache__/rsmeans.cpython-313.pyc",
               "tests/test_starter_costbook.py",
               "app/data/styles/craftsman.json",
               "app/bni_import.py", "app/data/combined_costs.csv",
               "app/data/ebnight.json"]


@pytest.mark.parametrize("name", LICENSED_NEVER)
def test_licensed_cost_data_is_refused(name):
    w = ship_check.why(name)
    assert w and "licensed cost data" in w, (name, w)


@pytest.mark.parametrize("name", LICENSED_OK)
def test_cost_data_importer_code_passes(name):
    assert ship_check.why(name) is None, name


def test_no_app_file_is_licensed_cost_data():
    """Nothing the program packages today matches the licensed names."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for sub in ("app", "data"):
        top = os.path.join(root, sub)
        if not os.path.isdir(top):
            continue
        for base, _dirs, files in os.walk(top):
            for f in files:
                rel = os.path.relpath(os.path.join(base, f), root)
                w = ship_check.why(rel) or ""
                assert "licensed cost data" not in w, rel
