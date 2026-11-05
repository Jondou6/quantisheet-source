"""The company contact list shipped with tester builds, sealed with a
password (AES via Fernet, key from PBKDF2-SHA256). The password is not
in the program: the person who opens it types it once, and the contacts
are added to their own Company Directory.

    seal(contacts, password) -> bytes        (tools/seal_contacts.py)
    unseal(blob, password) -> [contacts]     (raises WrongPassword)
"""
import base64
import json
import os

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                    "contacts.sealed")
ITERATIONS = 390_000


class WrongPassword(ValueError):
    pass


def _key(password, salt, iterations=ITERATIONS):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt,
                     iterations=iterations)
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def seal(contacts, password):
    from cryptography.fernet import Fernet
    if not password:
        raise ValueError("A password is needed.")
    salt = os.urandom(16)
    token = Fernet(_key(password, salt)).encrypt(
        json.dumps({"contacts": contacts}).encode("utf-8"))
    return json.dumps({"v": 1, "kdf": "pbkdf2-sha256",
                       "iterations": ITERATIONS,
                       "salt": base64.b64encode(salt).decode("ascii"),
                       "token": token.decode("ascii")}).encode("utf-8")


def unseal(blob, password):
    from cryptography.fernet import Fernet, InvalidToken
    d = json.loads(blob.decode("utf-8") if isinstance(blob, bytes) else blob)
    key = _key(password or "", base64.b64decode(d["salt"]),
               int(d.get("iterations", ITERATIONS)))
    try:
        raw = Fernet(key).decrypt(d["token"].encode("ascii"))
    except InvalidToken:
        raise WrongPassword("That password is not right.") from None
    return json.loads(raw.decode("utf-8")).get("contacts", [])


def available():
    return os.path.exists(FILE)


def import_into_directory(password, path=None):
    """Unlock the shipped list and add it to this computer's Company
    Directory. Returns (added, updated, total)."""
    from . import subdir
    with open(path or FILE, "rb") as f:
        contacts = unseal(f.read(), password)
    return subdir.merge(contacts)
