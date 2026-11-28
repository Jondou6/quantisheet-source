"""The error-report receiver on Cloudflare (cloudflare/README.md), with
wrangler as it is signed in on this PC:

    python tools/cf_error_worker.py whoami    is wrangler signed in?
    python tools/cf_error_worker.py deploy    deploy the Worker
    python tools/cf_error_worker.py check     one made-up report -> 204?

Deploys only cloudflare/error-reports-worker.js with cloudflare/
wrangler.toml (the Worker quantisheet-error-reports, its private R2
bucket binding and the name reports.quantisheet.com). Prints no tokens."""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CF = os.path.join(ROOT, "cloudflare")
URL = "https://reports.quantisheet.com/v1/report"


def wrangler(*args, timeout=600):
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SystemExit("npx (Node.js) isn't on PATH")
    p = subprocess.run([npx, "--yes", "wrangler", *args], cwd=CF,
                       capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW",
                                             0))
    out = (p.stdout or "") + (p.stderr or "")
    out = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[email]", out)
    out = re.sub(r"\b[0-9a-f]{32}\b", "[id]", out)
    return p.returncode, out


def check():
    body = json.dumps({"app": "quantisheet", "version": "0.0.0",
                       "report": "made-up test report"}).encode()
    req = urllib.request.Request(URL, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-QuantiSheet-Report", "1")
    req.add_header("User-Agent", "QuantiSheet/0.0.0")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("receiver answered: HTTP", r.status)
    except urllib.error.HTTPError as e:
        print("receiver answered: HTTP", e.code)
    except Exception as e:                                # noqa: BLE001
        print("receiver not reachable:", type(e).__name__, e)
    try:                                   # reading must not be possible
        with urllib.request.urlopen(urllib.request.Request(
                URL, headers={"User-Agent": "QuantiSheet/0.0.0"}),
                timeout=30) as r:
            print("GET answered: HTTP", r.status, "(should be 405)")
    except urllib.error.HTTPError as e:
        print("GET answered: HTTP", e.code, "(405 = reading refused)")
    except Exception as e:                                # noqa: BLE001
        print("GET:", type(e).__name__)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "whoami"
    if cmd == "check":
        check()
    elif cmd in ("whoami", "deploy"):
        code, out = wrangler(cmd)
        print(out[-3000:].encode('ascii', 'replace').decode())
        sys.exit(code)
    else:
        print(__doc__)
