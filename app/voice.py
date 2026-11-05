"""Voice commands: say what you want - "next page", "zoom in", "go to
page twelve", "go to sheet C two oh one", "measure length", "auto scale",
"AI takeoff", "search for digester", "undo", "stop listening".

Speech is recognised by Windows' own speech engine (System.Speech, part of
Windows - offline, nothing leaves the computer, no account), run in a
small PowerShell helper that prints what it hears. interpret() turns the
words into a command; it's plain Python, so it is the same everywhere and
easy to test.
"""
import difflib
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading

log = logging.getLogger(__name__)

# spoken phrase -> command name (as in the menus / command search)
PHRASES = {
    "next page": "Next Page", "page down": "Next Page",
    "next sheet": "Next Page", "previous page": "Previous Page",
    "page up": "Previous Page", "previous sheet": "Previous Page",
    "back a page": "Previous Page", "go back": "Previous View",
    "first page": "First Page", "last page": "Last Page",
    "zoom in": "Zoom In", "zoom out": "Zoom Out",
    "fit width": "Fit Width", "fit page": "Fit Page",
    "fit to page": "Fit Page", "whole page": "Fit Page",
    "actual size": "Actual Size", "undo": "Undo", "redo": "Redo",
    "save": "Save", "save the file": "Save", "print": "Print",
    "select": "Select", "select tool": "Select",
    "measure length": "Length", "length": "Length",
    "measure area": "Area", "area": "Area",
    "polylength": "Polylength", "measure perimeter": "Polylength",
    "volume": "Volume", "measure volume": "Volume",
    "cutout": "Cutout (Deduct)", "deduct": "Cutout (Deduct)",
    "count": "Count", "count tool": "Count",
    "auto area": "Auto Area (Click a Room)",
    "trace length": "Trace Length (Click a Line)",
    "trace line": "Trace Length (Click a Line)",
    "highlight": "Highlight", "cloud": "Cloud", "rectangle": "Rectangle",
    "text box": "Text Box", "callout": "Callout", "sticky note":
    "Sticky Note", "stamp": "Stamp", "arrow": "Arrow", "line": "Line",
    "calibrate": "Calibrate (Set Scale)",
    "set scale": "Calibrate (Set Scale)",
    "auto scale": "Auto Scale (Read Sheets)",
    "read the sheets": "Auto Scale (Read Sheets)",
    "bookmark sheets": "Auto Bookmark Sheets",
    "ai takeoff": "AI Takeoff (Whole Set)",
    "take off the set": "AI Takeoff (Whole Set)",
    "take off everything": "AI Takeoff (Whole Set)",
    "auto takeoff": "AI Takeoff (Whole Set)",
    "take off rooms": "Auto Takeoff Rooms on This Sheet",
    "auto takeoff rooms": "Auto Takeoff Rooms on This Sheet",
    "trade takeoff": "Trade Takeoff (Pipe, Duct, Devices, Roof, Rebar, "
                     "Earthwork)",
    "civil takeoff": "Trade Takeoff (Pipe, Duct, Devices, Roof, Rebar, "
                     "Earthwork)",
    "check takeoff": "Check Takeoff",
    "find rfis": "AI: Find RFIs & Questions",
    "find questions": "AI: Find RFIs & Questions",
    "summarize": "AI: Summarize", "spec check": "AI: Spec-Check",
    "new rfi": "New RFI", "compare revisions": "Compare Revisions (Overlay)",
    "overlay": "Compare Revisions (Overlay)",
    "markups list": "Markups List", "quantities": "Quantities",
    "estimate": "Assembly Library", "export to excel":
    "Export Assembly Estimate (Excel)", "create proposal": "Create Proposal",
    "project center": "Project Center", "help": "Help Center & Tutorials",
    "command search": "Command Search", "ocr": "Make Searchable (OCR)",
    "make searchable": "Make Searchable (OCR)",
    "delete markup": "Delete Selected Markup",
    "rotate right": "Rotate Right", "rotate left": "Rotate Left",
}
STOP = ("stop listening", "stop voice", "voice off", "that's all")

