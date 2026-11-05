# Back Office self-service server (optional)

Only for shops that want phone access: workers see their own pay stubs,
PTO and contact details, request PTO, ask for contact changes, and punch
in/out (works offline). Desktop-only shops skip all of this.

* Its own service with its own data volume, hosted the same way as
  QuantiSheet's server/ (Docker + Caddy on Fly.io, Render or a small VPS).
  QuantiSheet's relay never carries HR data.
* Secrets come from the host: `QSBO_OFFICE_TOKEN` (24+ random characters,
  also entered once in Back Office > People > Self-service) and
  `QSBO_SERVER_KEY` (Fernet key; encryption at rest). Without
  `QSBO_SERVER_KEY` a key file is made in the data volume.
* The server holds only what self-service needs: name, contact details,
  last 4 digits of SSN and bank account, PTO balance, pay stubs from the
  payroll provider's register, open jobs and geofences. All encrypted.
* Nothing moves by itself: the office clicks Publish (send stubs, balances,
  jobs) and Pull (bring in requests and punches) in Back Office.
* Punch photos are kept only for workers with written consent on file.
  No face recognition.
* Trial run on one PC: `python -m quantisheet_backoffice.server --data
  ./ss-data --port 8080` with QSBO_OFFICE_TOKEN set.
