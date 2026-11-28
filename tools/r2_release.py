"""Put this version on the testers' update folder in one command, instead
of the Cloudflare website (Nov 25 optimization list: "One-command tester
release").

    python tools/r2_release.py setup     once: paste the R2 access key
    python tools/r2_release.py setup --from-file     the same, no typing:
                 reads ~/QuantiSheet Keys/r2_upload.json, a text file
                 {"account": "...", "key_id": "...", "secret": "..."},
                 keeps it encrypted and removes the plain file
    python tools/r2_release.py check     is a key saved? (shows no key)
    python tools/r2_release.py upload    upload this version's two files
    python tools/r2_release.py release   sign + upload + verify

`setup` is for Jon to run in a console window: it asks for the Cloudflare
account ID and an R2 API token's Access Key ID and Secret Access Key
(R2 > Manage API tokens > Create, "Object Read & Write" on the
quantisheet-updates bucket only) and keeps them encrypted for this
Windows user (DPAPI) in ~/QuantiSheet Keys/r2_upload.dat. They are never
printed, logged or put in the repo.

`upload` sends release/r2_upload/<folder>/team/QuantiSheet-Beta-Setup-
<version>.exe first and version.json last (so a tester never sees a
version.json whose installer isn't there yet), with S3 signature v4 over
https. `release` runs tools/sign_team_update.py, the upload, then
tools/verify_update.py. Nothing goes to testers unless Jon says so."""
import datetime
import hashlib
import hmac
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
KEYS = os.path.join(os.path.expanduser("~"), "QuantiSheet Keys")
CRED = os.path.join(KEYS, "r2_upload.dat")
BUCKET = "quantisheet-updates"
REGION = "auto"


# ---- S3 signature version 4 (no extra packages)
def _h(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sign(method, host, path, headers, payload_hash, key_id, secret,
         amz_date, region=REGION, query=""):
    """The Authorization header for one request. `headers` holds every
    header to sign except host, x-amz-date and x-amz-content-sha256."""
    h = {k.lower(): str(v).strip() for k, v in headers.items()}
    h.update({"host": host, "x-amz-date": amz_date,
              "x-amz-content-sha256": payload_hash})
    names = sorted(h)
    canon = "\n".join([method, urllib.parse.quote(path, safe="/~"), query,
                       "".join(f"{k}:{h[k]}\n" for k in names),
                       ";".join(names), payload_hash])
    day = amz_date[:8]
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                         hashlib.sha256(canon.encode()).hexdigest()])
    k = _h(_h(_h(_h(("AWS4" + secret).encode(), day), region), "s3"),
           "aws4_request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    return (f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, "
            f"SignedHeaders={';'.join(names)}, Signature={sig}")


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def put(cred, key, path, content_type, endpoint=None, now=None):
    """PUT one file to the bucket; returns the HTTP status."""
    endpoint = endpoint or f"https://{cred['account']}.r2.cloudflarestorage.com"
    u = urllib.parse.urlparse(endpoint)
    obj = f"/{BUCKET}/{key}"
    payload = _sha_file(path)
    amz = (now or datetime.datetime.now(datetime.timezone.utc)) \
        .strftime("%Y%m%dT%H%M%SZ")
    size = os.path.getsize(path)
    headers = {"content-type": content_type, "content-length": str(size)}
    auth = sign("PUT", u.netloc, obj, headers, payload, cred["key_id"],
                cred["secret"], amz)
    with open(path, "rb") as f:
        req = urllib.request.Request(
            endpoint.rstrip("/") + urllib.parse.quote(obj, safe="/~"),
            data=f, method="PUT")
        for k, v in headers.items():
            req.add_header(k, v)
        req.add_header("x-amz-date", amz)
        req.add_header("x-amz-content-sha256", payload)
        req.add_header("Authorization", auth)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.status
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode("utf-8", "replace")
            # an S3 error names the problem, never the secret
            raise SystemExit(f"upload refused: HTTP {e.code} "
                             f"{_err_code(body)}")


def _err_code(body):
    import re
    m = re.search(r"<Code>(\w+)</Code>", body)
    return m.group(1) if m else ""


# ---- the key, kept encrypted
def save_cred(cred, path=CRED):
    from app import secretstore
    blob = secretstore.protect(json.dumps(cred).encode("utf-8"), "R2 key")
    if blob is None:
        raise SystemExit("Windows DPAPI isn't available, so the key can't "
                         "be kept safely here.")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(blob)


def load_cred(path=CRED):
    from app import secretstore
    if not os.path.isfile(path):
        raise SystemExit("No R2 key on this PC yet: run "
                         "python tools/r2_release.py setup")
    with open(path, "rb") as f:
        return json.loads(secretstore.unprotect(f.read()).decode("utf-8"))


