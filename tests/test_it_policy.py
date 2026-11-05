"""IT department settings (Group Policy / policy.json), the support bundle
and the command line for both (0.12.17)."""
import json
import os
import re
import zipfile

import pytest

from app import policy


@pytest.fixture(autouse=True)
def own_settings(tmp_path, monkeypatch):
    """Never the real settings file on this PC."""
    from app import settings
    d = tmp_path / "home"
    d.mkdir()
    monkeypatch.setattr(settings, "DIR", str(d))
    monkeypatch.setattr(settings, "PATH", str(d / "settings.json"))
    monkeypatch.setattr(settings, "_cache", {})


@pytest.fixture
def it(tmp_path, monkeypatch):
    """Write policy.json and reload: it(DisableAI=True, ...)."""
    path = tmp_path / "policy.json"

    def set_(**kw):
        path.write_text(json.dumps(kw))
        monkeypatch.setenv("QUANTISHEET_POLICY_FILE", str(path))
        policy.reload()
    return set_


def test_no_policy_by_default():
    assert policy.all_set() == {}
    assert all(policy.allowed(c) for c in policy.NETWORK)


def test_registry_wins_over_the_file(it, monkeypatch):
    it(PriceDatabasePath=r"\\file\prices.db", DisableAI=1)
    monkeypatch.setattr(policy, "_from_registry",
                        lambda: {"PriceDatabasePath": r"\\gpo\prices.db",
                                 "Nonsense": 1})
    policy.reload()
    assert policy.get("PriceDatabasePath") == r"\\gpo\prices.db"
    assert policy.on("DisableAI")                 # from the file
    assert "Nonsense" not in policy.all_set()


def test_offline_mode_blocks_every_internet_feature(it):
    it(OfflineMode="true")
    for cat in ("aerial", "weather", "rates", "docusign"):
        with pytest.raises(policy.Blocked, match="IT department"):
            policy.check(cat, "https://example.gov/x")
    assert policy.allowed("ai")             # local AI is separate


def test_aerial_and_weather_respect_the_policy(it):
    from app import aerial
    from app.pm import weather
    it(DisableAerial=1, DisableWeather=1)
    with pytest.raises(policy.Blocked, match="DisableAerial"):
        aerial._get(aerial.GEOCODE_URL, {"address": "x"})
    with pytest.raises(policy.Blocked, match="DisableWeather"):
        weather._get("https://api.open-meteo.com/v1/forecast")


def test_ai_off_and_another_host(it):
    from app.ai import review
    from app.genset import brief
    it(DisableAI=1)
    with pytest.raises(review.AIError, match="IT department"):
        review._ollama("hi")
    assert brief.ai_up() is False
    it(AIHost="http://ai-server:11434")
    assert review._allowed_host("http://localhost:11434") == \
        "http://ai-server:11434"


def test_price_database_set_by_it_cannot_be_moved(it, tmp_path):
    from app import pricedb
    target = str(tmp_path / "shared" / "prices.db")
    it(PriceDatabasePath=target)
    assert pricedb.path() == target and pricedb.managed()
    with pytest.raises(RuntimeError, match="IT department"):
        pricedb.use(str(tmp_path / "mine.db"))
    with pytest.raises(RuntimeError, match="IT department"):
        pricedb.use_local()


def test_relay_address_from_it(it):
    from app.collab import hubclient
    it(RelayURL="ws://quantisheet-relay:8765")
    assert hubclient.default_url() == "ws://quantisheet-relay:8765"


def _gpo(monkeypatch, **kw):
    """Settings as Group Policy writes them (the registry)."""
    monkeypatch.setattr(policy, "_from_registry", lambda: dict(kw))
    policy.reload()


def test_it_skips_the_prompts(it, monkeypatch):
    from app import onboard
    assert not onboard.signed_in()
    _gpo(monkeypatch, SkipEmailSignIn=1, AcceptAgreement=1)
    assert onboard.signed_in()


