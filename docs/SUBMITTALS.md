# Submittals (0.12.27)

Project Center > **Submittals** (also Project > Submittal Log, and the Submittals button on the Project tab) is the log:
numbered by spec section (08 71 00-001), with type, responsible
contractor, needed-on-site / lead / review dates ("submit by"), the review
steps (architect, then each engineer), who has the ball, revisions and
attachments.

* **From Spec Book…** - pick the project manual PDF. Every section
  (`SECTION 08 71 00 - DOOR HARDWARE`) is read, and the items under its
  PART 1 submittal articles (`1.3 ACTION SUBMITTALS`, `INFORMATIONAL`,
  `CLOSEOUT`) become proposed submittals ("Door Hardware - Product Data",
  "... - Shop Drawings", "... - Samples") with their type. Untick what you
  don't want; the rest are added as Not Submitted. Ones already in the log
  are skipped. (Needs text in the PDF - OCR a scan first.)
* **Make Submittal Package (PDF)** - one PDF to send: a cover sheet
  (project, number and revision, spec section and CSI division, type,
  from / to, dates, what's included), the contractor's review statement
  and signature, a review stamp for each reviewer (Approved, Approved as
  Noted, Revise and Resubmit, Rejected, For Record Only), then the
  attached PDFs and photos. Saved in the project's `Submittals` folder,
  opened in QuantiSheet, and kept on the submittal so **Send for Review**
  emails it.
* **Send for Review / Record Response / Resubmit as Next Revision** - the
  review workflow, as before.

Code: app/pm/submittals.py, tests/test_submittals.py.
