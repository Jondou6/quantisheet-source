# TLS for the collaboration relay

How to make a certificate for the QuantiSheet relay, which ports to open,
the Windows firewall commands, and how to pin the self-signed certificate
by its fingerprint.

The tool is `tools/relay_cert.py`. It writes a certificate and a key only
to the path you give it, and it prints the fingerprint. It does not change
the relay, the desktop client, or any setting. Wiring the fingerprint into
the client is still to do (see "Pinning" below).

`server/data/` is the relay's private data and is gitignored. Leave it
alone. Do not point the tool at the git checkout. `*.key` and `*.pem` are
gitignored; `*.crt` is not, so a certificate saved inside the repo can be
committed by mistake.

## Which relay, which ports

Keep the ports the program already uses. Moving them means changing the
firewall rule, the scheduled task, and every `RelayURL` (Group Policy and
the examples in `docs/IT_DEPLOYMENT.md`).

| How the relay is run | WebSocket | Phone and browser pages |
|---|---|---|
| `QuantiSheet.exe relay`, and the relay started inside the app (`app/collab/relay.py`) | TCP **8765** (`--port`, default 8765) | TCP **8766** (`--http-port`, default 8766) |
| The hosted relay, `server/relay_server.py` (Docker, Fly.io, Render, or `python relay_server.py`) | TCP **8765** (`PORT`, default 8765) | The **same** port. One process serves both. |

8765 is the desktop address (`wss://host:8765`). 8766 is the phone link
the Windows relay prints (`https://host:8766/`). Opening only 8765 on a
Windows server leaves phones unable to connect.

The hosted relay sits behind Caddy, Fly, or Render, which do HTTPS on 443
and forward to 8765 (`TLS_PROXY=1` in `server/fly.toml` and
`server/render.yaml`). Do not also open 8766 for that one, and do not move
the Windows relay onto 443: something else on the server is often already
there, and the installer rule is 8765 and 8766 only.

Binding `127.0.0.1` is this computer only. It needs no firewall rule, and
it may run without a certificate. Binding `0.0.0.0` (the scheduled task
does this) is reachable from other computers: it must have a relay token,
and it must have a certificate or an explicit plain-LAN opt-in
(`ALLOW_PLAIN_WS=1` on the hosted relay, `collab_allow_plain_lan` in the
app). A plain `ws://` address is refused by the desktop client unless it
is the IT `RelayURL` or that opt-in is on (`app/collab/client.py`).

## Make the certificate

From the repo, on the machine that will run the relay:

```
python tools/relay_cert.py C:\ProgramData\QuantiSheet
```

That writes:

- `C:\ProgramData\QuantiSheet\relay.crt`
- `C:\ProgramData\QuantiSheet\relay.key`

and prints:

```
SHA-256 fingerprint: AA:BB:...
relay_cert_sha256=AA:BB:...
```

The fingerprint is SHA-256 of the DER certificate, colon-separated hex.
It is the same value Windows shows for the certificate. It is not a hash
of the PEM file.

The common name defaults to `quantisheet-relay`, which is only a
placeholder. Pass the name people will type, and every address as well,
because the relay's own screen shows the LAN IP (`wss://10.x.x.x:8765`):

```
python tools/relay_cert.py C:\ProgramData\QuantiSheet --cn relay.example.test --san 10.1.2.3 --san relay.example.test
```

`--san` may be repeated. A value that parses as an IP is stored as an IP
name; anything else is stored as a DNS name. The common name is always
included. `--days` defaults to 825, the same lifetime the app uses for its
own self-signed signing certificate. `--bits` is 2048, 3072, or 4096
(default 2048). `--force` replaces an existing pair. Without `--force` the
tool stops if either file is already there.

To choose the two files yourself:

```
python tools/relay_cert.py --cert C:\ProgramData\QuantiSheet\relay.crt --key C:\ProgramData\QuantiSheet\relay.key --cn relay.example.test
```

A path ending in `.crt`, `.cer`, or `.pem` is the certificate, and the key
is written next to it with a `.key` suffix.

The certificate is self-signed, `CA:FALSE`, with TLS server use
(`serverAuth`) and a subject alternative name. The key is unencrypted PKCS#8
PEM, written with mode `0600` where the operating system honours that mode.
Windows does not apply Unix modes to the ACL. Lock the key after writing
it (next section). The tool never prints the key.

These names are made up for the examples: `relay.example.test`, `10.1.2.3`.
Use the real host when you run it. Do not commit the files the tool wrote.

Functions another program can call, without the command line:

- `destinations(path)` → `(cert_path, key_path)`
- `generate(cert_path, key_path, cn=..., sans=(), days=825, bits=2048, force=False)` → `Issued` (`.cert_path`, `.key_path`, `.fingerprint`)
- `fingerprint_sha256(cert)` → colon-separated SHA-256. `cert` is PEM text, PEM or DER bytes, or a file path.
- `fingerprint_matches(cert, expected)` → true when `expected` is that fingerprint. Colons, spaces, and case do not matter.
- `main(argv)` → exit code 0, or 2 on a bad path or a refusal to overwrite.

## Point the relay at the files

The Windows scheduled task "QuantiSheet Relay" is created by
`installer/quantisheet_server.iss` without a certificate. The action to
add, as an administrator, is the task's existing command plus `--cert` and
`--key` (the same flags `QuantiSheet.exe relay` already accepts in
`app/cli.py`, and the same paths `docs/IT_DEPLOYMENT.md` already uses):

