"""Public snapshot export: clean tree, no history, scan fails closed."""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import public_source  # noqa: E402


def _git(repo, *args, env=None):
    subprocess.check_call(
        ["git", "-c", "user.name=QuantiSheet",
         "-c", "user.email=noreply@quantisheet.invalid", *args],
        cwd=repo, env=env, stdout=subprocess.DEVNULL)


def _names(root):
    out = []
    for base, _dirs, files in os.walk(root):
        for name in files:
            out.append(os.path.relpath(os.path.join(base, name), root)
                       .replace("\\", "/"))
    return out


def test_gitignore_and_never_publish_rules():
    ignore = public_source.ignore_from_text([
        ("", "*.secret\nserver/data/\nrelease/\napp/onboard.py\n"),
    ])
    assert ignore.ignored("hidden.secret")
    assert ignore.ignored("sub/hidden.secret")
    assert ignore.ignored("server/data/secret")
    assert ignore.ignored("release/notes.txt")
    assert ignore.ignored("app/onboard.py")
    assert not ignore.ignored("app/main.py")
    assert not ignore.ignored("build.sh")
    assert public_source.exclude_reason("server/data/secret", ignore)
    assert public_source.exclude_reason(".env", None) == ".env*"
    assert public_source.exclude_reason("keys/a.pem", None) == "*.pem"
    assert public_source.exclude_reason("a.pfx", None) == "*.pfx"
    assert public_source.exclude_reason("a.p12", None) == "*.p12"
    assert public_source.exclude_reason(
        "app/data/company_sender.json", None) == "company_*.json"
    assert public_source.exclude_reason(
        "tools/public_source_scrub.json", None).endswith("scrub.json")
    assert public_source.exclude_reason("README.md", ignore) is None


def test_kept_email_is_not_a_username_hit(tmp_path):
    text = 'SUPPORT_EMAIL = "' + "jon" + "dou6@hotmail.com" + '"\n'
    (tmp_path / "issue_report.py").write_text(text, encoding="utf-8")
    assert public_source.scan(str(tmp_path)) == []


def test_username_windows_path_and_secret_fail(tmp_path):
    user = "jon" + "do"
    users = "Use" + "rs"
    (tmp_path / "note.txt").write_text(
        "C:" + "\\" + users + "\\" + user + "\\Desktop\n", encoding="utf-8")
    (tmp_path / "secret.bin").write_bytes(bytes(range(32)))
    (tmp_path / "ok.txt").write_text("x" * 32, encoding="utf-8")
    findings = public_source.scan(str(tmp_path))
    blob = "\n".join(findings)
    assert "note.txt" in blob and "username" in blob
    assert "Windows user path" in blob
    assert "secret.bin" in blob and "32-byte binary secret" in blob
    assert "ok.txt" not in blob


def test_scrubbed_string_fails_and_pending_does_not(tmp_path):
    scrub = public_source.load_scrub()
    enabled = public_source.enabled_strings(scrub)
    assert enabled
    (tmp_path / "leak.txt").write_text(enabled[0][1] + "\n", encoding="utf-8")
    findings = public_source.scan(str(tmp_path))
    assert any("scrubbed string" in f for f in findings)
    kept = [e for e in scrub["entries"] if e["id"] == "support-email"]
    pending = [e for e in scrub["entries"]           # owner: keep (Nov 4)
               if e["id"] == "partner-center-identity"]
    assert kept and kept[0]["status"] == "decided: keep" and not kept[0]["enabled"]
    assert pending and pending[0]["status"] == "decided: keep" and \
        not pending[0]["enabled"]
    folder = tmp_path / "keep"
    folder.mkdir()
    (folder / "mail.txt").write_text(kept[0]["strings"][0] + "\n", encoding="utf-8")
    (folder / "store.json").write_text(
        pending[0]["strings"][0] + "\n", encoding="utf-8")
    assert public_source.scan(str(folder)) == []


