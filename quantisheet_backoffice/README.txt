QuantiSheet Back Office 0.3.1
=============================

An optional, separate program beside QuantiSheet (folder
quantisheet_backoffice\ next to app\ and quantisheet_claims\). QuantiSheet
starts it from Module > QuantiSheet Back Office... through
app\backoffice_hook.py and hands it one read-only JSON snapshot of the
open job. Back Office never imports QuantiSheet's code, never opens
~/.quantisheet or the price database, and never writes the PDF.

Run from source (from the QuantiSheet folder, wherever it is):
    python -m quantisheet_backoffice [--snapshot FILE] [--data FOLDER]
    python -m quantisheet_backoffice --version | --selftest
Data folder: %LOCALAPPDATA%\QuantiSheetBackOffice (QS_BACKOFFICE_HOME
overrides). Keep it out of OneDrive: a synced SQLite file can be damaged.

Backups (File > Back up now): every backup (.qsbk) is encrypted. A backup
made on this PC restores here without a password; set a backup password
(File > Set backup password..., 10+ characters) so a backup also restores
on another PC with SSNs, tax IDs and bank details intact. Without that
password a backup cannot be opened elsewhere.

Tests:  quantisheet_backoffice\run-backoffice-tests.bat
Build:  pyinstaller --clean --noconfirm quantisheet_backoffice\build\QuantiSheetBackOffice.spec

Accounting modes (Settings > Accounting): 'Export to my accounting system'
(default: Back Office keeps its own balanced ledger and exports CSV/Excel,
QuickBooks Desktop IIF files and Sage 300 CRE import files) or 'Keep the
full books here' (banking, reconciliation, statements, migration import,
manual journal entries, dashboard).

Phase 2 (0.2.0): Payroll (gross pay from approved time, OT rules,
prevailing-wage rates, Payroll Preview, final payroll into job cost),
export to your payroll provider and register import, certified payroll
reports in Back Office's own layout, People (employee records with
masked/encrypted SSN, DOB and bank fields, every reveal logged, HR
documents, onboarding, change requests), certifications, PTO, field
punches and pay stubs through the optional self-service server, card
receipts matching, and the Field page (Daily Log manpower vs approved
hours, unit costs). Payroll here is gross pay for your licensed payroll
provider: Back Office does not withhold, file or pay payroll taxes.

Phase 3 (0.3.0, review fixes in 0.3.1):
- Assistant page (P3-01, P3-06 Ask the books): ask in plain words ("Who
  hasn't turned in time for last week on job 2611?", "What did we spend on
  job 2611 concrete last month?"); answers are computed from the books and
  cite the records used. Findings list (missing time, coding gaps, invoices
  over commitment, stalled approvals, missing waivers) with reminder TEXT
  for you to send yourself. Proposed changes (e.g. recode hours) show a
  before/after, change nothing until you click Apply, and can be undone.
- Bank suggestions (P3-05): rules first, then similar past lines, then the
  local model; you accept, change or dismiss each one; accepted AI
  suggestions can be undone. Reconciliation suggests which items to tick.
- WIP report (P3-04, Books & Reports): contract, estimated cost, cost to
  date, % complete, earned, billed, over/under; Excel and PDF.
- Sync Center (P3-02/P3-03): import vendor/job/cost-code/employee/
  commitment lists exported from your accounting system and review the
  differences; likely matches are confirmed by a person and nothing is
  renamed automatically. File-based only; no live connectors are included.
AI is optional and LOCAL ONLY: Settings > AI takes a local address
(localhost only; other addresses and redirects are refused), the runtime
(Ollama, or another OpenAI-compatible runtime on this PC), the model you
choose, a Test connection button and the confidence threshold for "Accept
AI at or above threshold". AI suggestions can be wrong; check before
accepting. With no model installed or running the Ask box says "AI is
unavailable" and offers a plain search of the books (it never guesses by
keywords), and every report still runs from the menus. SSNs, dates of
birth, bank and tax ID numbers, employee phone/e-mail/address and the
names of employees and time-entry workers are removed before any prompt,
and a prompt that still holds one is not sent. Every AI suggestion (model
name and version, input hash, suggestion, confidence) and who accepted,
corrected, rejected or undid it is in the AI activity log and the audit
trail.

0.3.1 (M4 review fixes): the above, plus P&L from the Ask box ("Pull this
quarter's P&L"), bulk recategorize and drafted journal entries as
before/after proposals applied only on Apply and undone in one step,
re-approval after recoding approved time, WIP "estimate needed" flag and
as-of forecast, sync file size limits and vendor-name checks.

Optional self-service server (its own service; QuantiSheet's relay never
carries HR data):  python -m quantisheet_backoffice.server --data FOLDER
for a trial on this PC, or server\deploy\ (Dockerfile + Caddyfile, see
server\deploy\README.md) on a host you control. Nothing is sent to it or
taken from it until an office user clicks Publish or Pull.

Back Office records payments; it never moves money, sends email on its
own, files taxes or 1099s, or connects to a bank. It does not open
QuickBooks company files and uses no Intuit API.

QuickBooks is a trademark of Intuit Inc. QuantiSheet is not affiliated with or endorsed by Intuit.
