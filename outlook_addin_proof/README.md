# QuantiSheet Outlook proof (stage 2 of the Outlook plan)

A throw-away test, not the add-in. It answers two questions in the Outlook
it is opened in, and decides whether the real add-in (option B) can exist:

1. Can a web add-in read a PDF attachment's bytes?
2. Can it reach a program listening on the same computer (127.0.0.1)?

**Status: written, not run.** It has not been loaded into any Outlook.
Nothing here is hosted, installed or submitted until Jon says so.

## What it needs before it can run

- **Somewhere to serve these files over https.** Outlook only loads an
  add-in's page from an https address. The four files to serve:
  `proof.html`, `proof.js` and the three icons. Any static host works.
  This is the one thing that needs Jon's OK: it puts a test page on the
  web (it shows nothing private and does nothing without Outlook).
- **The manifest**, made for that address:

      python tools/outlook_proof.py manifest https://<host>/<folder>
      -> outlook_addin_proof/manifest.xml

- **The test program on the PC**, started just before the test:

      python tools/outlook_proof_listener.py

  It listens on 127.0.0.1:47321 only (nothing outside the computer can
  reach it), answers the page, says whether what arrived is a PDF, keeps
  nothing, and stops by itself after 15 minutes.

## Running it

1. Start the test program (above).
2. Add the add-in to Outlook from the file `manifest.xml`
   (Outlook > Get Add-ins > My add-ins > Add a custom add-in > Add from
   file; for an outlook.com / Hotmail account the same page is at
   https://aka.ms/olksideload).
3. Open an email that has a PDF attached and click **QuantiSheet proof**
   on the ribbon, then **Run the test**.
4. Copy the text it shows back to Claude.
5. Remove the add-in again (same page, the three dots on its row).

Run it once in classic Outlook and, if there is one, once in the new
Outlook: they are different programs and may answer differently.

## Reading the answer

- Both "Yes": option B can be built. The plan's next decision is the
  listener in QuantiSheet (on hold until testers ask for one click).
- "read the first PDF's bytes" is No: an add-in cannot get the PDF in
  that Outlook. B stops; drag and drop (option A) is the answer.
- "reached the test program" is No: Outlook blocks the connection to
  this computer. B stops, same as above.
