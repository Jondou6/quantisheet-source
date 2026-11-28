"""The program on this computer that the Outlook proof page talks to
(outlook_addin_proof/README.md):

    python tools/outlook_proof_listener.py [minutes]

Listens on 127.0.0.1:47321 only, so nothing outside this computer can
reach it. GET /ping answers "ok"; POST /pdf says whether what arrived is
a PDF and how big, and keeps none of it. Stops by itself after 15 minutes
(or the minutes given). Each request is printed, without its contents."""
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 47321
MAX_BYTES = 200 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "QuantiSheetProof/1"

    def _headers(self, code, length=0):
        self.send_response(code)
        # the page is on an https website and this is a private address:
        # the browser inside Outlook asks first whether that is allowed
        self.send_header("Access-Control-Allow-Origin",
                         self.headers.get("Origin") or "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(length))
        self.end_headers()

    def _say(self, code, text):
        body = text.encode("utf-8")
        self._headers(code, len(body))
        self.wfile.write(body)

    def do_OPTIONS(self):                                # noqa: N802
        print("asked whether it may connect, from",
              self.headers.get("Origin"))
        self._headers(204)

    def do_GET(self):                                    # noqa: N802
        if self.path.split("?")[0] == "/ping":
            print("reached (ping) from", self.headers.get("Origin"))
            self._say(200, "ok")
        else:
            self._say(404, "not here")

    def do_POST(self):                                   # noqa: N802
        if self.path.split("?")[0] != "/pdf":
            self._say(404, "not here")
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if not 0 < n <= MAX_BYTES:
            self._say(413, "too large or empty")
            return
        data = self.rfile.read(n)
        is_pdf = b"%PDF-" in data[:1024]
        print(f"received {len(data)} bytes; a PDF: {is_pdf} (not kept)")
        self._say(200 if is_pdf else 415,
                  f"got {len(data)} bytes, " +
                  ("a PDF" if is_pdf else "not a PDF"))

    def log_message(self, *args):                        # quiet
        pass


def main(argv):
    minutes = float(argv[0]) if argv else 15.0
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"listening on 127.0.0.1:{PORT} for {minutes:g} minutes "
          "(this computer only)")
    sys.stdout.flush()
    try:
        time.sleep(minutes * 60)
    except KeyboardInterrupt:
        pass
    srv.shutdown()
    print("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
