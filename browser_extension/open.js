// Open in QuantiSheet: the hand-off page. The saved PDF's path comes in
// the page address; the button (and one automatic try) opens the
// quantisheet:// link, which is what makes the browser ask "Open
// QuantiSheet?". A browser won't always start another program from the
// background, so this page gives it a click to act on.
const path = new URLSearchParams(location.search).get("path") || "";
const link = appLink(path);
const go = document.getElementById("go");
document.getElementById("file").textContent =
  path.split(/[\\/]/).pop() || "";
if (path) {
  go.href = link;
  setTimeout(() => { location.href = link; }, 150);     // one try by itself
} else {
  go.removeAttribute("href");
  document.getElementById("note").textContent = "No file to open.";
}
