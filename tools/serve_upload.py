"""Serve the R2 upload folder to the browser on this PC for a few minutes,
so the Cloudflare dashboard's own Upload box can be given the files
(Nov 2: the built-in browser can't open a file picker).

    python tools/serve_upload.py start [MINUTES]   (default 15)
    python tools/serve_upload.py status

Listens on 127.0.0.1 only (never the network), read-only, only the files
in release\\r2_upload\\<folder>\\team, only to pages from
https://dash.cloudflare.com, and stops by itself after MINUTES.
"""
import http.server
import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = os.path.join(ROOT, "release", "r2_upload")
STATE = os.path.join(ROOT, ".run", "serve_upload.json")
ORIGIN = "https://dash.cloudflare.com"
PORT = 47613


def team_dir():
    for d in os.listdir(UP):
        p = os.path.join(UP, d, "team")
        if os.path.isdir(p):
            return d, p
    raise SystemExit("no release\\r2_upload\\<folder>\\team")


class H(http.server.BaseHTTPRequestHandler):
    folder = None

    def _cors(self):
        o = self.headers.get("Origin")
        if o == ORIGIN:
            self.send_header("Access-Control-Allow-Origin", ORIGIN)
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Allow-Methods", "GET")
            self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self):          # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):              # noqa: N802
        name = os.path.basename(self.path.split("?")[0].lstrip("/"))
        p = os.path.join(self.folder, name)
        if self.path.startswith("/list"):
            body = json.dumps(sorted(os.listdir(self.folder))).encode()
            ctype = "application/json"
        elif name and os.path.isfile(p):
            with open(p, "rb") as f:
                body = f.read()
            ctype = "application/octet-stream"
        else:
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve(minutes):
    secret, folder = team_dir()
    H.folder = folder
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H)
    with open(STATE, "w") as f:
        json.dump({"pid": os.getpid(), "until": time.time() + minutes * 60,
                   "port": PORT, "secret": secret,
                   "files": sorted(os.listdir(folder))}, f)
    threading.Timer(minutes * 60, srv.shutdown).start()
    srv.serve_forever()


def main(argv):
    cmd = argv[0] if argv else "status"
    if cmd == "start":
        minutes = float(argv[1]) if len(argv) > 1 else 15
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
            getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([sys.executable, __file__, "_serve", str(minutes)],
                         creationflags=flags, close_fds=True)
        time.sleep(2)
        print(open(STATE).read() if os.path.exists(STATE) else "starting")
    elif cmd == "_serve":
        serve(float(argv[1]))
    else:
        print(open(STATE).read() if os.path.exists(STATE) else "not running")


if __name__ == "__main__":
    main(sys.argv[1:])
