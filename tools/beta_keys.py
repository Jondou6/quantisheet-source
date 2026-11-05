"""Make beta tester license keys.

    python tools/beta_keys.py init
        one time: make your signing key (kept in KEYS below, never shipped)
        and put its public half in app/data/beta_pubkey.txt
    python tools/beta_keys.py issue "Jane Smith" --email jane@x.com
            --company "Smith Builders" --days 60
        a key for one tester; also saved as a text file you can email
    python tools/beta_keys.py list
        every key issued so far

Back up the KEYS folder (a USB stick is fine). Without the signing key you
can't make keys that work with installers you have already sent out.
"""
import argparse
import csv
import datetime as dt
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

KEYS = os.environ.get("QUANTISHEET_KEYS") or os.path.join(
    os.path.expanduser("~"), "QuantiSheet Keys")
PRIV = os.path.join(KEYS, "beta_signing_key.pem")
LOG = os.path.join(KEYS, "issued_keys.csv")
PUB = os.path.join(ROOT, "app", "data", "beta_pubkey.txt")


def _load_priv():
    from cryptography.hazmat.primitives import serialization
    with open(PRIV, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def _pub_text(priv):
    from cryptography.hazmat.primitives import serialization
    from app.betalicense import _b64e
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw)
    return _b64e(raw)


def init():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PrivateKey
    os.makedirs(KEYS, exist_ok=True)
    if os.path.exists(PRIV):
        priv = _load_priv()
        print("signing key already exists:", PRIV)
    else:
        priv = Ed25519PrivateKey.generate()
        with open(PRIV, "wb") as f:
            f.write(priv.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
        with open(os.path.join(KEYS, "README.txt"), "w") as f:
            f.write("QuantiSheet beta signing key.\n\nKeep this folder "
                    "private and backed up. Anyone with "
                    "beta_signing_key.pem can make license keys.\n"
                    "Never put it in the program folder or send it to "
                    "anyone.\n")
        print("made signing key:", PRIV)
    pub = _pub_text(priv)
    with open(PUB, "w") as f:
        f.write(pub + "\n")
    print("public key:", pub)
    print("written to:", PUB)


def issue(name, email="", company="", days=60):
    from app import betalicense
    name, email, company = (str(v).strip().strip('"').strip()
                            for v in (name, email, company))
    priv = _load_priv()
    pub = _pub_text(priv)
    key = betalicense.make_key(priv, name, email, company, days)
    ok, info, msg = betalicense.check(key, pub, now=dt.date.today())
    assert ok, msg
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["key id", "name", "email", "company", "issued",
                        "ends", "key"])
        w.writerow([info["k"], info["n"], info["e"], info["c"], info["i"],
                    info["x"], key])
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip()
    path = os.path.join(KEYS, f"Key - {safe or info['k']}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"QuantiSheet beta license key for {name}\n"
                f"Valid until {info['x']}\n\n"
                "Run the QuantiSheet installer, open QuantiSheet, and paste "
                "this whole key when it asks:\n\n"
                f"{key}\n\n"
                "This key is for you only. Please don't share the key or "
                "the installer.\n")
    print(msg)
    print("key id:", info["k"])
    print("saved to:", path)
    print()
    print(key)
    return key


def list_keys():
    if not os.path.exists(LOG):
        print("no keys issued yet")
        return
    with open(LOG, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            print(f"{row['key id']}  {row['ends']}  {row['name']}"
                  f"  {row['company']}  {row['email']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("issue")
    p.add_argument("name")
    p.add_argument("--email", default="")
    p.add_argument("--company", default="")
    p.add_argument("--days", type=int, default=60)
    sub.add_parser("list")
    a = ap.parse_args(argv)
    if a.cmd == "init":
        init()
    elif a.cmd == "issue":
        issue(a.name, a.email, a.company, a.days)
    else:
        list_keys()


if __name__ == "__main__":
    main()
