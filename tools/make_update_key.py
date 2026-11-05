"""One time, on Jon's PC: the update-check signing key. The private key
goes in ~/QuantiSheet Keys (beside the license signing key, outside the
source folder - never in the repo, an installer, a release or a
message); the public half goes in app/data/update_pubkey.txt. Refuses to
overwrite an existing key."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import make_update_manifest                              # noqa: E402

KEYS = os.environ.get("QUANTISHEET_KEYS") or os.path.join(
    os.path.expanduser("~"), "QuantiSheet Keys")
make_update_manifest.new_key(os.path.join(KEYS, "update_signing_key.pem"))
