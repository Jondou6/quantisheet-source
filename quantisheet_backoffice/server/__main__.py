"""Run the server for a trial on one machine:
    python -m quantisheet_backoffice.server --data FOLDER --port 8080
In production put it behind Caddy (HTTPS) as in deploy/. Needs
QSBO_OFFICE_TOKEN in the environment."""
import argparse
from wsgiref.simple_server import make_server

from .app import create_app


def main(argv=None):
    ap = argparse.ArgumentParser(prog="quantisheet_backoffice.server")
    ap.add_argument("--data", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args(argv)
    app = create_app(a.data)
    with make_server(a.host, a.port, app) as srv:
        print(f"Back Office self-service on http://{a.host}:{a.port}/")
        srv.serve_forever()


if __name__ == "__main__":
    main()