def test_export_drops_ignored_tracked_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "QuantiSheet"
    env["GIT_AUTHOR_EMAIL"] = "noreply@quantisheet.invalid"
    env["GIT_COMMITTER_NAME"] = "QuantiSheet"
    env["GIT_COMMITTER_EMAIL"] = "noreply@quantisheet.invalid"
    _git(repo, "init", "-b", "main", env=env)
    (repo / ".gitignore").write_text("*.secret\n", encoding="utf-8")
    (repo / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".env").write_text("TOKEN=nope\n", encoding="utf-8")
    (repo / "hidden.secret").write_text("tracked but ignored\n", encoding="utf-8")
    (repo / "app").mkdir()
    (repo / "app" / "onboard.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "company_acme.json").write_text("{}\n", encoding="utf-8")
    (repo / "sign.pem").write_text("not a real key\n", encoding="utf-8")
    data = repo / "server" / "data"
    data.mkdir(parents=True)
    (data / "secret").write_bytes(bytes(range(32)))
    _git(repo, "add", "-A", "-f", env=env)
    _git(repo, "commit", "-m", "fixture", env=env)
    out = tmp_path / "out"
    gate = tmp_path / "release_onboard.py"
    gate.write_text("RELEASE = True\n", encoding="utf-8")
    missing = public_source.export("HEAD", str(tmp_path / "no_gate"),
                                   repo=str(repo))
    assert not missing["ok"] and any("app/onboard.py: missing" in f
                                     for f in missing["findings"])
    result = public_source.export("HEAD", str(out), repo=str(repo),
                                  add={"app/onboard.py": str(gate)})
    assert result["ok"], result["findings"]
    names = _names(out)
    # the release's sign-in gate is in, never the copy git had
    assert (out / "app" / "onboard.py").read_text(encoding="utf-8") == \
        "RELEASE = True\n"
    assert "ok.py" in names
    assert "PUBLIC_SOURCE_README.md" in names
    assert ".git" not in names
    for banned in (".env", "hidden.secret",
                   "company_acme.json", "sign.pem", "server/data/secret",
                   "tools/public_source_scrub.json"):
        assert banned not in names
    readme = (out / "PUBLIC_SOURCE_README.md").read_text(encoding="utf-8")
    assert "AGPL-3.0" in readme
    assert "corresponding source" in readme
    assert result["sha"] in readme
    assert "quantisheet-source" in result["commands"]
    assert "noreply@quantisheet.invalid" in result["commands"]
    assert "QuantiSheet <noreply@quantisheet.invalid>" in result["commands"]
    assert not os.path.isdir(os.path.join(out, ".git"))
    # an injected secret, and an injected profile path, fail the scan
    (out / "planted.bin").write_bytes(bytes([255]) * 32)
    planted = public_source.scan(str(out))
    assert any("32-byte binary secret" in f for f in planted)
    os.remove(out / "planted.bin")
    user = "jon" + "do"
    (out / "planted.txt").write_text(
        "D:" + "/" + "Use" + "rs" + "/" + user + "/Desktop\n",
        encoding="utf-8")
    planted = public_source.scan(str(out))
    assert any("username" in f or "Windows user path" in f for f in planted)


def test_harness_skips_when_paths_are_unset(tmp_path):
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    for key in list(env):
        if key.startswith("QS_AIKEN_") or key.startswith("QS_COLLETON_") \
                or key == "QS_EVAL_SET":
            env.pop(key)
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "aiken_eval.py")],
        cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "skipping aiken" in proc.stdout
    assert "not set" in proc.stdout


def test_export_head_passes_and_injection_fails(tmp_path):
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        pytest.skip("not a git checkout (e.g. the owner's working folder)")
    out = tmp_path / "head"
    gate = tmp_path / "onboard.py"
    gate.write_text("# stand-in for the release's sign-in gate\n",
                    encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "public_source.py"),
         "HEAD", str(out), "--add", f"app/onboard.py={gate}"],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "public source scan passed" in proc.stdout
    assert "quantisheet-source" in proc.stdout
    assert "noreply@quantisheet.invalid" in proc.stdout
    names = _names(out)
    assert "PUBLIC_SOURCE_README.md" in names
    assert "tools/public_source_scrub.json" not in names
    assert "app/onboard.py" not in names
    assert "tools/unlock_code.py" not in names
    assert "app/issue_report.py" in names
    assert "installer/msix_identity.json" in names
    assert not os.path.exists(os.path.join(out, ".git"))
    (out / "planted.bin").write_bytes(bytes(range(32)))
    again = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "public_source.py"),
         "--scan", str(out)],
        cwd=ROOT, capture_output=True, text=True)
    assert again.returncode != 0
    assert "32-byte binary secret" in again.stdout
    os.remove(out / "planted.bin")
    needle = public_source.enabled_strings(public_source.load_scrub())[0][1]
    (out / "planted.txt").write_text(needle + "\n", encoding="utf-8")
    again = subprocess.run(
        [sys.executable, os.path.join(ROOT, "tools", "public_source.py"),
         "--scan", str(out)],
        cwd=ROOT, capture_output=True, text=True)
    assert again.returncode != 0
    assert "scrubbed string" in again.stdout


def test_placeholder_user_paths_are_allowed(tmp_path):
    """Nov 4: made-up and documentation paths are not personal data."""
    users = "Use" + "rs"
    lines = ["C:" + "\\" + users + "\\<name>\\x",
             "C:" + "\\\\" + users + "\\\\<name>",
             "C:" + "/" + users + "/x/OneDrive/a.pdf",
             "C:" + "\\" + users + "\\ExampleUser\\Documents",
             "C:" + "\\" + users + "\\Public\\Desktop",
             "C:" + "\\" + users + "\\%USERNAME%\\AppData"]
    (tmp_path / "doc.txt").write_text("\n".join(lines) + "\n",
                                      encoding="utf-8")
    assert public_source.scan(str(tmp_path)) == []
    (tmp_path / "real.txt").write_text(
        "C:" + "\\" + users + "\\RealPerson\\Desktop\n", encoding="utf-8")
    assert any("real.txt" in f and "Windows user path" in f
               for f in public_source.scan(str(tmp_path)))


def test_onboard_is_required_and_added(tmp_path):
    """Owner's decision (Nov 4): the sign-in gate goes to testers too."""
    assert "app/onboard.py" in public_source.REQUIRED_UNTRACKED
    assert "app/onboard.py" in public_source.ALWAYS_EXACT   # not from git
    assert public_source.exclude_reason("tools/unlock_code.py", None)
