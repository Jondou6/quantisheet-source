"""tools/relay_cert.py writes a certificate where it is told and prints
the fingerprint. No file is left in the repo."""
import importlib.util
import os

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.path.join(ROOT, "tools", "relay_cert.py")
    spec = importlib.util.spec_from_file_location("relay_cert", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


relay_cert = _load()


def _load_cert(path):
    with open(path, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())


def test_directory_gets_a_cert_and_a_matching_key(tmp_path, capsys):
    folder = tmp_path / "relay"
    rc = relay_cert.main([str(folder), "--cn", "relay.example.test",
                          "--san", "10.1.2.3"])
    assert rc == 0
    cert_path = folder / "relay.crt"
    key_path = folder / "relay.key"
    assert cert_path.is_file() and key_path.is_file()
    cert = _load_cert(cert_path)
    key = serialization.load_pem_private_key(key_path.read_bytes(),
                                             password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    assert key.key_size == 2048
    assert cert.public_key().public_numbers() == key.public_key().public_numbers()
    assert b"ENCRYPTED" not in key_path.read_bytes()
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert cn == "relay.example.test"
    sans = cert.extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value
    assert "relay.example.test" in sans.get_values_for_type(x509.DNSName)
    assert "10.1.2.3" in [str(ip) for ip in sans.get_values_for_type(
        x509.IPAddress)]
    eku = cert.extensions.get_extension_for_class(
        x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    basic = cert.extensions.get_extension_for_class(
        x509.BasicConstraints).value
    assert basic.ca is False
    printed = capsys.readouterr().out
    assert relay_cert.fingerprint_sha256(str(cert_path)) in printed
    assert "PRIVATE" not in printed
    assert relay_cert.fingerprint_matches(
        cert.public_bytes(serialization.Encoding.PEM),
        printed.split("SHA-256 fingerprint: ", 1)[1].splitlines()[0])


def test_refuses_to_overwrite_unless_forced(tmp_path):
    folder = str(tmp_path / "out")
    first = relay_cert.main([folder, "--cn", "a.example.test"])
    assert first == 0
    cert = (tmp_path / "out" / "relay.crt").read_bytes()
    again = relay_cert.main([folder, "--cn", "b.example.test"])
    assert again == 2
    assert (tmp_path / "out" / "relay.crt").read_bytes() == cert
    forced = relay_cert.main([folder, "--cn", "b.example.test", "--force"])
    assert forced == 0
    assert (tmp_path / "out" / "relay.crt").read_bytes() != cert


def test_explicit_paths_and_fingerprint_forms(tmp_path):
    cert_path = tmp_path / "mine.crt"
    key_path = tmp_path / "mine.key"
    issued = relay_cert.generate(str(cert_path), str(key_path),
                                 cn="relay.example.test", days=30, bits=2048)
    assert issued.cert_path == str(cert_path)
    assert issued.fingerprint == relay_cert.fingerprint_sha256(str(cert_path))
    plain = issued.fingerprint.replace(":", "")
    assert relay_cert.fingerprint_matches(str(cert_path), plain.lower())
    assert relay_cert.fingerprint_matches(str(cert_path), "  " + issued.fingerprint)
    assert not relay_cert.fingerprint_matches(str(cert_path), "ab" * 32)
    assert not relay_cert.fingerprint_matches(str(cert_path), "not-a-fingerprint")
    with pytest.raises(FileExistsError):
        relay_cert.generate(str(cert_path), str(key_path), cn="relay.example.test")


def test_cli_requires_a_path_and_rejects_a_short_key(tmp_path, capsys):
    assert relay_cert.main([]) == 2
    folder = str(tmp_path / "x")
    assert relay_cert.main([folder, "--bits", "1024"]) == 2
    assert not (tmp_path / "x").exists()
    capsys.readouterr()


def test_destinations_for_a_folder_and_a_crt_path(tmp_path):
    folder = str(tmp_path / "newdir")
    cert, key = relay_cert.destinations(folder)
    assert cert.endswith(os.path.join("newdir", "relay.crt"))
    assert key.endswith(os.path.join("newdir", "relay.key"))
    crt = str(tmp_path / "relay.pem")
    cert, key = relay_cert.destinations(crt)
    assert cert == crt
    assert key == str(tmp_path / "relay.key")
