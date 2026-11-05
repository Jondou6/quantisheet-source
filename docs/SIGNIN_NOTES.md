# First-start sign-in (app/onboard.py)

What it is: a "who's testing" speed bump for in-house testers. It asks
for a work email once per computer. Wrong entries say only "Invalid
email."; 5 wrong entries lock it for 15 minutes. A locked-out tester reads
Jon the PC code in the box; Jon runs `python tools/unlock_code.py <PC code>`
and reads back the 8-character unlock code.

What it is not (Grok review of 0.12.14, M7 - Jon agreed, Oct 19 2026):
- Not security. Only the email's domain is checked, against a salted
  fingerprint whose salt ships in the program. The signed-in token is
  computed from values in the program plus the machine ID and kept in the
  user's settings, so someone who reads the code can skip it.
- The command line (`quantisheet <command>`) is not gated.
- The lock lives in the user's settings and registry; the same user can
  remove it.

Before any release outside the company: turn the license key back on
(KEY_REQUIRED = True) and take the contacts out, as planned. If sign-in
ever has to be real, verify the address on a company server (an emailed
one-time code or Entra ID) and store a server-signed token.
