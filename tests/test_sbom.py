"""SBOM inventory against a fake package set. No network."""
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(ROOT, "tools", "sbom.py")
    spec = importlib.util.spec_from_file_location("sbom_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sbom = _load()


class _Meta(dict):
    def __init__(self, name, license_text="", expression="", classifiers=()):
        super().__init__({
            "Name": name,
            "License": license_text,
            "License-Expression": expression,
        })
        self._classifiers = list(classifiers)

    def get_all(self, key):
        if key == "Classifier":
            return list(self._classifiers)
        value = self.get(key)
        return [] if value in (None, "") else [value]


class FakeDist:
    def __init__(self, name, version, license_text="", expression="",
                 classifiers=()):
        self.version = version
        self.metadata = _Meta(name, license_text, expression, classifiers)


def _index(**packages):
    return {sbom.norm(name): dist for name, dist in packages.items()}


def _tree(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "\n".join([
            "GoodLib>=1.2",
            "CopyLib==3.0",
            "AfferoLib>=2",
            "LesserLib>=1 ; sys_platform == 'win32'",
            "MissingLib>=1",
            "# a comment, not a package",
            "",
        ]),
        encoding="utf-8",
    )
    (tmp_path / "quantisheet.spec").write_text(
        "\n".join([
            'hidden += collect_submodules("goodlib")',
            'hidden += collect_submodules("app")',
            "hidden += [",
            '    "CopyLib.extra",',
            '    "PySide6.QtCore",',
            "]",
        ]),
        encoding="utf-8",
    )
    return tmp_path


def _fake_index():
    return _index(**{
        "goodlib": FakeDist("GoodLib", "1.2.3", "MIT"),
        "copylib": FakeDist("CopyLib", "3.0.0", expression="GPL-3.0-only"),
        "afferolib": FakeDist("AfferoLib", "2.1.0", expression="AGPL-3.0-only"),
        "lesserlib": FakeDist("LesserLib", "1.0.0", expression="LGPL-3.0-only"),
        "pyside6": FakeDist("PySide6", "6.12.0", "LGPL"),
    })


def test_fake_set_flags_agpl_gpl_and_unknown(tmp_path):
    result = sbom.build(
        str(_tree(tmp_path)),
        index=_fake_index(),
        when=sbom.datetime(2026, 11, 4, tzinfo=sbom.timezone.utc),
        serial="urn:uuid:00000000-0000-4000-8000-000000000001",
    )
    by_name = {c["name"]: c for c in result["components"]}
    assert set(by_name) == {
        "goodlib", "copylib", "afferolib", "lesserlib", "missinglib", "pyside6",
    }
    assert "app" not in by_name
    assert by_name["goodlib"]["version"] == "1.2.3"
    assert by_name["goodlib"]["licenses"] == [{"license": {"id": "MIT"}}]
    sources = next(p["value"] for p in by_name["goodlib"]["properties"]
                   if p["name"] == "quantisheet:sources")
    assert "requirements.txt" in sources
    assert "quantisheet.spec" in sources

    flags = {name: flag for flag, name, _ver, _lic in result["loud"]}
    assert flags["copylib"] == "GPL"
    assert flags["afferolib"] == "AGPL"
    assert flags["missinglib"] == "UNKNOWN"
    assert "goodlib" not in flags
    assert "lesserlib" not in flags
    assert "pyside6" not in flags

    doc = result["document"]
    assert doc["bomFormat"] == "CycloneDX"
    assert doc["specVersion"] == "1.5"
    assert doc["metadata"]["component"]["name"] == "quantisheet"
    loud_count = next(p["value"] for p in doc["metadata"]["properties"]
                      if p["name"] == "quantisheet:loud_count")
    assert loud_count == "3"


def test_write_summary_is_loud_and_passed_index_skips_disk(tmp_path, monkeypatch):
    def boom():
        raise AssertionError("installed metadata was scanned")

    monkeypatch.setattr(sbom.importlib.metadata, "distributions", boom)
    result = sbom.build(
        str(_tree(tmp_path)),
        index=_fake_index(),
        serial="urn:uuid:00000000-0000-4000-8000-000000000002",
    )
    out = tmp_path / "out"
    cdx, txt = sbom.write(str(out), result)
    body = json.loads(open(cdx, encoding="utf-8").read())
    assert body["components"]
    text = open(txt, encoding="utf-8").read()
    assert "!!! LICENSE WARNING" in text
    assert "!!! GPL  copylib" in text
    assert "!!! AGPL  afferolib" in text
    assert "!!! UNKNOWN  missinglib" in text
    lesser_line = next(ln for ln in text.splitlines() if "lesserlib" in ln
                       and "version" not in ln)
    assert not lesser_line.startswith("!!!")


def test_main_exit_code_uses_the_fake_index(tmp_path, monkeypatch):
    index = _fake_index()
    monkeypatch.setattr(sbom, "installed_index", lambda: index)
    code = sbom.main(["--root", str(_tree(tmp_path)),
                      "--out", str(tmp_path / "release")])
    assert code == 2
    text = (tmp_path / "release" / sbom.TXT_NAME).read_text(encoding="utf-8")
    assert text.startswith("QuantiSheet third-party SBOM")
    data = json.loads((tmp_path / "release" / sbom.CDX_NAME).read_text(
        encoding="utf-8"))
    assert data["bomFormat"] == "CycloneDX"
    assert any(c["name"] == "missinglib" for c in data["components"])


def test_clean_set_has_no_warning(tmp_path):
    root = tmp_path
    (root / "requirements.txt").write_text("GoodLib>=1\n", encoding="utf-8")
    result = sbom.build(str(root), index=_index(
        goodlib=FakeDist("GoodLib", "1.0.0", "Apache-2.0")))
    assert result["loud"] == []
    text = sbom.summary_text(result)
    assert "No AGPL/GPL or unknown licenses." in text
    assert "!!!" not in text


def test_classifier_gpl_is_loud_and_lgpl_classifier_is_not():
    gpl = FakeDist(
        "CopyLib", "1",
        classifiers=["License :: OSI Approved :: GNU General Public License v3 (GPLv3)"],
    )
    lgpl = FakeDist(
        "LesserLib", "1",
        classifiers=["License :: OSI Approved :: GNU Lesser General Public License v3"],
    )
    assert sbom.loud_license(sbom.license_text(gpl)) == "GPL"
    assert sbom.loud_license(sbom.license_text(lgpl)) == ""
    # an SPDX "OR" is the user's choice: LGPL is one of the options
    both = FakeDist("Mix", "1", expression="LGPL-2.1-only OR GPL-2.0-only")
    assert sbom.loud_license(sbom.license_text(both)) == ""
    # a prose line naming both (no SPDX choice) stays loud
    assert sbom.loud_license("LGPL and GPL parts") == "GPL"


def test_source_does_not_fetch():
    text = open(sbom.__file__, encoding="utf-8").read()
    for banned in ("urllib", "requests", "http.client", "urlopen"):
        assert banned not in text
    assert "import socket" not in text
    assert "from socket" not in text


def test_real_repo_lists_bundled_names_without_reading_live_metadata(monkeypatch):
    def boom():
        raise AssertionError("installed metadata was scanned")

    monkeypatch.setattr(sbom.importlib.metadata, "distributions", boom)

    class AnyIndex(dict):
        def get(self, key, default=None):
            if key not in self:
                self[key] = FakeDist(key, "9.9.9", "MIT")
            return dict.get(self, key, default)

    result = sbom.build(ROOT, index=AnyIndex())
    names = {c["name"] for c in result["components"]}
    assert "pymupdf" in names
    assert "shapely" in names
    assert "modulor" in names
    assert "pyside6" in names
    assert "pywin32" in names
    assert "pytest" not in names
    assert "pyinstaller" not in names
    assert all(not c["name"].startswith("app") for c in result["components"])


def test_default_out_is_the_release_folder():
    assert sbom.default_out(ROOT) == os.path.join(ROOT, "release")


def test_marker_from_requirements_is_kept(tmp_path):
    result = sbom.build(str(_tree(tmp_path)), index=_fake_index())
    lesser = next(c for c in result["components"] if c["name"] == "lesserlib")
    marker = next(p["value"] for p in lesser["properties"]
                  if p["name"] == "quantisheet:marker")
    assert "sys_platform" in marker


def test_spdx_choice_takes_the_mildest_option():
    assert sbom.loud_license("LGPL-3.0-only OR GPL-2.0-only OR "
                             "GPL-3.0-only") == ""
    assert sbom.loud_license("GPL-3.0-only OR AGPL-3.0-only") == "GPL"
    # PyMuPDF's free option is AGPL; the other needs a paid licence
    assert sbom.loud_license("Dual Licensed - GNU AFFERO GPL 3.0 or "
                             "Artifex Commercial License") == "AGPL"
