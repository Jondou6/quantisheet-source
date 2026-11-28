"""tools/tag_release.py: tags each "QuantiSheet vX corresponding source"
commit that has no tag yet, never moves one (made-up repository answers,
no network)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools"))
import tag_release as t                                     # noqa: E402


def _fake(calls):
    def gh(*a):
        calls.append(a)
        if "/commits?" in a[0]:
            if "page=1" not in a[0]:
                return []
            return [{"sha": "c" * 40, "commit": {"message":
                     "QuantiSheet v1.1.33 corresponding source"}},
                    {"sha": "b" * 40, "commit": {"message":
                     "QuantiSheet v1.1.32 corresponding source\n\nmore"}},
                    {"sha": "9" * 40, "commit": {"message": "other work"}},
                    {"sha": "a" * 40, "commit": {"message":
                     "QuantiSheet v1.1.4 corresponding source"}}]
        if "/tags?" in a[0]:
            return [{"name": "v1.1.33"}] if "page=1" in a[0] else []
        return {}
    return gh


def test_lists_without_creating(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(t, "gh", _fake(calls))
    assert t.main([]) == 0
    assert "missing: v1.1.4 v1.1.32" in capsys.readouterr().out
    assert not any("git/refs" in c[0] for c in calls)


def test_creates_only_the_missing_tags_in_version_order(monkeypatch):
    calls = []
    monkeypatch.setattr(t, "gh", _fake(calls))
    t.main(["--create"])
    refs = [c for c in calls if "git/refs" in c[0]]
    assert [r[2] for r in refs] == ["ref=refs/tags/v1.1.4",
                                    "ref=refs/tags/v1.1.32"]
    assert refs[1][4] == "sha=" + "b" * 40