_UNITS = {"zero": 0, "oh": 0, "o": 0, "one": 1, "two": 2, "three": 3,
          "four": 4, "for": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
          "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
          "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}



def _ps_exe():
    """Windows PowerShell by full path (threat model T-017)."""
    from .syspaths import powershell
    return powershell()

def words_to_int(text):
    """'twelve' -> 12, 'one hundred five' -> 105, '42' -> 42, else None."""
    t = text.lower().replace("-", " ").replace(",", " ").strip()
    if re.fullmatch(r"\d+", t):
        return int(t)
    total = cur = 0
    seen = False
    for w in t.split():
        if w == "and":
            continue
        if w in _UNITS:
            cur += _UNITS[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur = (cur or 1) * 100
        elif w == "thousand":
            total += (cur or 1) * 1000
            cur = 0
        elif re.fullmatch(r"\d+", w):
            cur += int(w)
        else:
            return None
        seen = True
    return total + cur if seen else None


def int_to_words(n):
    ones = ["zero", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen",
            "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
            "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty",
            "seventy", "eighty", "ninety"]
    if n < 20:
        return ones[n]
    if n < 100:
        return tens[n // 10] + ("" if n % 10 == 0 else " " + ones[n % 10])
    rest = n % 100
    return ones[n // 100] + " hundred" + ("" if not rest else
                                         " " + int_to_words(rest))


def _sheet_code(text):
    """'c two oh one' -> 'C201', 'a dash one oh two' -> 'A-102',
    'p one point oh two' -> 'P1.02'."""
    toks = text.lower().replace("-", " dash ").split()
    out = ""
    for w in toks:
        if w in ("dash", "hyphen"):
            out += "-"
        elif w in ("point", "dot"):
            out += "."
        elif w in _UNITS and _UNITS[w] < 10:
            out += str(_UNITS[w])
        elif w in _UNITS or w in _TENS:
            out += str(words_to_int(w))
        elif re.fullmatch(r"[a-z]{1,2}", w) and not re.search(r"\d", out):
            out += w.upper()
        elif re.fullmatch(r"[a-z]{1,2}[\d.]+", w):
            out += w.upper()
        elif re.fullmatch(r"[\d.]+", w):
            out += w
        else:
            return None
    return out or None


def interpret(text, commands=()):
    """What `text` (as heard) asks for: (action, value) -
    ("stop", None), ("page", n), ("sheet", code), ("zoom", percent),
    ("search", words), ("command", name) - or (None, None)."""
    t = re.sub(r"[^\w\s.%-]", " ", (text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(please|quantisheet|quanti sheet|computer)\s+", "", t)
    t = re.sub(r"\s+please$", "", t)
    if not t:
        return None, None
    if t in STOP:
        return "stop", None
    m = re.match(r"^(?:go to |open |show |jump to )?(?:page|sheet number)\s+"
                 r"(.+)$", t)
    if m:
        n = words_to_int(m.group(1))
        if n:
            return "page", n
    m = re.match(r"^(?:go to |open |show |jump to )?(?:sheet|drawing)\s+(.+)$",
                 t)
    if m:
        code = _sheet_code(m.group(1))
        if code:
            return "sheet", code
    m = re.match(r"^zoom (?:to )?(.+?)\s*(?:percent|%)$", t)
    if m:
        n = words_to_int(m.group(1))
        if n:
            return "zoom", n
    m = re.match(r"^(?:search for|search|find|look for)\s+(.+)$", t)
    if m:
        return "search", m.group(1)
    if t in PHRASES:
        return "command", PHRASES[t]
    for c in commands:
        if t == c.lower():
            return "command", c
    keys = list(PHRASES) + [c.lower() for c in commands]
    hit = difflib.get_close_matches(t, keys, n=1, cutoff=0.82)
    if hit:
        k = hit[0]
        if k in PHRASES:
            return "command", PHRASES[k]
        return "command", next(c for c in commands if c.lower() == k)
    return None, None


def grammar_phrases():
    """What the recogniser listens for first (free dictation is the
    fallback): the phrases above, 'go to page one…two hundred', zoom
    levels."""
    out = set(PHRASES) | set(STOP)
    out |= {f"go to page {int_to_words(n)}" for n in range(1, 201)}
    out |= {f"page {int_to_words(n)}" for n in range(1, 101)}
    out |= {f"zoom to {int_to_words(n)} percent"
            for n in (25, 50, 75, 100, 125, 150, 200, 300, 400)}
    return sorted(out)


# ------------------------------------------------------------- engine
_PS = r"""
$ErrorActionPreference = 'Stop'
try { Add-Type -AssemblyName System.Speech } catch {
  [Console]::Out.WriteLine("ERROR`tWindows speech recognition isn't available on this computer."); exit 2 }
try {
  $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine([System.Globalization.CultureInfo]::CurrentUICulture)
} catch {
  try { $rec = New-Object System.Speech.Recognition.SpeechRecognitionEngine } catch {
    [Console]::Out.WriteLine("ERROR`tNo speech recognizer is installed (Settings > Time & language > Speech)."); exit 2 }
}
$phr = [IO.File]::ReadAllLines($env:PS_PHRASES)
$ch = New-Object System.Speech.Recognition.Choices
$ch.Add([string[]]$phr)
$gb = New-Object System.Speech.Recognition.GrammarBuilder($ch)
$gb.Culture = $rec.RecognizerInfo.Culture
$g = New-Object System.Speech.Recognition.Grammar($gb)
$g.Name = "commands"
$rec.LoadGrammar($g)
$d = New-Object System.Speech.Recognition.DictationGrammar
$d.Name = "dictation"
$rec.LoadGrammar($d)
try { $rec.SetInputToDefaultAudioDevice() } catch {
  [Console]::Out.WriteLine("ERROR`tNo microphone found. Plug one in (or turn it on in Settings > Privacy > Microphone)."); exit 3 }
[Console]::Out.WriteLine("READY")
[Console]::Out.Flush()
while ($true) {
  $r = $rec.Recognize([TimeSpan]::FromSeconds(20))
  if ($r -ne $null) {
    $c = $r.Confidence.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    [Console]::Out.WriteLine("HEARD`t" + $c + "`t" + $r.Grammar.Name + "`t" + $r.Text)
    [Console]::Out.Flush()
  }
}
"""


def available():
    """(ok, reason)."""
    if not sys.platform.startswith("win"):
        return False, ("Voice commands use Windows' built-in speech "
                       "recognition, so they need Windows.")
    return True, ""


class Listener:
    """Runs the recogniser in the background. on_heard(text, confidence,
    grammar) and on_state(state, message) are called from a worker
    thread - post them to the GUI thread."""

    def __init__(self, on_heard, on_state=None):
        self.on_heard = on_heard
        self.on_state = on_state or (lambda *a: None)
        self.proc = None
        self._files = []

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        ok, why = available()
        if not ok:
            self.on_state("error", why)
            return False
        if self.running:
            return True
        fd, phr = tempfile.mkstemp(suffix=".txt", prefix="pdfs_voice_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(grammar_phrases()))
        fd, ps = tempfile.mkstemp(suffix=".ps1", prefix="pdfs_voice_")
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(_PS)
        self._files = [phr, ps]
        env = dict(os.environ, PS_PHRASES=phr)
        try:
            self.proc = subprocess.Popen(
                [_ps_exe(), "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", ps],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, env=env, text=True,
                encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            self.on_state("error", f"Couldn't start speech recognition ({e})")
            return False
        self.on_state("starting", "Starting the microphone…")
        threading.Thread(target=self._read, daemon=True,
                         name="voice").start()
        return True

    def _read(self):
        try:
            self._read_lines()
        except Exception:                 # a callback on a closed window
            log.warning("voice listener stopped", exc_info=True)

    def _read_lines(self):
        p = self.proc
        if p is None:
            return
        for line in p.stdout:
            line = line.rstrip("\r\n")
            if line == "READY":
                self.on_state("listening", "Listening - say a command.")
            elif line.startswith("ERROR\t"):
                self.on_state("error", line.split("\t", 1)[1])
            elif line.startswith("HEARD\t"):
                parts = line.split("\t", 3)
                if len(parts) == 4:
                    try:
                        conf = float(parts[1])
                    except ValueError:
                        conf = 0.0
                    self.on_heard(parts[3], conf, parts[2])
            elif line.strip():
                log.debug("voice helper: %s", line)
        code = p.wait()
        self.on_state("stopped", "" if code in (0, 1, None) or code < 0
                      else f"Speech recognition stopped (code {code}).")
        self._cleanup()

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.proc = None

    def _cleanup(self):
        for f in self._files:
            try:
                os.remove(f)
            except OSError:
                pass
        self._files = []


def accept(text, confidence, grammar):
    """Whether to act on what was heard: commands from the phrase list need
    a fair confidence; free dictation needs more (it hears everything)."""
    if grammar == "commands":
        return confidence >= 0.5
    return confidence >= 0.65
