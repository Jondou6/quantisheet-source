# AI Takeoff - design log (v3, Oct 31 2026)

Dated record of what was built, why, and what was rejected. Engineering
rules kept (from the design review): one whole-symbol score for symbol
counts; instant fill; rooms to their own wall faces (no room ranking, no
50/50 split); scale only from scale text, printed dimension lines, or the
person's calibration (never from counting pixels of a drawn object);
review and confidence scores are the place to add value.

## Oct 31 2026 - run again without counting twice (app/rerun.py, rerun_ui.py)
- Built: a second run's measurements are matched to what is already on the
  drawing by place and shape (areas: 80% overlap; lines: every point within
  6 pt and length within 10%; counts: within 6 pt of the same item or any
  AI count). Matches are listed as previously detected and locked - never
  added again, whether accepted, still in review or measured by hand. The
  rest are new matches, ticked, for the person to pick. Review decisions
  from the earlier run that come back unchanged (same name, sheet, page,
  quantity within 1%) are kept.
- Why: v2 only skipped exact repeats (same label, within 3 pt). A renamed
  or accepted room, or one the person measured by hand, came back.
- Rejected: matching by name (renamed items would double); replacing the
  earlier marks with the new run's (loses the person's edits and
  decisions).

## Oct 31 2026 - AI vs manual on the drawing (annotate.py, estimate.py)
- Built: every AI measurement carries a small "AI" badge (and the v2 dashed
  line) until accepted; accepting (Check Takeoff or the review queue) makes
  it solid and takes the badge off. The origin (AI not checked / AI accepted
  / manual) is stored in the PDF (PSBadge, PSAudit, PSStatus) so it survives
  save, reopen and XFDF.
- Export rule: a drawing export shows the drawing as it is (badges and
  dashes included until accepted). The quantity CSV totals only accepted
  and manual quantities, has an Origin column, and lists pending AI items
  apart under "Pending review (AI, not in the totals)".
- Settings: ai_pencil (dashes), ai_badge (badge) can turn either off.

## Oct 31 2026 - one review queue (review_queue.py, ReviewQueueDialog)
- Built: one list of everything the AI found that isn't accepted - areas,
  lengths, counts (doors, windows, devices), schedule rows, a doubtful
  scale - least sure first, repeats last. Accept / Deny / Undo. A room's
  CHECK item and its outline are one entry. Items in review are in no
  total until accepted (the v2 room-109 rule).
- Rejected: a second queue per kind (the person had two places to look).

## Oct 31 2026 - scale confidence and evidence (app/scale_evidence.py)
- Built: each sheet's scale gets a 0-100 score with reasons and a crop of
  the printed scale words. Evidence used: the printed scale text itself,
  a SCALE label beside it, agreement with printed dimension strings beside
  their dimension lines (autoscale.dimension_scale), other scales printed
  on the same sheet, OCR and scan DPI. A user calibration is 100. A scan
  with no text layer is 0 ("set it by hand"). Under 60 on a sheet that is
  measured: the sheet goes to the review queue and its lengths and areas
  wait (pending) until the person confirms the scale; counts don't wait.
- Rule kept: no pixel-counting of drawn objects to guess a scale.
- Rejected: auto-correcting the scale from the dimensions (a scale changes
  every length; the person confirms it).

## Nov 2 2026 - shower-bench passages are floor, not doorways (HMB 109)
- Built (Chief's patch, reviewed, tried on a copy, applied with Jon's OK):
  when a room is filled out to its wall faces, openings up to FACE_GAP_FT
  are shut as doorways only between wall-thick ink (poche, or two face
  lines within FACE_WALL_FT). A gap beside a thin wall-layer line - a
  bench outline, a door leaf or swing, a grab bar - is floor. Slots up to
  FACE_THIN_GAP_FT beside any line stay shut as before.
- Why: HMB A101 draws benches, swings and curtains on the wall layers;
  the 2'-9" passage beside a shower bench was shut as a door, so Women's
  Shower 109 came out 114.7 SF against 129.8.
- Result (A101, truth.csv): 109 -11.6% -> -7.8% (now within 8%); 104,
  103, 106, 111 closer; 108 +3.6 -> +4.5% and 112 +2.8 -> +3.3% (still
  within; Chief reads truth.csv as low there - unverified). 8/9 -> 9/9.
- Still open: the floor under a built-in bench itself is not counted
  (109 stays ~10 SF short).
