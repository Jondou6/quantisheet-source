# Open in QuantiSheet (browser add-on for Chrome, Edge and Brave)

One job: send the plan PDF open in the browser (or a PDF a link points
to) into QuantiSheet on the same computer.

How it works
1. Toolbar button, or right-click > Open (linked) PDF in QuantiSheet.
2. With QuantiSheet 1.1.38 or newer (setup copy) the add-on hands the PDF
   straight to the program: the browser starts `QuantiSheet.exe` as a
   native messaging host (`com.quantisheet.open`, registered by setup;
   `app/browserhost.py`), the add-on sends the PDF the tab is showing down
   that pipe (`direct.js`), and the program saves it in
   `Downloads\QuantiSheet\` and opens it. No browser download, so no
   Save As window (Brave asks where to save every download by default).
3. Without that (older QuantiSheet, Store copy): the add-on saves the PDF
   with the browser's own download feature and opens
   `quantisheet://open?path=<the saved file>` (`app/weblink.py`,
   QuantiSheet 1.1.37 or newer). The browser asks once to allow it.

Make this page a PDF (popup button, or right-click a page): the browser
itself makes the PDF, the one its Print > Save as PDF makes
(`Page.printToPDF`, `page.js`), and it goes down the direct line. That
needs the `debugger` access, asked for the first time it is used and used
for that one request on that one tab; the browser shows its own notice
while it runs. Needs QuantiSheet 1.1.38 or newer.

View and mark up in the browser (`viewer-qs.js`, `pdfjs/`): the add-on
carries Mozilla's PDF.js viewer (version 4.10.38, Apache-2.0, licence in
`pdfjs/LICENSE`; fetched by `tools/fetch_pdfjs.py`, with only the English
strings and without its PDF-script sandbox, sample PDF and source maps).
"View here" in the popup opens the tab's PDF in it; the tick-box "Use this
add-on's viewer for every PDF" does that for every PDF the browser shows
(needs the same all-sites access as the other two options, and can't be on
together with "Always open in QuantiSheet"). Highlight, text, draw and
image are PDF.js's own tools and are saved as standard PDF annotations,
which QuantiSheet shows as its own markups (Text Box, Pen, Highlight).
The toolbar's Open in QuantiSheet sends the PDF with those marks down the
direct line. The one change to Mozilla's `viewer.html` is the two script
lines above `viewer.mjs`.

The Store (MSIX) copy of QuantiSheet has no direct line, by decision
(Jon, Nov 27): registering with browsers from a Store package needs the
restricted `unvirtualizedResources` capability, which could hold up Store
certification. With the Store copy the add-on uses the download way (3),
and the popup says to press Save if the browser asks where to save.
Make this page a PDF and the viewer's Open in QuantiSheet work there too:
the browser saves the PDF the add-on holds (`saveHeld`) and the saved file
is handed over.

Takeoff in the viewer (`takeoff.js`, QuantiSheet 1.1.39 or newer, setup
copy): a Takeoff button on the viewer's toolbar opens a panel to set the
page's scale (a standard scale, or two points and a real length) and to
click out lengths, areas and counts under a name. The numbers shown are a
preview. Nothing is written into the PDF: Open in QuantiSheet sends the
clicks and the scale with the PDF (`"marks"` on the direct line's `end`),
`app/browserhost.py` keeps them beside the saved PDF, and
`app/webmarks.py` builds QuantiSheet's own takeoff markups from them when
the PDF opens, with the program's own arithmetic, as one step Undo takes
back. `viewer.html` now has three script lines above `viewer.mjs`.

The add-on's id is fixed by `key` in manifest.json; setup's
`browser-host.json` lists the ids that may use the direct line. A store
gives the add-on a different id: add each store's id to
`installer/browser-host.json` when it is known.

Sites that show a PDF inside a web page (a viewer, a file-sharing
preview): the page itself isn't a PDF, so the add-on throws that download
away and waits up to three minutes for the user's own download from the
site ("Open my next PDF download instead" does the same from the start).
A Dropbox shared link is fetched as the file itself (dl=1).

Two options in the popup, both off until ticked: a small Open in
QuantiSheet button on every PDF shown in the browser, and "Always open web
PDFs in QuantiSheet". Ticking either makes the browser ask for access to
see which pages are PDFs (`webRequest`, all sites); unticking
both gives it back.

The hand-off itself goes through the add-on's own page (`open.html`),
which opens the `quantisheet://` link and has a button to click.

Privacy: nothing leaves the computer. No accounts, no analytics, no
remote code, no network requests of its own. Permissions: `downloads`
(save the PDF), `contextMenus` (the right-click items), `activeTab` (read
the address and title of the tab when the button is pressed), `storage`
(remember for three minutes, in this browser session only, that the next
PDF download should open in QuantiSheet).

Try it before any store: chrome://extensions (or edge://extensions) >
Developer mode > Load unpacked > this folder.

Not published. Publishing needs Jon's go, a Chrome Web Store developer
account (one-time fee) and, for Edge, the Microsoft Edge program in
Partner Center (no fee). The same folder is the package for both.
