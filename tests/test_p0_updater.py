"""Updater checks from the Nov 4 review (QS-007, Part F, policy drift)."""
import os

from app import policy, updatecheck


def test_signed_by_needs_valid_and_the_right_certificate():
    good = "A" * 40
    assert updatecheck.signed_by("x.exe", good,
                                 run=lambda cmd: f"Valid|{good}\n")
    assert not updatecheck.signed_by("x.exe", good,
                                     run=lambda cmd: "Valid|" + "B" * 40)
    assert not updatecheck.signed_by("x.exe", good,
                                     run=lambda cmd: f"NotSigned|{good}")
    assert not updatecheck.signed_by("x.exe", good, run=lambda cmd: 1 / 0)


def test_unsigned_installer_refused_when_manifest_names_a_signer(
        tmp_path, monkeypatch):
    p = tmp_path / "QuantiSheet-Team-Setup-9.9.9.exe"
    p.write_bytes(b"setup")
    info = {"sha256": updatecheck.sha256_file(str(p)), "size": 5,
            "signer": "C" * 40}
    monkeypatch.setattr(updatecheck, "signed_by", lambda path, t: False)
    ran = []
    try:
        updatecheck.launch_installer(str(p), info, run=ran.append)
        assert False, "should refuse"
    except updatecheck.HashMismatch:
        pass
    assert not ran
    info["signer"] = ""                    # no certificate yet: as before
    assert updatecheck.launch_installer(str(p), info, run=ran.append)
    assert ran


def test_previous_installer_is_kept_for_going_back(tmp_path, monkeypatch):
    for v in ("1.0.5", "1.0.6", "1.0.7", "1.1.1"):
        (tmp_path / f"QuantiSheet-Team-Setup-{v}.exe").write_bytes(b"x")
    monkeypatch.setattr(updatecheck, "current_version", lambda: "1.0.7")
    updatecheck.tidy(keep_version="1.1.1", folder=str(tmp_path))
    left = sorted(os.listdir(tmp_path))
    assert left == ["QuantiSheet-Team-Setup-1.0.7.exe",
                    "QuantiSheet-Team-Setup-1.1.1.exe"]
    assert updatecheck.previous_installer(str(tmp_path), "1.1.1") \
        .endswith("1.0.7.exe")
    assert updatecheck.previous_installer(str(tmp_path), "1.0.7") is None


def test_package_status_policy_is_defined():
    assert "DisablePackageStatus" in policy.SETTINGS
    assert "packages" in policy.NETWORK


def test_cannot_check_the_signature_means_do_not_install(tmp_path,
                                                         monkeypatch):
    """Review (Nov 4): PowerShell blocked -> fail closed, say what to do."""
    assert updatecheck.signed_by("x.exe", "A" * 40,
                                 run=lambda cmd: 1 / 0) is None
    assert updatecheck.signed_by("x.exe", "A" * 40,
                                 run=lambda cmd: "") is None
    p = tmp_path / "QuantiSheet-Team-Setup-9.9.9.exe"
    p.write_bytes(b"setup")
    info = {"sha256": updatecheck.sha256_file(str(p)), "size": 5,
            "signer": "C" * 40}
    monkeypatch.setattr(updatecheck, "signed_by", lambda path, t: None)
    ran = []
    try:
        updatecheck.launch_installer(str(p), info, run=ran.append)
        assert False, "should refuse"
    except updatecheck.HashMismatch as e:
        assert "by hand" in str(e)
    assert not ran


def test_reinstall_previous_version_runs_the_kept_installer(tmp_path,
                                                            monkeypatch):
    """Review 2 (Nov 4): a real way back, with the read-only warning."""
    from app import updatecheck_ui as U
    p = tmp_path / "QuantiSheet-Team-Setup-1.0.6.exe"
    p.write_bytes(b"setup")
    monkeypatch.setattr(updatecheck, "previous_installer", lambda *a: str(p))
    asked, ran = [], []
    assert U.reinstall_previous(None, ask=lambda t: asked.append(t) or True,
                                run=ran.append) == str(p)
    assert ran == [[str(p)]]
    assert "1.0.6" in asked[0] and "saving" in asked[0]
    assert U.reinstall_previous(None, ask=lambda t: False,
                                run=ran.append) is None
    assert len(ran) == 1