```
schtasks /Create /F /TN "QuantiSheet Relay" /SC ONSTART /RU "NT AUTHORITY\LOCALSERVICE" /TR "\"C:\Program Files\QuantiSheet\QuantiSheet.exe\" relay --host 0.0.0.0 --token-file \"C:\ProgramData\QuantiSheet\relay\relay-token.txt\" --data-dir \"C:\ProgramData\QuantiSheet\relay\hub\" --log \"C:\ProgramData\QuantiSheet\relay\relay.log\" --cert \"C:\ProgramData\QuantiSheet\relay.crt\" --key \"C:\ProgramData\QuantiSheet\relay.key\""
schtasks /End /TN "QuantiSheet Relay"
schtasks /Run /TN "QuantiSheet Relay"
```

After creating it, open the task and confirm the action is one command with
`--cert` and `--key` on it. The quotes are the same shape the installer
uses inside `installer/quantisheet_server.iss`.

The relay runs as `NT AUTHORITY\LOCALSERVICE`. That account has to be able
to read both files. Other users do not need the files; they need the
fingerprint. SIDs below are the ones the installer already uses for the
relay folder (`S-1-5-19` is LOCAL SERVICE, `S-1-5-32-544` is Administrators):

```
icacls "C:\ProgramData\QuantiSheet\relay.key" /inheritance:r /grant:r *S-1-5-19:(R) *S-1-5-32-544:(F)
icacls "C:\ProgramData\QuantiSheet\relay.crt" /inheritance:r /grant:r *S-1-5-19:(R) *S-1-5-32-544:(R)
```

Run the relay by hand once to see `wss://` in the line it prints:

```
QuantiSheet.exe relay --host 0.0.0.0 --token-file "C:\ProgramData\QuantiSheet\relay\relay-token.txt" --cert "C:\ProgramData\QuantiSheet\relay.crt" --key "C:\ProgramData\QuantiSheet\relay.key"
```

Other ways to give it the same pair, if you are not using the scheduled task:

- Inside the app, settings `relay_cert` and `relay_key` (read by `app/collab/relay.py` `tls_context`). Not set by this tool.
- The hosted process: environment `TLS_CERT` and `TLS_KEY` (read by `server/relay_server.py` `tls_context`). On your own Linux server, Caddy (`server/Caddyfile`) can do HTTPS instead, with `TLS_PROXY=1` and no certificate in the Python process.

Set Group Policy `RelayURL` to `wss://relay.example.test:8765` (port 8765,
not 8766). Phones use `https://relay.example.test:8766/` on the Windows
relay, or `https://relay.example.test/` when a proxy is doing HTTPS in
front of the single-port hosted relay.

## Windows firewall

The installer adds one inbound rule named `QuantiSheet Relay` for TCP 8765
and 8766, limited to `QuantiSheet.exe`. `netsh` will add a second rule of
the same name, so delete first, then add. Run these in an administrator
command prompt. The program path must be the real `QuantiSheet.exe`.

```
netsh advfirewall firewall delete rule name="QuantiSheet Relay"
netsh advfirewall firewall add rule name="QuantiSheet Relay" dir=in action=allow protocol=TCP localport=8765,8766 program="C:\Program Files\QuantiSheet\QuantiSheet.exe"
```

`dir=in` is inbound. Do not add an outbound rule; clients open the
connection out, and the server only listens.

To remove it on uninstall, which is what the installer runs:

```
netsh advfirewall firewall delete rule name="QuantiSheet Relay"
```

Check:

```
netsh advfirewall firewall show rule name="QuantiSheet Relay"
```

A relay started as `python server\relay_server.py` on Windows is not
`QuantiSheet.exe`, so the program filter above would block it. That is not
how the product is installed. If you do run it that way, use a separate
rule without `program=`, for port 8765 only (the hosted relay has no 8766):

```
netsh advfirewall firewall add rule name="QuantiSheet Relay (python)" dir=in action=allow protocol=TCP localport=8765
```

**UNVERIFIED:** nobody in this repo runs `relay_server.py` as the Windows
service. The scheduled task runs `QuantiSheet.exe`. Prefer the first rule.

Loopback (`127.0.0.1`) needs no rule. A hosted relay on Fly.io or Render
uses the host's firewall, not `netsh`.

## Pinning the self-signed certificate

A self-signed certificate is not signed by a public CA. The desktop client
(`app/collab/client.py` `CollabClient._connect_kwargs`, and
`app/collab/hubclient.py`) does not pass an SSL context, so the
`websockets` default applies: the certificate is checked against the
system trust store and the host name, and this certificate fails both.
People cannot connect with `wss://` until the client is taught the
fingerprint.

This tool does not change the client. The suggested setting name is
`relay_cert_sha256`, holding the colon fingerprint the tool printed.
**UNVERIFIED:** that name is not read anywhere in the app today. It is a
name to wire, not a name that already works.

What to wire, in the client's connect path:

1. Read `relay_cert_sha256`. If it is empty, keep today's behaviour.
2. For a `wss://` URL, pass an SSL context with `check_hostname = False`
   and `verify_mode = CERT_NONE`, and then compare the peer certificate
   yourself. Hostname checking stays off only because the pin replaces it.
   Still put every name and IP from the relay address into `--san`, so a
   later switch back to normal CA checking has a name to match.
3. After the handshake, take the peer certificate as DER
   (`SSLObject.getpeercert(binary_form=True)`) and accept the connection
   only when `fingerprint_matches(der, expected)` is true. Close it
   otherwise. Do not accept a certificate just because the name matches.

`fingerprint_matches` compares SHA-256 of the DER certificate. A different
certificate for the same host name will not match, which is the point of
pinning a self-signed one. Ship the fingerprint in Group Policy or type it
into the setting. Do not ship the private key.

The phone page is a browser. A browser will warn on this certificate until
the certificate is trusted on that phone, or until a real CA certificate
is used instead. Pinning in the desktop client does not silence the
browser warning. **UNVERIFIED:** there is no phone-side pin in
`app/collab/web/` today.
