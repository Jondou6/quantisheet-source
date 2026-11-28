# Error-report receiver (Cloudflare)

`error-reports-worker.js` receives QuantiSheet's automatic error reports
(app/errorreports.py; team copy only, off until a tester turns it on).

Set-up, once, in the Cloudflare account that has quantisheet.com:

1. R2 > Create bucket: `quantisheet-error-reports` (private; no public
   access, no r2.dev URL).
2. Workers & Pages > Create > Worker, named `quantisheet-error-reports`;
   paste `error-reports-worker.js` and deploy.
3. The Worker's Settings > Bindings > Add > R2 bucket: variable name
   `REPORTS`, bucket `quantisheet-error-reports`.
4. The Worker's Settings > Domains & Routes > Add > Custom domain:
   `reports.quantisheet.com`.
5. Check: `curl -i -X POST https://reports.quantisheet.com/v1/report -H
   "Content-Type: application/json" -H "X-QuantiSheet-Report: 1" -d
   "{\"app\":\"quantisheet\",\"version\":\"0.0.0\",\"report\":\"made-up
   test\"}"` answers `204`, and the object appears under `reports/<day>/`
   in the bucket.

Reading reports: R2 > quantisheet-error-reports > reports/. Nothing is
served back by the Worker. Stored per report: the time received, the
QuantiSheet version and the scrubbed report text. No IP address.
