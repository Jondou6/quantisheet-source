# Made-up 1.1.1 samples

Everything in this folder is invented. Addresses are `123 Example St`. Phones are `555-0100` through `555-0102`. Mail uses `@example.com`. There is no company name, no logo, no utility or water-district fields, and no licensed price book.

Regenerate with `python tests/sample_data/make_samples.py`. That writes a new payroll key, so commit `payroll_company/backoffice.sqlite` and `payroll_company/datakey.bin` from the same run.

## Service files

Shapes follow `app/service/backflow.py`, `workorder.py`, and `agreements.py` on `cursor/service-111-644c`.

- `service_backflow.json` — 5 reports. One pass, one fail then repair then pass, RP and DC devices, and one missing serial. Check rows store `Diff. ___ psi`. The relief valve stores `Opened at ___ psi`. Repairs are the free-text `{pid}_repair_note` field (`c1_repair_note`, and the same for `c2`, `rv`, `so1`, `so2`). Account number and meter number are blank.
- `service_work_orders.json` — 10 service calls.
- `service_agreements.json` — 3 agreements.

`{pid}_repair_note` is the field the owner's later backflow screen uses. The copy of `backflow.py` on `cursor/service-111-644c` keeps psi as text and does not yet copy `{pid}_repair_note` in `_clean`. The phrases `Diff.` and `Opened at` live in the psi text fields.

## Job cost report

`job_cost_report.pdf` is a text PDF (three jobs, 25 cost codes, more than one page). `job_cost_report.prn` is the same lines with a form feed between pages.

Layout the column parser on the owner's PC expects:

- Amounts are right-aligned to the heading phrases (Original Estimate, Approved Changes, Total Estimate, Total Committed, Remaining to Commit, JTD Cost, Budget Variance).
- A blank cell is omitted, so some lines have fewer than seven amounts.
- Totals labels end in `*`, and the last figure on a totals line ends in `*`.
- Negatives use a trailing `-` (`15.00-`).
- The job line has no Job label. It starts `99-T-001  Example Hall`.
- Each page repeats the job number, the name, and two address lines. The second line includes a zip (`EX 00000`).
- `Job Totals*` and `Extra Totals*` follow each job's last cost code. `Report Totals*` follows the last job.

The .PRN cannot be checked against this branch's parser. The importer on `cursor/backoffice-1-1-1-86e2` refuses printer files and does not place amounts by heading-word right edges. That column parser is only on the owner's PC. This branch is cut from main and does not include the importer.

## Payroll key fixture

`payroll_company/backoffice.sqlite` is a small company file from the main `quantisheet_backoffice` schema. `payroll_company/datakey.bin` is the Fernet data key in the old location, next to the database, as `quantisheet_backoffice/crypto.py` writes it.

This copy was produced where Windows DPAPI is not available, so the file is `plain:` plus the key (`crypto._OwnerOnlyFile`). On Windows, `crypto.default_backend()` wraps the same file as `dpapi:`. A Windows migration run should pass `crypto._OwnerOnlyFile()` when it opens this sample, or re-wrap the key with DPAPI first. The key is a throwaway generated for this fixture. The company name and logo are empty. Three example workers, example phones, and small made-up cent amounts are encrypted in the payroll columns.