def test_policy_json_cannot_unlock_prompts(it, monkeypatch):
    """Fable review S1: a user could write policy.json where IT hasn't
    made the folder - it may not turn off the sign-in, the agreement or
    supply the license."""
    from app import onboard
    it(SkipEmailSignIn=1, AcceptAgreement=1, LicenseKey="X" * 20,
       DisableAI=1)
    assert not onboard.signed_in()
    assert "LicenseKey" not in policy.all_set()
    assert policy.on("DisableAI")              # the harmless ones still work


def test_policy_file_location_ignores_the_environment(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    # the real lookup (conftest points ProgramData at the test home); it
    # only builds the path - nothing in ProgramData is read or written
    monkeypatch.setattr(policy, "_program_data", policy._real_program_data)
    monkeypatch.setenv("QUANTISHEET_POLICY_FILE", r"D:\IgnoreThis\p.json")
    monkeypatch.setenv("PROGRAMDATA", r"D:\IgnoreThis")
    path = policy._file()
    assert "IgnoreThis" not in path and path.endswith("policy.json")


def test_it_license_key_used_when_the_user_has_none(it, monkeypatch):
    from app import betalicense
    monkeypatch.setattr(betalicense, "check", lambda k, *a, **kw: (
        k == "IT-KEY", {"n": "Office", "x": "2099-01-01"}, ""))
    assert betalicense.current() is None
    _gpo(monkeypatch, LicenseKey="IT-KEY")
    assert betalicense.current()["n"] == "Office"
    assert policy.masked()["LicenseKey"] == "(set)"


def test_support_bundle_has_no_secrets(tmp_path, monkeypatch, it):
    from app import diagnostics, settings
    _gpo(monkeypatch, LicenseKey="ABCD-SECRET-SECRET-WXYZ", DisableAI=1)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "quantisheet.log").write_text(
        "INFO signed in as someone.person@example.com\nINFO ok\n")
    import app.main as main_mod
    monkeypatch.setattr(main_mod, "log_folder", lambda: str(log_dir))
    settings.set("docusign_token", "tok-123-very-private")
    out = diagnostics.bundle(str(tmp_path / "b.zip"))
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        rep = json.loads(z.read("report.json"))
        log = z.read("logs/quantisheet.log").decode()
        everything = b"".join(z.read(n) for n in names).decode("utf-8",
                                                               "replace")
    assert "someone.person@example.com" not in everything
    assert "[email removed]" in log
    assert "tok-123-very-private" not in everything
    assert "SECRET-SECRET" not in everything
    assert rep["policy"]["DisableAI"] is True
    assert "windows" in rep and "version" in rep
    assert any("docusign_token (value withheld)" == s
               for s in rep["settings"])


def test_cli_policy_and_diagnostics(tmp_path, capsys, it):
    from app import cli
    assert cli.main(["policy"]) == 0
    assert "No IT policy" in capsys.readouterr().out
    it(OfflineMode=1)
    assert cli.main(["--json", "policy"]) == 0
    assert json.loads(capsys.readouterr().out) == {"OfflineMode": True}
    out = str(tmp_path / "s.zip")
    assert cli.main(["diagnostics", "--out", out]) == 0
    assert zipfile.is_zipfile(out)


def test_admx_and_docs_list_every_setting():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    admx = open(os.path.join(root, "installer", "policy",
                             "QuantiSheet.admx"), encoding="utf-8").read()
    adml = open(os.path.join(root, "installer", "policy", "en-US",
                             "QuantiSheet.adml"), encoding="utf-8").read()
    doc = open(os.path.join(root, "docs", "IT_DEPLOYMENT.md"),
               encoding="utf-8").read()
    for name in policy.SETTINGS:
        assert f'valueName="{name}"' in admx or f'id="{name}"' in admx, name
        assert name in doc, name
    for cat, (_name, hosts) in policy.NETWORK.items():
        for h in hosts:
            assert h.split(" ")[0] in doc, h
    # every string the ADMX refers to is defined in the ADML
    for ref in set(re.findall(r"\$\(string\.(\w+)\)", admx)):
        assert f'id="{ref}"' in adml, ref
    for ref in set(re.findall(r"\$\(presentation\.(\w+)\)", admx)):
        assert f'id="{ref}"' in adml, ref


