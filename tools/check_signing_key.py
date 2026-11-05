"""Is the license signing key on this PC? (Prints yes/no only - never the
key.)  python tools/check_signing_key.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beta_keys  # noqa: E402

print("signing key present:", os.path.exists(beta_keys.PRIV))
