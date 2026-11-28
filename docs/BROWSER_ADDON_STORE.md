# Open in QuantiSheet: what the store listings need

For whoever fills in the Chrome Web Store and Microsoft Edge Add-ons forms.
Nothing here is submitted by any tool; a submission happens only on Jon's
word.

## The file to upload

    python tools/pack_extension.py --store
    -> release\browser\open-in-quantisheet-<version>-store.zip

The `--store` copy has no `key` in its manifest. A store gives the add-on
its own id. **After the first upload to each store, send both ids back**:
they go in `installer/browser-host.json` (`allowed_origins`), and only a
QuantiSheet built after that accepts the published add-on on its direct
line. Until then the published add-on still works through the browser's
downloads.

Test before submitting, with the published id or the plain zip:
QuantiSheet 1.1.40 or newer (setup copy) on the same computer.

## Listing text

**Name:** Open in QuantiSheet

**Short description (132 characters or fewer):**
Open a web PDF in QuantiSheet, make a web page a PDF, or view, mark up and
measure a PDF in the browser.

**Description:**
Open in QuantiSheet sends plan PDFs from your browser to QuantiSheet, the
takeoff and estimating program, on the same computer.

- Open the PDF you are looking at in QuantiSheet with one click, or
  right-click a link to a PDF.
- Make the web page you are on into a PDF and open it in QuantiSheet.
- View a PDF in the add-on's own viewer: highlight, draw, add a text note
  or an image, then send it to QuantiSheet with those marks.
- Start a takeoff in the browser: set the scale and click out lengths,
  areas, cut-outs and counts, snapped to the drawing's own lines.
  QuantiSheet works out the quantities when it opens.
- Optional: a button on every PDF, always open PDFs in QuantiSheet, or use
  the add-on's viewer for every PDF.

Requires QuantiSheet for Windows. The PDF goes to QuantiSheet on your own
computer and nowhere else. The add-on collects nothing and sends nothing
to anyone.

**Category:** Productivity (Chrome: Workflow and Planning).

**Single purpose (Chrome asks for one sentence):**
Get the PDF or web page the user is looking at into the QuantiSheet
program on the same computer, with a viewer to look at and mark the PDF
first.

## Why each permission is needed

Always present:

| Permission | Why |
| --- | --- |
| `nativeMessaging` | Hands the PDF to QuantiSheet on the same computer. The only program it can reach is QuantiSheet's own (`com.quantisheet.open`), which QuantiSheet's setup registers. |
| `activeTab` | When the user clicks the add-on's button, read the PDF that tab is showing. No access to any other tab. |
| `scripting` | Runs one small function in the tab the user clicked on, to read the PDF it is already showing and pass it to the add-on. |
| `downloads` | For a QuantiSheet without the direct line: the browser saves the PDF and the saved file is handed over. Also "Open my next PDF download". |
| `contextMenus` | The right-click items: open a linked PDF, open this PDF, make this page a PDF. |
| `storage` | Remembers the three on/off options and, until the browser closes, that the user asked for their next PDF download to open in QuantiSheet. |

Asked for only when the user turns something on:

| Permission | When it is asked | Why |
| --- | --- | --- |
| All sites (`http://*/*`, `https://*/*`) and `webRequest` | When the user ticks "button on every PDF", "always open PDFs in QuantiSheet" or "use this viewer for every PDF" | To see that a page being opened is a PDF. Page contents are not read. Unticking all three gives the access back. |
| `debugger` | The first time the user chooses Make this page a PDF | It is the only way an add-on can ask the browser for its own print-to-PDF of a page. Used for that one request on that one tab (`Page.printToPDF`, then reading the result), then let go. The browser shows its own notice while it runs. |

## Remote code

None. Every script is in the package. The PDF viewer is Mozilla's PDF.js
4.10.38 (Apache-2.0), included unchanged except for three script lines
in its `viewer.html`; its licence is in `pdfjs/LICENSE`. The package's
content security policy allows WebAssembly (`wasm-unsafe-eval`) because
PDF.js decodes some images with it; nothing else is loosened.

## Data use (the stores' privacy forms)

- Collects no personal data, no browsing history, no page contents.
- Sends nothing to any server. The only requests it makes are for the one
  PDF the user pointed at, to the website that PDF is on.
- The PDF, and any marks or takeoff clicks made in the viewer, go to
  QuantiSheet on the same computer.
- Not sold, not shared, not used for anything else.

**Privacy policy URL:** https://quantisheet.com/privacy

## For the reviewer (test instructions box)

1. Install QuantiSheet for Windows (setup copy, 1.1.40 or newer).
2. Open any PDF on the web, click the add-on's toolbar button, then Open
   in QuantiSheet. The PDF opens in QuantiSheet.
3. On any web page: toolbar button, Make this page a PDF. Allow the
   permission the browser asks for. The page opens in QuantiSheet as a PDF.
4. On a PDF: toolbar button, View here. The PDF opens in the add-on's
   viewer; the green button sends it to QuantiSheet.

Without QuantiSheet installed, step 2 falls back to saving the PDF with
the browser; nothing else happens.

## Known limits to say plainly if asked

- An IT department can turn the add-on's line and links off in
  QuantiSheet (policy `DisableBrowserAddon`); the add-on then says so and
  does nothing else.
- Windows only (QuantiSheet is a Windows program).
- With the Microsoft Store copy of QuantiSheet there is no direct line:
  PDFs go through the browser's downloads, and takeoff clicked out in the
  viewer does not go along.
