# ADA module (0.12.25)

The **Module** tab (and Module menu) has the ADA tools: **ADA Standards
PDF** opens the Justice Department's PDF itself in a tab - figures and
all, searchable with Ctrl+F; **Look Up** (ADA Standards (2010)) and **ADA
Checker** open one window with two tabs. It works with no drawing open; with one, the
checker's counts are saved inside the PDF (`quantisheet_ada.json`).

## Reference

The whole 2010 ADA Standards for Accessible Design (US Department of
Justice, September 15, 2010 - a public-domain government publication):
the DOJ rules (28 CFR 35.151 and 36.401-406) and every section of
chapters 1-10 with its advisory, 1,151 entries.

* Type a section number (`404.2.3`, `§ 208.2`) or words (`door
  maneuvering`, `van parking`, `checkout aisle`).
* Links go up to the parent section and down to the subsections.
* Copy Section / Copy Citation for RFIs and comments.
* The figures are not reproduced; the page number points to the PDF.

How it's built: `tools/fetch_ada.py` downloads the PDF from
www.ada.gov (only that address) to `data/ada/` and pulls the page text;
`tools/ada_index.py` splits it into sections and writes
`app/data/ada2010.json`, which ships with the program. Running heads,
footers and the back index are removed; table rows keep their line
breaks.

## Checker (commercial)

Chapter 2 scoping from the counts you type - parking (208), passenger
loading (209), entrances (206.4), the route between stories (206.2.3 and
its Exception 1), toilet rooms (213, 603, 604), drinking fountains (211),
assembly seating and assistive listening (221, 219), dining and work
surfaces (226), counters (227), dressing rooms and lockers (222, 225),
guest rooms (224) and patient rooms (223). Each line gives what's
required, what you have, and the section. Double-click a line to read
the section.

The tables in `app/ada_check.py` are checked against the Standards' own
text by `tests/test_ada.py`, so a typo in a number fails the tests.
Fractions round up (104.2). Bad entries (text, negative, NaN) count as
blank.

## Generated office and retail sets

Generate Set adds sheet **A-801 Accessibility** to office and retail
sets: door clear width (404.2.3), maneuvering depth and latch-side room
(404.2.4.1), restroom turning space (603.2.1, 304.3.1), route width
(403.5.1), a route from the entrance to every room (206.2.4) and the
entrance (206.4), then the chapter 2 lines for what the set shows.
Machinery rooms are exempt (203.5).

To pass those checks, office and retail plans now get 3'-0" interior
doors (a 2'-8" leaf is under 32 in. clear), a 5 ft hall, restrooms at
least 5'-9" wide, and 18 in. of wall beside the latch where the wall is
long enough. Houses are unchanged.

## From the drawings (0.12.26)

**Fill From Drawings** reads the counts on the drawings by group name:
"Parking", "Accessible Parking", "Van Parking", "WC - Men", "Urinal -
Men", "Lavatory - Men", "Toilet Stall - Women", "Accessible Stall -
Women", "Ambulatory Stall - Women", "Seat", "Wheelchair Space", "Aisle
Seat", "Entrance", "Accessible Entrance", "Drinking Fountain", "Guest
Room", "Dwelling Unit", "Dressing Room", "Locker". What follows a dash or
colon names the room; parking is one facility per sheet.

**Measured sizes:** a length in a group like "Door Clear Width",
"Accessible Route", "Access Aisle", "Parking Stall Width", "Toilet Stall
Width", "Ambulatory Stall", "Grab Bar Height", "Counter Height",
"Turning Space", "Ramp Width" or "Handrail Height" is checked against
its minimum or maximum (app/ada_takeoff.py ELEMENTS; a test checks each
number is in the cited section). **Mark Up Short Items on Drawings**
clouds the ones that fall short (subject "ADA Check").

**Apartments** (use "Apartments / residential"): 233.3.1.1 mobility
units 5% (min 1), 233.3.1.2 communication units 2% (min 1), resident
parking 208.2.3.1-2. HUD-funded housing follows HUD's 504 rules.

## Limits

A screening aid. Alterations (202), historic buildings (202.5), the
exceptions, state codes (CBC 11B, TAS ...) and the jurisdiction's
adopted code decide the real answer. It reads counts and sizes only from
measurements named as above.
