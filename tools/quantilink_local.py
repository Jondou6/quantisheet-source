"""Run a local QuantiLink server on this PC and check QuantiSheet's Send
with QuantiLink against it (Jon, Nov 24: "Install it on my pc").

    python tools/quantilink_local.py start [FOLDER]   start it (localhost)
    python tools/quantilink_local.py status
    python tools/quantilink_local.py stop
    python tools/quantilink_local.py setup             test admin + key
    python tools/quantilink_local.py check             a real send

FOLDER is where QuantiLink was unzipped (default Desktop\\QuantiLink\\
quantilink). It listens on 127.0.0.1:8080 only; its files go to a "data"
folder next to it. setup makes a made-up test administrator and a Desktop
sync key and keeps them in data\\test-login.json on this PC only (never
printed). check sends a made-up PDF with QuantiSheet's own client and
fetches the share link."""
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
STATE = os.path.join(ROOT, ".run", "quantilink_local.json")
URL = "http://127.0.0.1:8080"


def _default_folder():
    desk = os.path.dirname(ROOT)
    return os.path.join(desk, "QuantiLink", "quantilink")


def _state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _get(path, timeout=5):
    with urllib.request.urlopen(URL + path, timeout=timeout) as r:
        return r.status, r.read()


def _post(path, body, cookie=None):
    req = urllib.request.Request(URL + path, data=json.dumps(body).encode(),
                                 method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-QuantiLink", "1")          # the server's CSRF check
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}"), \
                r.headers.get("Set-Cookie")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), None


def health():
    try:
        st, raw = _get("/api/health")
        return json.loads(raw) if st == 200 else None
    except Exception:                                     # noqa: BLE001
        return None


def node_version():
    try:
        out = subprocess.run(["node", "--version"], capture_output=True,
                             text=True, timeout=20,
                             creationflags=getattr(subprocess,
                                                   "CREATE_NO_WINDOW", 0))
        return out.stdout.strip()
    except Exception as e:                                # noqa: BLE001
        return f"not found ({type(e).__name__})"


def start(folder=None):
    folder = os.path.abspath(folder or _default_folder())
    if not os.path.isfile(os.path.join(folder, "server.js")):
        sys.exit(f"no server.js in {folder}")
    if health():
        print("already running at", URL)
        return
    v = node_version()
    print("node", v)
    try:
        major = int(v.lstrip("v").split(".")[0])
    except ValueError:
        sys.exit("Node.js wasn't found")
    if major < 22:
        sys.exit("QuantiLink needs Node.js 22 or newer (built-in SQLite)")
    data = os.path.join(os.path.dirname(folder), "data")
    os.makedirs(data, exist_ok=True)
    env = dict(os.environ, HOST="127.0.0.1", PORT="8080",
               QUANTILINK_DATA=data)
    # backups into the Dropbox folder, as Start QuantiLink.bat does (Nov 25)
    drop = os.path.join(os.path.expanduser("~"), "Dropbox")
    if os.path.isdir(drop):
        env["QUANTILINK_BACKUP_DIR"] = os.path.join(drop, "QuantiLink Backups")
        print("backups to", env["QUANTILINK_BACKUP_DIR"])
    log = open(os.path.join(data, "server.log"), "ab")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
        getattr(subprocess, "DETACHED_PROCESS", 0) | \
        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    p = subprocess.Popen(["node", "server.js"], cwd=folder, env=env,
                         stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=flags,
                         close_fds=True)
    with open(STATE, "w") as f:
        json.dump({"pid": p.pid, "folder": folder, "data": data}, f)
    for _ in range(40):
        time.sleep(0.5)
        h = health()
        if h:
            print("running at", URL, "pid", p.pid)
            print("health:", {k: h.get(k) for k in ("app", "signup",
                                                    "encryption")})
            return
    sys.exit("started but not answering yet - see data\\server.log")


