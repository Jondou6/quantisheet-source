"""Make the signed version.json for the team copy's update check.

    # once, on the build PC: a new signing key (private key stays on this
    # PC - never in the repo, the installer, a release or a message)
    python tools/make_update_manifest.py new-key --key <private.pem>
        -> writes <private.pem> and app/data/update_pubkey.txt

    # each team release
    python tools/make_update_manifest.py sign --key <private.pem> \
        --installer release/QuantiSheet-Beta-Setup-1.0.2.exe \
        --url https://<download host>/QuantiSheet-Beta-Setup-1.0.2.exe \
        --notes-file release/team-notes-1.0.2.txt --out release/version.json

The version comes from app/__init__.py. The manifest is checked with the
program's own parse_manifest() before it is written, so a manifest this
tool writes is one the program accepts. Nothing is uploaded: publishing
version.json (and the installer) is a separate step Jon approves."""
import argparse
import datetime
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _pub_path():
    return os.path.join(ROOT, "app", "data", "update_pubkey.txt")


def new_key(key_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PrivateKey
    from app.betalicense import _b64e
    if os.path.exists(key_path):
        sys.exit(f"{key_path} exists - not overwritten")
    if os.path.commonpath([os.path.abspath(key_path), ROOT]) == ROOT:
        sys.exit("keep the private key outside the source folder")
    k = Ed25519PrivateKey.generate()
    os.makedirs(os.path.dirname(os.path.abspath(key_path)), exist_ok=True)
    with open(key_path, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM,
                                serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()))
    pub = k.public_key().public_bytes(serialization.Encoding.Raw,
                                      serialization.PublicFormat.Raw)
    with open(_pub_path(), "w", encoding="utf-8") as f:
        f.write(_b64e(pub) + "\n")
    print("wrote", key_path, "and", _pub_path())


def build(private_key, installer_bytes_path, url, notes, version,
          published=None):
    """The signed manifest as a dict ({"manifest": ..., "sig": ...})."""
    from app import updatecheck
    from app.betalicense import _b64e
    h = hashlib.sha256()
    size = 0
    with open(installer_bytes_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    m = {"channel": updatecheck.CHANNEL, "version": version, "url": url,
         "sha256": h.hexdigest(), "size": size, "notes": notes,
         "published": published or datetime.date.today().isoformat()}
    return {"manifest": m,
            "sig": _b64e(private_key.sign(updatecheck.signed_bytes(m)))}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("new-key")
    a.add_argument("--key", required=True)
    b = sub.add_parser("sign")
    b.add_argument("--key", required=True)
    b.add_argument("--installer", required=True)
    b.add_argument("--url", required=True)
    b.add_argument("--notes-file")
    b.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "new-key":
        return new_key(args.key)
    from cryptography.hazmat.primitives import serialization
    from app import __version__, updatecheck
    with open(args.key, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), None)
    notes = ""
    if args.notes_file:
        with open(args.notes_file, encoding="utf-8") as f:
            notes = f.read().strip()
    doc = build(key, args.installer, args.url, notes, __version__)
    raw = json.dumps(doc, indent=1, ensure_ascii=True).encode("ascii")
    updatecheck.parse_manifest(raw)          # the program must accept it
    with open(args.out, "wb") as f:
        f.write(raw)
    print("wrote", args.out, doc["manifest"]["version"],
          doc["manifest"]["sha256"])


if __name__ == "__main__":
    main()
