# Open in QuantiSheet: how to use the browser add-on

For the add-on's support page and for testers. Works in Chrome, Edge and
Brave on Windows, with QuantiSheet installed on the same computer.

## What you need

- QuantiSheet 1.1.41 or newer, installed from the setup program. With the
  Microsoft Store copy the add-on still opens PDFs, but through the
  browser's downloads, and takeoff started in the browser does not go
  along.
- The add-on, pinned to the toolbar (the puzzle-piece button, then the
  pin beside Open in QuantiSheet).

## Open a PDF in QuantiSheet

1. Open the PDF in a browser tab.
2. Click the add-on's toolbar button, then **Open in QuantiSheet**.

The PDF is saved in `Downloads\QuantiSheet` and opens in QuantiSheet. You
can also right-click a link to a PDF and choose **Open linked PDF in
QuantiSheet**.

If the site shows the PDF inside a web page (a viewer or a sign-in page),
click **Open my next PDF download instead**, then use the site's own
Download button. The PDF you download opens in QuantiSheet.

## Make a web page a PDF

1. Open the page.
2. Toolbar button, then **Make this page a PDF** (or right-click the page).

The first time, the browser asks you to allow it, and it shows a notice
while the PDF is being made. The page opens in QuantiSheet as a PDF named
after the page.

## View and mark up in the browser

1. Open the PDF, toolbar button, then **View here**.
2. Use the tools at the top right: highlight, text, draw, add an image.
3. Click the green **Open in QuantiSheet** to send the PDF with your marks.
   They arrive as QuantiSheet markups.

## Start a takeoff in the browser

1. In the viewer, click **Takeoff**. A column opens on the right.
2. **Set the scale.** Pick it from the list, or click **By two points**,
   click both ends of a dimension you can read, and type its length
   (`20` or `12' 6"`). If the page states one scale, the column offers it:
   click **Use it**, then check it against a dimension.
3. Type a **Name** (Walls, Doors) and pick a tool:
   - **Length**: click along the run; double-click or Enter to finish.
   - **Area**: click each corner; double-click or Enter to finish.
   - **Cut-out**: click the corners of an opening inside an area.
   - **Count**: click each one; click Count again when done.
   - **Move**: drag a corner. **Erase**: click a measurement to remove it.
4. Click **Open in QuantiSheet**.

Clicks snap to the ends of the lines on the drawing; untick **Snap** to
turn that off. Hold **Shift** for a straight or 45-degree line. Keys:
**Shift+L** length, **Shift+A** area, **Shift+C** count.

The numbers in the column are a preview. QuantiSheet works out the
quantities itself when the PDF opens, from where you clicked and the
scale you set, and adds them as its own takeoff markups. **Ctrl+Z** in
QuantiSheet undoes them.

## The three options

Each is off until you tick it, and the browser asks for access to see
which pages are PDFs when you do.

- **Show an Open in QuantiSheet button on every PDF**
- **Always open web PDFs in QuantiSheet**
- **Use this add-on's viewer for every PDF in the browser**

The last two can't both be on.

## If something doesn't work

| What you see | What to do |
| --- | --- |
| A Save As window every time, and "If the browser asks where to save, press Save" | You have the Microsoft Store copy, or QuantiSheet older than 1.1.38. Press Save; the PDF still opens. |
| "Sent, but the takeoff needs QuantiSheet 1.1.39 or newer" | Update QuantiSheet. The PDF opened; the measurements did not go along. |
| "Your IT department has turned off opening PDFs from the browser" | Your company has switched this off. Open the PDF from File > Open instead. |
| "The website didn't send this PDF to the add-on's viewer" | Click **Open it the usual way**. Some sites only send a PDF once; use the toolbar button, then View here, on those. |
| "The add-on needs reloading" | On the browser's Extensions page, click the reload arrow on Open in QuantiSheet. |
| "left out: set the scale on that page" in QuantiSheet | A measurement was made on a page with no scale. Set the scale and measure it again. |

## Privacy

The PDF goes to QuantiSheet on your own computer and nowhere else. The
add-on collects nothing and sends nothing to anyone.