def stop():
    st = _state()
    pid = st.get("pid")
    if not pid:
        print("not started by this tool")
        return
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                   capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print("stopped pid", pid)


def status():
    h = health()
    print("running" if h else "not running", URL, _state().get("folder", ""))
    bdir = os.path.join(os.path.expanduser("~"), "Dropbox", "QuantiLink Backups",
                        "snapshots")
    if os.path.isdir(bdir):
        snaps = sorted(os.listdir(bdir))
        print("Dropbox backups:", len(snaps), "newest", snaps[-1] if snaps else None)


def _login_file():
    st = _state()
    return os.path.join(st.get("data") or os.path.join(
        os.path.dirname(_default_folder()), "data"), "test-login.json")


def setup():
    """A made-up test administrator and a Desktop sync key, kept on this
    PC only."""
    if not health():
        sys.exit("start it first")
    lf = _login_file()
    if os.path.exists(lf):
        print("test login already made:", os.path.basename(lf))
        return
    email = "test-admin@example.com"
    pw = "Qs-" + secrets.token_urlsafe(18) + "-9x"
    code, body, cookie = _post("/api/auth/register",
                               {"name": "Test Admin", "email": email,
                                "password": pw})
    if code != 200:
        sys.exit(f"register: HTTP {code} {body.get('error', '')}")
    with open(lf, "w") as f:                       # before anything else
        json.dump({"email": email, "password": pw, "url": URL}, f)
    sid = cookie.split(";")[0] if cookie else None
    code, body, _ = _post("/api/account/tokens",
                          {"name": "QuantiSheet test"}, cookie=sid)
    if code != 200:
        sys.exit(f"key: HTTP {code} {body.get('error', '')}")
    token = body["result"]["token"]
    with open(lf, "w") as f:
        json.dump({"email": email, "password": pw, "token": token,
                   "url": URL}, f)
    print("made the test administrator", email, "and a key (kept in",
          os.path.basename(lf) + ", not shown)")


def check():
    """Send a made-up PDF with QuantiSheet's own client, then open the
    share link."""
    import tempfile
    from app import quantilink as ql
    with open(_login_file()) as f:
        login = json.load(f)
    c = ql.Client(login["url"], login["token"])
    spaces = c.spaces()
    print("folders:", [(s["name"], s["personal"], s["role"])
                       for s in spaces])
    space = spaces[0]["id"]
    tmp = tempfile.mkdtemp(prefix="qs-ql-check-")
    pdf = os.path.join(tmp, "RFI 001 - Made-up test.pdf")
    import fitz
    d = fitz.open()
    d.new_page().insert_text((72, 72), "Made-up RFI for a QuantiLink test")
    d.save(pdf)
    d.close()
    res = ql.send_file(c, space, "Test Project", "RFIs", pdf, days=1)
    again = ql.send_file(c, space, "Test Project", "RFIs", pdf, days=1)
    link = res["link"]
    shown = link.rsplit("/", 1)[0] + "/<token>"
    print("sent:", res["name"], "->", shown)
    print("sent again (new version):", again["name"])
    st, raw = _get("/s/" + link.rsplit("/", 1)[1], timeout=10)
    print("share link opens: HTTP", st, len(raw), "bytes")
    tok = link.rsplit("/", 1)[1]
    try:
        st2, raw2 = _get(f"/api/share/{tok}", timeout=10)
        info = json.loads(raw2)
        print("share info:", st2, {k: info.get(k) for k in
                                   ("name", "size", "kind", "expires")
                                   if isinstance(info, dict)})
    except Exception as e:                                # noqa: BLE001
        print("share info:", type(e).__name__, e)
    try:
        bad = ql.Client(login["url"], "qlt_wrong").spaces()
        print("wrong key accepted?!", bad)
    except ql.QuantiLinkError as e:
        print("wrong key refused:", e)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"start": lambda: start(sys.argv[2] if len(sys.argv) > 2 else None),
     "stop": stop, "status": status, "setup": setup,
     "check": check}[cmd]()