def test_every_weather_host_is_in_the_firewall_list(monkeypatch):
    """Every host weather._url() can send to - the free servers, and the
    customer-... ones a commercial API key switches to - is in the policy
    list IT opens in the firewall (and so in docs/IT_DEPLOYMENT.md)."""
    from urllib.parse import urlsplit
    from app.pm import weather
    src = open(weather.__file__, encoding="utf-8").read()
    bases = set(re.findall(r'"(https://[^"/]+/[^"]*)"', src))
    assert len({urlsplit(b).hostname for b in bases}) >= 3, bases
    listed = set(policy.NETWORK["weather"][1])
    for key in ("", "TEST-KEY-123"):
        monkeypatch.setattr(weather, "_api_key", lambda key=key: key)
        for b in bases:
            host = urlsplit(weather._url(b, {"q": 1})).hostname
            assert host in listed, (host, bool(key))
            assert host.startswith("customer-") == bool(key), host


def test_relay_token_file_is_made_once_and_reused(tmp_path):
    from app import cli
    p = str(tmp_path / "pd" / "relay-token.txt")
    a = cli._token_from_file(p)
    assert len(a) >= 24 and os.path.isfile(p)
    assert cli._token_from_file(p) == a


def test_relay_command_passes_tls_and_data_dir(tmp_path, monkeypatch):
    from app import cli
    from app.collab import relay
    seen = {}
    monkeypatch.setattr(relay, "run_relay", lambda *a, **k: seen.update(
        args=a, kw=k))
    monkeypatch.setattr(relay, "tls_context", lambda c, k: "CTX")
    tok = str(tmp_path / "t.txt")
    assert cli.main(["relay", "--token-file", tok, "--data-dir",
                     str(tmp_path / "hub"), "--cert", "c.pem", "--key",
                     "k.pem"]) == 0
    assert seen["kw"] == {"data_dir": str(tmp_path / "hub"),
                          "ssl_ctx": "CTX"}
    assert seen["args"][3] == open(tok).read().strip()
    assert cli.main(["relay", "--cert", "c.pem"]) == 1     # needs --key


def test_relay_token_policy(it):
    from app.collab import hubclient
    it(RelayToken="from-it")
    assert hubclient.default_token() == "from-it"
    assert policy.masked()["RelayToken"] == "(set)"


def test_public_build_always_needs_a_key(tmp_path, monkeypatch):
    from app import betalicense
    assert betalicense.edition() == "tester"      # the source folder
    monkeypatch.setattr(betalicense, "edition", lambda: "public")
    monkeypatch.setattr(betalicense, "KEY_REQUIRED", False)
    monkeypatch.delenv("QUANTISHEET_BETA", raising=False)
    import sys
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert betalicense.required()
    monkeypatch.setattr(betalicense, "edition", lambda: "tester")
    assert not betalicense.required()


def test_server_installer_matches_the_docs():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    iss = open(os.path.join(root, "installer", "quantisheet_server.iss"),
               encoding="utf-8").read()
    doc = open(os.path.join(root, "docs", "IT_DEPLOYMENT.md"),
               encoding="utf-8").read()
    # every command-line switch the installer reads is documented, and
    # writes a real policy name
    for m in re.finditer(r'ValueName: "(\w+)"; ValueData: "[^"]*"; Flags: '
                         r"uninsdeletevalue; Check: HasParam\('(\w+)'\)",
                         iss):
        name, param = m.groups()
        assert name in policy.SETTINGS, name
        assert f"/{param}=" in doc, param
    assert "PrivilegesRequired=admin" in iss
    app_id = re.search(r"AppId=\{\{([0-9A-F-]+)\}", iss).group(1)
    assert app_id in doc                         # the detection rule


