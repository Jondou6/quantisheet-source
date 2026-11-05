"""Optional Back Office server for employee self-service (P2-07) and
mobile / offline time punches (P2-08).

Decision 10 = A: hosted like QuantiSheet's server/ (Docker + Caddy, Fly.io
or Render) but as its OWN service with its own data volume; QuantiSheet's
relay never carries HR data. Desktop-only shops never run it. The desktop
program publishes to it and pulls from it only when a person clicks (see
quantisheet_backoffice/remote.py). Standard library only (wsgiref), plus
cryptography for encryption at rest.
"""