def setup():
    import getpass
    print("R2 upload key for the testers' update folder (kept encrypted for"
          " this Windows user; nothing is shown as you paste).")
    cred = {"account": input("Cloudflare account ID: ").strip(),
            "key_id": getpass.getpass("R2 Access Key ID: ").strip(),
            "secret": getpass.getpass("R2 Secret Access Key: ").strip()}
    if not all(cred.values()):
        raise SystemExit("all three are needed")
    save_cred(cred)
    print("saved. Next: python tools/r2_release.py release")


PLAIN = os.path.join(KEYS, "r2_upload.json")


def setup_from_file(plain=PLAIN, path=CRED):
    """Encrypt the key from a plain JSON file, then remove that file."""
    if not os.path.isfile(plain):
        raise SystemExit(f"no {plain}")
    with open(plain, encoding="utf-8-sig") as f:
        raw = json.load(f)
    cred = {k: str(raw.get(k) or "").strip()
            for k in ("account", "key_id", "secret")}
    if not all(cred.values()):
        raise SystemExit("the file needs account, key_id and secret")
    save_cred(cred, path)
    if load_cred(path) != cred:
        raise SystemExit("the saved key didn't read back; plain file kept")
    size = os.path.getsize(plain)
    with open(plain, "r+b") as f:            # blank it before removing
        f.write(b"\0" * size)
    os.remove(plain)
    print("saved (encrypted for this Windows user); the plain file is "
          "removed. Next: python tools/r2_release.py release")


def check(path=CRED):
    cred = load_cred(path)
    print("R2 key saved: account ID", len(cred["account"]), "characters,",
          "key ID", len(cred["key_id"]), "characters, secret",
          len(cred["secret"]), "characters (not shown)")


def verify_key(endpoint=None, path=CRED):
    """A read-only request (list one object) to prove the saved key works
    on the bucket. Prints the HTTP status only."""
    cred = load_cred(path)
    endpoint = endpoint or \
        f"https://{cred['account']}.r2.cloudflarestorage.com"
    u = urllib.parse.urlparse(endpoint)
    query = "list-type=2&max-keys=1"
    empty = hashlib.sha256(b"").hexdigest()
    amz = datetime.datetime.now(datetime.timezone.utc) \
        .strftime("%Y%m%dT%H%M%SZ")
    auth = sign("GET", u.netloc, f"/{BUCKET}", {}, empty, cred["key_id"],
                cred["secret"], amz, query=query)
    req = urllib.request.Request(f"{endpoint.rstrip('/')}/{BUCKET}?{query}")
    req.add_header("x-amz-date", amz)
    req.add_header("x-amz-content-sha256", empty)
    req.add_header("Authorization", auth)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
            print("the key works on the bucket: HTTP", r.status)
            return True
    except urllib.error.HTTPError as e:
        print("the key was refused: HTTP", e.code,
              _err_code(e.read()[:300].decode("utf-8", "replace")))
        return False


# ---- what to upload
def files(version=None):
    """[(bucket key, local path, content type)], installer first."""
    from app import __version__, updatecheck
    v = version or __version__
    folder = urllib.parse.urlparse(updatecheck.UPDATE_BASE).path.strip("/")
    team = os.path.join(ROOT, "release", "r2_upload", folder, "team")
    setup_exe = f"QuantiSheet-Beta-Setup-{v}.exe"
    out = [(f"{folder}/team/{setup_exe}", os.path.join(team, setup_exe),
            "application/vnd.microsoft.portable-executable"),
           (f"{folder}/team/version.json",
            os.path.join(team, "version.json"), "application/json")]
    for _k, p, _t in out:
        if not os.path.isfile(p):
            raise SystemExit(f"missing {os.path.basename(p)} - run "
                             "tools/sign_team_update.py first")
    with open(out[1][1], encoding="utf-8") as f:
        if (json.load(f).get("manifest") or {}).get("version") != v:
            raise SystemExit("version.json is for another version - run "
                             "tools/sign_team_update.py again")
    return out


def upload(endpoint=None, version=None):
    cred = load_cred()
    for key, path, ctype in files(version):
        st = put(cred, key, path, ctype, endpoint)
        print("uploaded", os.path.basename(path), "- HTTP", st)


def _tool(name):
    py = sys.executable
    r = subprocess.run([py, os.path.join(ROOT, "tools", name)], cwd=ROOT)
    if r.returncode:
        raise SystemExit(f"{name} failed")


def main(argv):
    cmd = argv[0] if argv else ""
    if cmd == "setup" and "--from-file" in argv:
        setup_from_file()
    elif cmd == "check":
        check()
        if "--online" in argv and not verify_key():
            return 1
    elif cmd == "setup":
        setup()
    elif cmd == "upload":
        upload()
    elif cmd == "release":
        _tool("sign_team_update.py")
        upload()
        _tool("verify_update.py")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