def test_public_build_fails_closed(tmp_path, monkeypatch):
    """Fable review M2 / Venice review S4: an installed copy is a tester
    build only with the sealed contact list AND the build PC's signature on
    "tester" + this version. Adding an (empty) contacts.sealed and deleting
    build.json leaves it a public build that needs a key."""
    import sys
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PrivateKey
    from app import betalicense
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("QUANTISHEET_BETA", raising=False)
    real = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: (
        True if p.endswith("contacts.sealed") else real(p)))
    monkeypatch.setattr(betalicense, "tester_stamp_ok", lambda st: False)
    assert betalicense.edition() == "public" and betalicense.required()
    monkeypatch.setattr(betalicense, "tester_stamp_ok", lambda st: True)
    assert betalicense.edition() == "tester"
    monkeypatch.setattr(os.path, "isfile", lambda p: False)
    assert betalicense.edition() == "public"
    # the signature itself: right key and version only
    key = Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization
    pub = betalicense._b64e(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    monkeypatch.undo()
    stamp = betalicense.make_tester_stamp(key)
    assert betalicense.tester_stamp_ok(stamp, pub)
    assert not betalicense.tester_stamp_ok(dict(stamp, edition="public"), pub)
    other = betalicense.make_tester_stamp(key, "0.0.1")
    assert not betalicense.tester_stamp_ok(other, pub)      # another version
    forged = betalicense.make_tester_stamp(Ed25519PrivateKey.generate())
    assert not betalicense.tester_stamp_ok(forged, pub)
    assert not betalicense.tester_stamp_ok({}, pub)


def test_cli_version(capsys):
    from app import cli
    assert cli.main(["--json", "version"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["edition"] == "tester" and out["key_required"] is False


def test_it_relay_address_is_trusted(it, monkeypatch):
    """Fable review M3: the plain ws:// relay IT set up is used without
    each user ticking the in-house box; any other plain address isn't."""
    from app.collab import client
    it(RelayURL="ws://quantisheet-relay:8765")
    client.check_url("ws://quantisheet-relay:8765")
    with pytest.raises(client.InsecureRelay):
        client.check_url("ws://somewhere-else:8765")


def test_cli_version_to_a_file(tmp_path):
    from app import cli
    out = tmp_path / "v.json"
    assert cli.main(["version", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["edition"] == "tester"


def test_support_bundle_scrubs_keys_tokens_users_and_shares(tmp_path,
                                                            monkeypatch, it):
    """Venice review S5: secrets that reach a log line, the Windows user
    name and \\\\server\\share paths stay out of the support zip."""
    from app import diagnostics, settings
    _gpo(monkeypatch, LicenseKey="PDFS-ABCDEF-1234567890-ZYXW",
         RelayToken="tok_relay_998877665544")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setenv("USERNAME", "jsmithers")
    (log_dir / "quantisheet.log").write_text(
        "INFO key PDFS-ABCDEF-1234567890-ZYXW accepted\n"
        "INFO relay token tok_relay_998877665544\n"
        "INFO opened \\\\fileserver\\jobs\\x.pdf as jsmithers\n"
        "INFO docusign tok-123-very-private\n")
    import app.main as main_mod
    monkeypatch.setattr(main_mod, "log_folder", lambda: str(log_dir))
    settings.set("docusign_token", "tok-123-very-private")
    out = diagnostics.bundle(str(tmp_path / "b.zip"))
    with zipfile.ZipFile(out) as z:
        everything = b"".join(z.read(n) for n in z.namelist()).decode(
            "utf-8", "replace")
    for secret in ("PDFS-ABCDEF-1234567890-ZYXW", "tok_relay_998877665544",
                   "tok-123-very-private", "jsmithers", "fileserver"):
        assert secret not in everything, secret
    assert "[secret removed]" in everything and "[user]" in everything
