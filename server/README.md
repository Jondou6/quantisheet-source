# QuantiSheet collaboration relay (hosted)

The relay forwards markup changes between everyone in a session. Running it
on a server lets people outside your office network work on the same set
together, from QuantiSheet or the phone/tablet web app.

Live sessions are only forwarded, never stored. The hub built into the
relay (hub.py) does keep three things in DATA_DIR, because they must
outlast a session:

* **E-signature requests** - page images, each signer's fields and the
  audit trail. Signers open `https://your-host/sign.html?t=...` from the
  email QuantiSheet sends; they need no account.
* **Project files** - every version of every uploaded file, check-out locks
  and an activity feed (Project > Project Files in QuantiSheet).
* **Punch items** with photos, added from a phone at
  `https://your-host/punch.html`.

Back up DATA_DIR like any other project storage. Rooms and projects are
password protected; creating a project or a signature request also needs
the relay token when one is set. Signers and phone users only need their
link or the project password.

## Option 1: any Linux server (Docker + Caddy for HTTPS)

    cp -r ../app/collab/web ./web            # the phone/tablet web app
    docker build -t quantisheet-relay .
    docker run -d --restart=always -p 127.0.0.1:8765:8765 \
        -v /srv/quantisheet-data:/data \
        -e RELAY_TOKEN=pick-a-long-secret quantisheet-relay

Point a DNS name at the server, put it in `Caddyfile`, run `caddy run`.
In QuantiSheet: Tools > Live Collaboration > Join, relay
`wss://relay.yourcompany.com/`, the token, a room name and password.

## Option 2: Fly.io

    cp -r ../app/collab/web ./web
    fly launch --copy-config --no-deploy
    fly volumes create quantisheet_data --size 10
    fly secrets set RELAY_TOKEN=pick-a-long-secret
    fly deploy

Relay address: `wss://<app>.fly.dev/`

## Option 3: Render

Push this folder (with `web/`) to a Git repo and create a Blueprint from
`render.yaml` (it asks for a 10 GB disk, which needs a paid instance). Relay address: `wss://<service>.onrender.com/`

## Client addresses behind the host's proxy (TRUSTED_PROXIES)

5 wrong passwords or tokens from one address within a minute lock that
address out for a minute. Behind Fly's or Render's proxy every connection
comes from the proxy, so the relay has to read the client's real address
from the `X-Forwarded-For` header the proxy adds - and it believes that
header only from the addresses in `TRUSTED_PROXIES` (comma-separated IPs or
networks, e.g. `10.0.0.0/8,fdaa::/16`; loopback is always trusted).
fly.toml sets `fdaa::/16` (Fly's private 6PN network) and render.yaml
`10.0.0.0/8` (Render's internal network). **Check these against your
host's current documentation before you deploy:** if the range misses the
proxy, every client looks like the proxy and one person's wrong password
locks everyone out; if it is wider than the proxy, a client could put a
fake address in the header and dodge the lockout. Behind your own Caddy or
nginx on the same machine leave it unset (loopback is trusted); on another
machine set it to that machine's address.

## Run it without Docker

    pip install "websockets>=13"
    PORT=8765 RELAY_TOKEN=secret DATA_DIR=./data python relay_server.py

`/healthz` answers `ok` for uptime checks. The web app is served from `/`.

## One source for hub.py and relaycore.py

`server/hub.py` and `server/relaycore.py` are copies of `app/collab/hub.py`
and `app/collab/relaycore.py`. Edit the app copies, then run
`python tools/sync_server.py` before `fly deploy` (the test suite fails if
they differ).

## Encryption

Clients should use `wss://`. On Fly.io and Render the platform does HTTPS
(`TLS_PROXY=1` is set in fly.toml / render.yaml). On your own server either
set `TLS_CERT` and `TLS_KEY`, or run behind Caddy (see Caddyfile) with
`TLS_PROXY=1`. A relay listening unencrypted on a network address refuses
to start unless `ALLOW_PLAIN_WS=1` (trusted in-house network only).

