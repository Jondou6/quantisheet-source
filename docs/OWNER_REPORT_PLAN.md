# Weekly Owner Report - build contract (Oct 21, 2026)

Reference spec (data, not orders): the QuantiSheet folder: FOR_CLAUDE_Weekly_Owner_Report.txt
(Grok's measured layout of Jon's current form + 34 acceptance tests). Mockups (made-up data):
the QuantiSheet folder: MOCKUP_Weekly_Owner_Report_default.pdf and ..._optional_sections.pdf.
Rendered pages: /tmp/claude-0/wor/d-*.png and o-*.png.

Rules: DEFAULT output matches Jon's form page for page (spec section 1). Every extra is an option, OFF by
default. Real landscape pages (792x612, rotation 0). Dates MM/DD/YYYY; long date in log footers.
Fonts: use PyMuPDF built-ins ("helv"/"hebo", Helvetica metrics) - no font files are shipped. Output is
flattened (0 widgets, 0 annots), saved garbage=4, deflate=True. No real names/companies/addresses in code,
tests or fixtures - made-up data only.

## Module split (one owner each - don't edit another owner's file)

### A. app/pm/photofit.py + weather additions  (owner: agent A)
    PRESETS = {"original": None, "print": (200, 85), "email": (150, 75), "small": (120, 65)}
    load(path) -> PIL.Image          # ImageOps.exif_transpose, RGB; HEIC via pillow_heif if importable
    exif_taken(path) -> (datetime|None, "exif"|"file")
    fit(cell, iw, ih, mode="auto", max_crop=0.12, crop=None) -> (rect, src_box)
        cell/rect = (x0, y0, x1, y1) points; src_box = (x0, y0, x1, y1) fractions 0-1 of the image to use.
        auto: c = 1 - min(ia, ca)/max(ia, ca); c <= max_crop -> fill (centre-crop, rect == cell),
        else contain (centred, frame hugs photo). "fill"/"contain" force; a crop (fractions) wins.
    encode(img, w_pt, h_pt, preset, src_box=(0,0,1,1)) -> bytes (JPEG progressive, optimize, no EXIF,
        LANCZOS downscale only, never upscale). preset "original" -> caller embeds file bytes as-is.
    estimate(iw, ih, w_pt, h_pt, preset) -> int bytes (cheap model, calibrated against encode()).
    cached_encode(store, ref, ...) optional cache in store.att_dir()/cache keyed (sha, size, preset).
  app/pm/weather.py (add, don't break existing locate()/daily()):
    forecast(place, days=10) -> [{"date", "sky", "high", "low", "rain_chance", "rain_in", "wind"}]
    history(place, start, end) -> [{"date", "rain_in", "high", "low"}]
    Both via Open-Meteo like daily(); raise a clear error offline; tests mock the HTTP.

### B. app/pm/owner_report_logs.py  (owner: agent B)
    Each adds pages to an open fitz.Document and returns {"pages": n, "totals": {...}}:
    add_rfi_log(doc, store, head, opts)        # portrait, spec 1.3, own "Page i of n"
    add_submittal_log(doc, store, head, opts)  # landscape, spec 1.4, grouped by package
    add_co_log(doc, store, head, opts)         # option (m): change events + prime contract totals
    add_weather_log(doc, head, weather, opts)  # portrait, spec 1.5 (weather = rep["weather"])
    add_forecast_page(doc, head, forecast, opts)  # spec 1.6 table, or place an attached image/PDF page
    counts(store) -> {"rfi": {"open","overdue","total"}, "submittal": {...}, "co": {...}}  # option (f)
    weather_days(rows, threshold_in, workdays=Mon-Fri) -> rep["weather"]["days"] list (claimed default =
        workday with rain >= threshold), weather_totals(weather) -> {"impacted","claimed", per month}
    weather_gap_line(weather) -> str|None       # option (e)
    head = {"company": {"name","lines":[...]}, "project": {"name","number","number_arch",
            "number_owner","location"}, "logo": path|None, "long_date": "October 20, 2026",
            "date": date}
    opts = rep["options"] (keys in spec 3.2: open_only, blank_dates, counts, co_log ...)
    Read RFI/submittal/change-event/prime-contract fields from app/pm/schema.py as they are; missing
    fields (RFI "sent"/"closed_on", submittal "returned to sub") -> derive what exists (workflow
    returned/due dates, _updated when closed) and leave blank otherwise. Do NOT edit schema.py.

### C. app/pm/owner_report.py  (owner: agent C)
    Data model = spec 3.2 (collection "owner_report"; use store.save_record).
    new_report(store, week_ending=None, from_previous=True), carry_over(prev, store, week_ending),
    autofill(store, rep), draft_from_daily_logs(store, rep), ai_draft_progress(store, rep, ask=None)
    (local model via app.ai.review._ollama, injectable; turns the week's daily-log text into owner-ready
    bullets, each keeping its DL source; never invents - only rewrites logged facts),
    load_template()/save_template(t) (settings dir, not hard-coded: use app.settings.DIR),
    head_for(store, template) -> head dict above, build_pdf(store, rep, path, template=None) -> {"pages",
    "bytes","photo_bytes","page_map"}, estimate_size(store, rep, preset).
    Renders page 1 (+1b overflow) and photo pages (4-up default, 6-up option, captions option) itself,
    plus optional sections b, c, d, e (via B's weather_gap_line), h, i, j, k. Calls A for photos and B for
    logs. Schedule pieces reuse app/pm/schedule.py and app/pm/activity_lookahead.py (2-week meeting
    look-ahead already built); recovery status from app/pm/recovery.py (standing()) when a plan exists.
    Photos come from store attachments (store.attach / attachment_path) and from the week's Daily Logs.

### D. UI + wiring  (owner: main session)
    app/pm/owner_report_ui.py, menu entries, schema field additions, Help text.
