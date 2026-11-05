"""What each Project Center tool holds: its fields, list columns, statuses
and who has the ball. Modelled on Procore's workflows, with fewer fields
shown up front: only fields marked ``quick`` appear when creating an item;
the rest sit under "More details".

Field types
  text, long (multi-line), date, number, money, bool, choice (options),
  person (one member), people (several members or emails), ref (another
  record: ``ref`` names the tool), lines (a small table: ``cols``),
  attachments, thread (discussion), csi (spec section / cost code).
"""
from datetime import date, timedelta

STATUS_COLORS = {
    "Draft": "muted", "Open": "accent", "Initiated": "accent",
    "Work Required": "warn", "Ready for Review": "accent2",
    "Not Accepted": "bad", "Ready to Close": "accent2", "Closed": "good",
    "Pending": "warn", "Approved": "good", "Approved as Noted": "good",
    "Revise and Resubmit": "warn", "Rejected": "bad", "Void": "muted",
    "Submitted": "accent", "In Review": "accent2", "Not Submitted": "muted",
    "Ordered": "accent", "In Fabrication": "accent2", "Shipped": "accent2",
    "Delivered": "good", "Late": "bad", "Not Ordered": "muted",
    "Scheduled": "accent", "In Progress": "accent2", "Passed": "good",
    "Failed": "bad", "Executed": "good", "Out for Signature": "accent2",
    "Will Bid": "good", "Won't Bid": "bad", "Might Bid": "warn",
    "Invited": "accent", "Bid Received": "good", "Awarded": "good",
}

RFI_REASONS = ["Clarification", "Plan/Spec Discrepancy",
               "Drawing Discrepancy", "Engineering Conflict",
               "Existing Conditions Conflict", "Substitution Request",
               "Alternate Proposal", "Owner Decision Needed",
               "Finish Schedule", "Confirmation", "Other"]
ACTIONS = ["Clarification", "Direction", "Approval", "Confirmation",
           "Information", "Review"]
IMPACT = ["Undetermined", "Yes", "No"]
SUBMITTAL_TYPES = ["Product Data", "Shop Drawings", "Samples",
                   "Certificates", "Calculations", "Test Reports",
                   "Design Data", "Mock-up", "O&M Manuals", "Warranty",
                   "Closeout", "LEED / Sustainability", "Other"]
REVIEW_RESULTS = ["", "Approved", "Approved as Noted",
                  "Revise and Resubmit", "Rejected", "For Record Only"]
CATEGORIES = ["Labor", "Subcontractor", "Material", "Equipment", "Other",
              "Overhead"]
ROLES = ["Owner", "Architect", "Engineer", "General Contractor",
         "Subcontractor", "Supplier", "Inspector", "Consultant", "Other"]


def workdays_from(start, n):
    d = start
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def today():
    return date.today().isoformat()


def in_workdays(n):
    return lambda: workdays_from(date.today(), n).isoformat()


def F(key, label, type="text", quick=False, required=False, **kw):
    d = {"key": key, "label": label, "type": type, "quick": quick,
         "required": required}
    d.update(kw)
    return d


TOOLS = {}


def tool(key, **kw):
    kw.setdefault("group", "Project")
    kw["key"] = key
    TOOLS[key] = kw
    return kw


# ------------------------------------------------------------- field tools
tool("rfi", title="RFIs", one="RFI", group="Design", icon="rfi",
     prefix="RFI-", width=3, title_field="subject",
     statuses=["Draft", "Open", "Closed"], closed=["Closed"],
     fields=[
         F("subject", "Subject", quick=True, required=True),
         F("question", "Question", "long", quick=True, required=True),
         F("to", "Assigned to", "person", quick=True, required=True,
           help="Who must answer (the architect or engineer)"),
         F("due", "Due", "date", quick=True, default=in_workdays(7)),
         F("sent", "Sent on", "date", quick=True, default=today,
           help="The day the RFI went to the architect - days open and "
                "the owner report's aging count from it"),
         F("cc", "Distribution", "people", quick=True),
         F("status", "Status", "choice", default="Open"),
         F("reason", "Reason", "choice", options=RFI_REASONS),
         F("action", "Action requested", "choice", options=ACTIONS),
         F("from", "Received from", "person", default="@me"),
         F("company", "Responsible contractor", "text"),
         F("cost_impact", "Cost impact", "choice", options=IMPACT,
           default="Undetermined"),
         F("cost_amount", "Cost impact amount", "money"),
         F("schedule_impact", "Schedule impact", "choice", options=IMPACT,
           default="Undetermined"),
         F("schedule_days", "Schedule impact (days)", "number"),
         F("drawing", "Drawing number"), F("detail", "Detail"),
         F("spec", "Spec section", "csi"), F("location", "Location"),
         F("suggestion", "Suggested answer", "long"),
         F("answer", "Official response", "long"),
         F("answered_by", "Answered by", "person"),
         F("answered", "Answered on", "date"),
         F("change_event", "Change event", "ref", ref="event"),
         F("attachments", "Attachments", "attachments"),
         F("thread", "Discussion", "thread"),
     ],
     columns=["_no", "subject", "status", "_ball", "due", "cost_impact",
              "schedule_impact", "drawing"])

tool("submittal", title="Submittals", one="Submittal", group="Design",
     icon="submittal", prefix="", width=3, title_field="title",
     number_by="spec",
     statuses=["Draft", "Not Submitted", "Submitted", "In Review",
               "Approved", "Approved as Noted", "Revise and Resubmit",
               "Rejected", "Closed"],
     closed=["Approved", "Approved as Noted", "Rejected", "Closed"],
     fields=[
         F("title", "Title", quick=True, required=True),
         F("spec", "Spec section", "csi", quick=True, required=True),
         F("sheets", "Drawing sheets",
           help="Sheets that show this work (From Spec Book fills them "
                "from the open drawing set)"),
         F("type", "Type", "choice", quick=True, options=SUBMITTAL_TYPES,
           default="Product Data"),
         F("responsible", "Responsible contractor", "person", quick=True),
         F("package", "Package", "ref", ref="subpkg"),
         F("status", "Status", "choice", default="Not Submitted"),
         F("revision", "Revision", "number", default=0),
         F("required_on_site", "Needed on site", "date", quick=True),
         F("lead_days", "Lead time (days)", "number", default=0),
         F("review_days", "Review time (days)", "number", default=10),
         F("submit_by", "Submit by", "date",
           help="Worked out from the on-site date, lead time and review "
                "time"),
         F("received", "Received from sub", "date"),
         F("workflow", "Review steps", "lines",
           cols=[("reviewer", "Reviewer", "person"),
                 ("days", "Days", "number"),
                 ("sent", "Sent", "date"), ("due", "Due", "date"),
                 ("returned", "Returned", "date"),
                 ("result", "Response", "choice", REVIEW_RESULTS),
                 ("comments", "Comments", "text")]),
         F("cc", "Distribution", "people"),
         F("description", "Description", "long"),
         F("attachments", "Attachments", "attachments"),
         F("thread", "Discussion", "thread"),
     ],
     columns=["_no", "title", "spec", "type", "status", "_ball", "submit_by",
              "required_on_site", "revision"])

tool("subpkg", title="Submittal Packages", one="Package", group="Design",
     icon="package", prefix="PKG-", width=3, title_field="title",
     statuses=["Open", "Closed"], closed=["Closed"],
     fields=[F("title", "Description", quick=True, required=True),
             F("spec", "Spec section", "csi", quick=True),
             F("responsible", "Submitting company", "person", quick=True),
             F("status", "Status", "choice", default="Open"),
             F("notes", "Notes", "long"),
             F("attachments", "Attachments", "attachments")],
     columns=["_no", "title", "spec", "responsible", "status", "_items"])

tool("transmittal", title="Transmittals", one="Transmittal",
     group="Design", icon="transmittal", prefix="T-", width=3,
     title_field="subject", statuses=["Draft", "Sent", "Acknowledged"],
     closed=["Acknowledged"],
     fields=[
         F("subject", "Subject", quick=True, required=True),
         F("to", "To", "people", quick=True, required=True),
         F("purpose", "Purpose", "choice", quick=True,
           options=["For Approval", "For Review", "For Your Use",
                    "As Requested", "For Bid", "For Construction",
                    "For Record"], default="For Review"),
         F("items", "Items", "lines", quick=True,
           cols=[("qty", "Copies", "number"), ("item", "Item", "text"),
                 ("date", "Dated", "date"), ("description", "Description",
                                             "text")]),
         F("via", "Sent via", "choice",
           options=["Email", "Download link", "Hand delivery", "Courier",
                    "Mail"], default="Email"),
         F("cc", "Copies to", "people"),
         F("status", "Status", "choice", default="Draft"),
         F("sent", "Sent on", "date"), F("due", "Response needed by",
                                         "date"),
         F("acknowledged", "Acknowledged on", "date"),
         F("acknowledged_by", "Acknowledged by", "person"),
         F("notes", "Remarks", "long"),
         F("attachments", "Attachments", "attachments"),
     ],
     columns=["_no", "subject", "to", "purpose", "status", "sent",
              "acknowledged"])

tool("punch", title="Punch List", one="Punch item", group="Field",
     icon="punch", prefix="P-", width=4, title_field="title",
     statuses=["Draft", "Initiated", "Work Required", "Ready for Review",
               "Not Accepted", "Ready to Close", "Closed"],
     closed=["Closed"],
     fields=[
         F("title", "Description", quick=True, required=True),
         F("location", "Location", quick=True),
         F("assignee", "Assignee", "person", quick=True,
           help="The sub who must fix it"),
         F("due", "Due", "date", quick=True, default=in_workdays(10)),
         F("photos", "Photos", "attachments", quick=True),
         F("status", "Status", "choice", default="Work Required"),
         F("trade", "Trade"), F("priority", "Priority", "choice",
                                options=["Low", "Normal", "High"],
                                default="Normal"),
         F("manager", "Punch manager", "person", default="@me"),
         F("final_approver", "Final approver", "person"),
         F("sheet", "Sheet"), F("pin", "Pin on sheet", "pin"),
         F("cost_code", "Cost code", "csi"),
         F("owner_status", "Owner sign-off", "choice",
           options=["", "Accepted", "Not Accepted"]),
         F("architect_status", "Architect sign-off", "choice",
           options=["", "Accepted", "Not Accepted"]),
         F("thread", "Comments", "thread"),
     ],
     columns=["_no", "title", "location", "assignee", "status", "_ball",
              "due", "priority"])

tool("observation", title="Observations", one="Observation",
     group="Field", icon="eye", prefix="OBS-", width=3,
     title_field="title",
     statuses=["Initiated", "Ready for Review", "Not Accepted", "Closed"],
     closed=["Closed"],
     fields=[
         F("title", "Title", quick=True, required=True),
         F("type", "Type", "choice", quick=True,
           options=["Safety", "Quality", "Commissioning", "Environmental",
                    "Warranty", "Work to Complete"], default="Quality"),
         F("assignee", "Assignee", "person", quick=True),
         F("location", "Location", quick=True),
         F("description", "Description", "long", quick=True),
         F("photos", "Photos", "attachments", quick=True),
         F("priority", "Priority", "choice",
           options=["Low", "Medium", "High", "Urgent"], default="Medium"),
         F("hazard", "Hazard", "choice",
           options=["", "Fall", "Electrical", "Struck by", "Caught between",
                    "Housekeeping", "PPE", "Fire", "Other"]),
         F("status", "Status", "choice", default="Initiated"),
         F("due", "Due", "date", default=in_workdays(3)),
         F("trade", "Trade"),
         F("thread", "Comments", "thread"),
     ],
     columns=["_no", "title", "type", "assignee", "status", "_ball", "due",
              "priority"])

tool("inspection", title="Inspections", one="Inspection", group="Field",
     icon="checklist", prefix="INS-", width=3, title_field="title",
     statuses=["Scheduled", "In Progress", "Passed", "Failed", "Closed"],
     closed=["Passed", "Closed"],
     fields=[
         F("title", "Title", quick=True, required=True),
         F("template", "Checklist", "template", quick=True),
         F("date", "Date", "date", quick=True, default=today),
         F("inspector", "Inspector", "person", quick=True, default="@me"),
         F("location", "Location"), F("trade", "Trade"),
         F("status", "Status", "choice", default="Scheduled"),
         F("items", "Checklist items", "lines",
           cols=[("item", "Item", "text"),
                 ("result", "Result", "choice",
                  ["", "Yes", "No", "N/A"]),
                 ("note", "Note", "text")]),
         F("photos", "Photos", "attachments"),
         F("signed_by", "Signed by", "person"),
         F("thread", "Comments", "thread"),
     ],
     columns=["_no", "title", "date", "inspector", "status", "_progress"])

tool("daily", title="Daily Log", one="Daily log", group="Field",
     icon="calendar", prefix="DL-", width=4, title_field="date", log=True,
     statuses=["Draft", "Submitted"], closed=["Submitted"],
     fields=[
         F("date", "Date", "date", quick=True, required=True,
           default=today),
         F("weather", "Weather", "weather", quick=True),
         F("manpower", "Manpower", "lines", quick=True,
           cols=[("company", "Company", "text"), ("trade", "Trade", "text"),
                 ("workers", "Workers", "number"),
                 ("hours", "Hours each", "number"),
                 ("location", "Location", "text"),
                 ("notes", "Work done", "text")]),
         F("work", "Work performed", "long", quick=True),
         F("equipment", "Equipment", "lines",
           cols=[("item", "Equipment", "text"), ("hours", "Hours", "number"),
                 ("idle", "Idle hours", "number"),
                 ("notes", "Notes", "text")]),
         F("deliveries", "Deliveries", "lines",
           cols=[("time", "Time", "text"), ("supplier", "Supplier", "text"),
                 ("contents", "Contents", "text"),
                 ("received_by", "Received by", "text")]),
         F("visitors", "Visitors", "lines",
           cols=[("name", "Name", "text"), ("company", "Company", "text"),
                 ("purpose", "Purpose", "text"), ("time", "Time", "text")]),
         F("safety", "Safety and incidents", "long"),
         F("delays", "Delays", "lines",
           cols=[("cause", "Cause", "choice",
                  ["Weather", "Owner", "Design", "Sub", "Material",
                   "Inspection", "Other"]),
                 ("hours", "Hours lost", "number"),
                 ("description", "Description", "text")]),
         F("inspections_note", "Inspections today", "long"),
         F("photos", "Photos", "attachments"),
         F("status", "Status", "choice", default="Draft"),
         F("author", "Author", "person", default="@me"),
     ],
     columns=["date", "_weekday", "_workers", "weather", "author",
              "status"])

tool("timecard", title="Time Cards", one="Time card", group="Field",
     icon="crew", prefix="TC-", width=4, title_field="date",
     statuses=["Draft", "Submitted", "Approved"], closed=["Approved"],
     fields=[
         F("date", "Date", "date", quick=True, required=True,
           default=today),
         F("foreman", "Foreman", "person", quick=True, default="@me"),
         F("crew", "Crew hours", "lines", quick=True,
           cols=[("name", "Name", "text"),
                 ("class", "Labor class (FMN, OPR, LAB...)", "text"),
                 ("hours", "Hours", "number")]),
         F("equipment", "Equipment hours", "lines", quick=True,
           cols=[("code", "Equipment code", "text"),
                 ("hours", "Hours", "number")]),
         F("production", "Quantities installed", "lines", quick=True,
           cols=[("cost_code", "Cost code", "text"),
                 ("qty", "Quantity", "number"), ("unit", "Unit", "text"),
                 ("hours", "Crew hours on it", "number")]),
         F("notes", "Notes", "long"),
         F("status", "Status", "choice", default="Draft"),
     ],
     columns=["date", "_weekday", "foreman", "status"])

tool("meeting", title="Meetings", one="Meeting", group="Project",
     icon="meeting", prefix="M-", width=3, title_field="title",
     statuses=["Agenda", "Minutes", "Distributed"], closed=["Distributed"],
     fields=[
         F("title", "Title", quick=True, required=True),
         F("type", "Type", "choice", quick=True,
           options=["OAC", "Pre-Construction", "Subcontractor", "Safety",
                    "Coordination", "Pre-Installation", "Closeout",
                    "Other"], default="OAC"),
         F("date", "Date", "date", quick=True, default=today),
         F("time", "Time", quick=True), F("location", "Location"),
         F("status", "Status", "choice", default="Agenda"),
         F("attendees", "Attendees", "lines",
           cols=[("name", "Name", "person"), ("company", "Company", "text"),
                 ("present", "Present", "choice", ["", "Yes", "No"])]),
         F("topics", "Topics", "lines", quick=True,
           cols=[("no", "No.", "text"), ("topic", "Topic", "text"),
                 ("discussion", "Discussion", "text"),
                 ("owner", "Assigned to", "person"),
                 ("due", "Due", "date"),
                 ("status", "Status", "choice",
                  ["Open", "Closed", "Info"])]),
         F("next", "Next meeting", "text"),
         F("cc", "Distribution", "people"),
         F("attachments", "Attachments", "attachments"),
     ],
     columns=["_no", "title", "type", "date", "status", "_open_topics"])

tool("activity", title="Schedule", one="Activity", group="Project",
     icon="gantt", prefix="A", width=4, title_field="name",
     statuses=["Not Started", "In Progress", "Complete"],
     closed=["Complete"], sort="_n",
     fields=[
         F("name", "Activity", quick=True, required=True),
         F("duration", "Duration (workdays)", "number", quick=True,
           default=5, help="0 makes it a milestone"),
         F("preds", "Predecessors", "lines", quick=True,
           cols=[("id", "Activity no.", "text"),
                 ("type", "Type (FS, SS, FF, SF)", "text"),
                 ("lag", "Lag (days)", "number")],
           help="What must happen first. Finish-to-start unless you say "
                "otherwise"),
         F("start", "Start no earlier than", "date", quick=True,
           help="Leave blank to start as soon as the predecessors allow"),
         F("area", "Area / phase", quick=True),
         F("responsible", "Responsible", "person", quick=True),
         F("status", "Status", "choice", default="Not Started"),
         F("percent", "% complete", "number"),
         F("actual_start", "Actual start", "date"),
         F("actual_finish", "Actual finish", "date"),
         F("cost_code", "Cost code", "csi"),
         F("baseline_start", "Baseline start", "date"),
         F("baseline_finish", "Baseline finish", "date"),
         F("long_lead_label", "Long-lead item name (owner report)"),
         F("owner_co", "Owning subcontractor",
           help="Master Schedule: the sub whose updates may change this "
                "activity. Blank = the GC's"),
         F("notes", "Notes", "long"),
     ],
     columns=["_no", "name", "area", "_start", "duration", "_finish",
              "percent", "_float", "responsible"])

tool("issue", title="Issues", one="Issue", group="Project", icon="flag",
     prefix="I-", width=3, title_field="title",
     statuses=["Open", "Closed"], closed=["Closed"],
     fields=[F("title", "Title", quick=True, required=True),
             F("assignee", "Responsible", "person", quick=True),
             F("due", "Due", "date", quick=True, default=in_workdays(5)),
             F("description", "Description", "long", quick=True),
             F("status", "Status", "choice", default="Open"),
             F("company", "Company"), F("location", "Location"),
             F("priority", "Priority", "choice",
               options=["Low", "Normal", "High"], default="Normal"),
             F("meeting", "From meeting", "ref", ref="meeting"),
             F("closed_on", "Closed on", "date"),
             F("attachments", "Attachments", "attachments"),
             F("thread", "Comments", "thread")],
     columns=["_no", "title", "assignee", "status", "_ball", "due",
              "priority"])

DELAY_CAUSES = ["Owner change or decision", "Design error / RFI response",
                "Late owner-furnished items", "Differing site conditions",
                "Permit or inspection", "Weather beyond normal",
                "Labor / crew shortage", "Subcontractor performance",
                "Material delivery", "Equipment", "Other"]
DELAY_RESPONSIBILITY = ["Owner", "Contractor", "Third party",
                        "Force majeure / weather", "Concurrent / shared"]

tool("delay", title="Delay Log", one="Delay event", group="Project",
     icon="flag", prefix="D-", width=3, title_field="title",
     statuses=["Open", "Notice Given", "Analyzed", "Submitted", "Granted",
               "Denied", "Withdrawn"],
     closed=["Granted", "Denied", "Withdrawn"],
     fields=[F("title", "Title", quick=True, required=True),
             F("description", "Description", "long", quick=True),
             F("cause", "Cause", "choice", quick=True,
               options=DELAY_CAUSES, default="Owner change or decision"),
             F("responsibility", "Responsibility", "choice", quick=True,
               options=DELAY_RESPONSIBILITY, default="Owner"),
             F("event_start", "Event start", "date", quick=True,
               required=True),
             F("event_end", "Event end", "date", quick=True),
             F("status", "Status", "choice", default="Open"),
             F("notice_date", "Notice given on", "date",
               help="Written notice to the owner - the contract sets the "
                    "deadline"),
             F("notice_due", "Notice due by", "date",
               help="From the owner contract's delay notice days (Project "
                    "> Owner contract terms)"),
             F("notice_to", "Notice sent to"),
             F("notice_ref", "Notice reference",
               help="Letter, email or RFI number"),
             F("affected", "Affected activities", "lines",
               cols=[("id", "Activity no.", "text"),
                     ("days", "Added workdays", "number"),
                     ("note", "Note", "text")],
               help="Existing activities the event made longer"),
             F("fragnet", "Fragnet (new activities)", "lines",
               cols=[("name", "New activity", "text"),
                     ("duration", "Duration (workdays)", "number"),
                     ("pred", "Predecessor no.", "text"),
                     ("succ", "Successor no.", "text")],
               help="Activities the event added, tied into the schedule "
                    "for the time impact analysis"),
             F("refs", "References", "lines",
               cols=[("kind", "Kind (RFI, CE, daily log...)", "text"),
                     ("number", "Number", "text"),
                     ("note", "Note", "text")]),
             F("days_requested", "Days requested", "number"),
             F("days_granted", "Days granted", "number"),
             F("granted_on", "Granted on", "date",
               help="When the owner granted the time - the owner report "
                    "moves the contract finish from this date on"),
             F("cost", "Cost", "money"),
             F("attachments", "Attachments", "attachments"),
             F("thread", "Comments", "thread")],
     columns=["_no", "title", "cause", "responsibility", "event_start",
              "status", "days_requested", "days_granted"])

tool("permit", title="Permits", one="Permit", group="Project",
     icon="flag", prefix="PER-", width=3, title_field="title",
     statuses=["Applied", "Issued", "Active", "Expired", "Closed"],
     closed=["Expired", "Closed"],
     fields=[F("title", "Permit / inspection", quick=True, required=True),
             F("agency", "Agency", quick=True),
             F("permit_no", "Permit no."),
             F("status", "Status", "choice", default="Applied"),
             F("applied", "Applied on", "date"),
             F("issued", "Issued on", "date"),
             F("expires", "Expires", "date"),
             F("next_inspection", "Next inspection"),
             F("notes", "Notes", "long"),
             F("attachments", "Attachments", "attachments")],
     columns=["_no", "title", "agency", "status", "issued",
              "next_inspection"])

tool("expedite", title="Expediting", one="Expediting item",
     group="Project", icon="truck", prefix="EX-", width=3,
     title_field="item",
     statuses=["Not Ordered", "Ordered", "In Fabrication", "Shipped",
               "Delivered", "Late"], closed=["Delivered"],
     fields=[F("item", "Item", quick=True, required=True),
             F("supplier", "Supplier", quick=True),
             F("needed", "Needed on site", "date", quick=True),
             F("status", "Status", "choice", default="Not Ordered"),
             F("spec", "Spec section", "csi"),
             F("submittal", "Submittal", "ref", ref="submittal"),
             F("commitment", "Purchase order", "ref", ref="commitment"),
             F("lead_days", "Lead time (days)", "number"),
             F("ordered", "Ordered on", "date"),
             F("promised", "Promised ship date", "date"),
             F("expected", "Expected delivery", "date"),
             F("delivered", "Delivered on", "date"),
             F("tracking", "Tracking / BOL"),
             F("notes", "Notes", "long")],
     columns=["_no", "item", "supplier", "status", "needed", "expected",
              "_late"])

# ------------------------------------------------------------- cost
EVENT_REASONS = ["Owner Request", "Design Change", "Unforeseen Condition",
                 "Allowance", "Value Engineering", "Code Requirement",
                 "Error / Omission", "Other"]

tool("budget", title="Budget", one="Budget line", group="Cost",
     icon="budget", prefix="", width=1, title_field="description",
     statuses=[], sort="cost_code",
     fields=[F("cost_code", "Cost code", "csi", quick=True, required=True),
             F("description", "Description", quick=True, required=True),
             F("category", "Category", "choice", quick=True,
               options=CATEGORIES, default="Subcontractor"),
             F("original", "Original budget", "money", quick=True),
             F("units", "Quantity", "number"), F("unit", "Unit"),
             F("etc", "Cost to complete (your estimate)", "money",
               help="Leave blank to use what's left of the budget or "
                    "commitment"),
             F("risk", "Risk on remaining work", "money"),
             F("notes", "Notes", "long")],
     columns=["cost_code", "description", "category", "original",
              "_approved", "_revised", "_committed", "_actual", "_fac",
              "_variance", "_flag"])

tool("contract", title="Prime Contract", one="Contract line",
     group="Cost", icon="contract", prefix="", width=1,
     title_field="description", statuses=[], sort="item",
     fields=[F("item", "Item no.", quick=True, required=True),
             F("description", "Description", quick=True, required=True),
             F("scheduled", "Scheduled value", "money", quick=True,
               required=True),
             F("cost_code", "Cost code", "csi")],
     columns=["item", "description", "cost_code", "scheduled", "_billed",
              "_pct"])

tool("commitment", title="Commitments", one="Commitment", group="Cost",
     icon="commitment", prefix="SC-", width=3, title_field="title",
     statuses=["Draft", "Out for Signature", "Executed", "Closed", "Void"],
     closed=["Closed", "Void"],
     fields=[F("title", "Title", quick=True, required=True),
             F("vendor", "Subcontractor / supplier", "person", quick=True,
               required=True),
             F("type", "Type", "choice", quick=True,
               options=["Subcontract", "Purchase Order"],
               default="Subcontract"),
             F("lines", "Schedule of values", "lines", quick=True,
               cols=[("cost_code", "Cost code", "text"),
                     ("description", "Description", "text"),
                     ("amount", "Amount", "number")]),
             F("status", "Status", "choice", default="Draft"),
             F("retainage", "Retainage %", "number", default=10),
             F("executed", "Executed on", "date"),
             F("start", "Start", "date"), F("finish", "Finish", "date"),
             F("insurance_expires", "Insurance expires", "date"),
             F("license_expires", "License expires", "date"),
             F("w9", "W-9 on file", "choice", options=["", "Yes", "No"]),
             F("scope", "Scope of work", "long"),
             F("exclusions", "Exclusions", "long"),
             # contract terms (PM review NW-13), checked against the owner
             # contract by Project > Check subcontract terms
             F("claim_notice_days", "Claim notice (days)", "number"),
             F("delay_notice_days", "Delay notice (days)", "number"),
             F("ld_per_day", "Liquidated damages ($/day)", "money"),
             F("pay_when_paid", "Pay-when-paid", "choice",
               options=["", "Yes", "No"]),
             F("pay_days", "Payment due (days)", "number"),
             F("warranty_months", "Warranty (months)", "number"),
             F("umbrella_limit", "Umbrella / excess limit ($)", "money"),
             F("flow_down", "Flow-down clause", "choice",
               options=["", "Yes", "No"]),
             F("attachments", "Attachments", "attachments")],
     columns=["_no", "title", "vendor", "status", "_original", "_approved",
              "_revised", "_invoiced", "_paid", "_remaining", "_compliance"])

tool("event", title="Change Events", one="Change event", group="Cost",
     icon="event", prefix="CE-", width=3, title_field="title",
     statuses=["Open", "Pending", "Approved", "Rejected", "Void"],
     closed=["Approved", "Rejected", "Void"],
     fields=[F("title", "Title", quick=True, required=True),
             F("reason", "Reason", "choice", quick=True,
               options=EVENT_REASONS, default="Owner Request"),
             F("scope", "Scope", "choice", quick=True,
               options=["Out of Scope", "In Scope", "To Be Determined"],
               default="Out of Scope"),
             F("lines", "Costs and price", "lines", quick=True,
               cols=[("cost_code", "Cost code", "text"),
                     ("description", "Description", "text"),
                     ("vendor", "Vendor", "text"),
                     ("cost", "Cost", "number"),
                     ("markup", "Markup %", "number"),
                     ("price", "Price to owner", "number")]),
             F("status", "Status", "choice", default="Open"),
             F("days", "Schedule days", "number"),
             F("rfi", "From RFI", "ref", ref="rfi"),
             F("submitted", "Sent to owner", "date"),
             F("approved", "Owner approved", "date"),
             F("co_no", "Change order no."),
             F("commitments_approved", "Sub change orders approved",
               "choice", options=["", "Yes", "No"]),
             F("description", "Description", "long"),
             F("attachments", "Attachments", "attachments")],
     columns=["_no", "title", "reason", "status", "_cost", "_price",
              "co_no", "days"])

tool("cost", title="Direct Costs & Invoices", one="Cost", group="Cost",
     icon="dollar", prefix="DC-", width=4, title_field="description",
     statuses=["Pending", "Approved", "Paid"], closed=["Paid"],
     fields=[F("date", "Date", "date", quick=True, required=True,
               default=today),
             F("vendor", "Vendor", "person", quick=True, required=True),
             F("cost_code", "Cost code", "csi", quick=True, required=True),
             F("amount", "Amount", "money", quick=True, required=True),
             F("description", "Description", quick=True),
             F("quantity", "Quantity installed (for unit costs)", "number"),
             F("unit", "Unit (LF, CY, EA...)"),
             F("commitment", "Against commitment", "ref",
               ref="commitment"),
             F("invoice", "Invoice no."),
             F("category", "Category", "choice", options=CATEGORIES,
               default="Material"),
             F("retainage", "Retainage held", "money"),
             F("waiver", "Lien waiver", "choice",
               options=["", "Conditional received",
                        "Unconditional received", "Not required"]),
             F("status", "Status", "choice", default="Pending"),
             F("approved_by", "Approved by", "person"),
             F("paid", "Paid on", "date"),
             F("attachments", "Attachments", "attachments")],
     columns=["_no", "date", "vendor", "cost_code", "description",
              "amount", "status", "_compliance"])

tool("subpay", title="Sub Pay Apps", one="Sub pay application",
     group="Cost", icon="pay_app", prefix="SPA-", width=3,
     title_field="period_to",
     statuses=["Draft", "Submitted", "Approved", "Rejected", "Billed"],
     closed=["Rejected", "Billed"],
     fields=[F("commitment", "Subcontract", "ref", ref="commitment",
               quick=True, required=True),
             F("period_to", "Period to", "date", quick=True, required=True,
               default=today),
             F("lines", "Work this period", "lines",
               cols=[("cost_code", "Cost code", "text"),
                     ("description", "Description", "text"),
                     ("scheduled", "Scheduled", "number"),
                     ("previous", "Previous", "number"),
                     ("this_period", "This period", "number"),
                     ("stored", "Stored materials", "number")]),
             F("status", "Status", "choice", default="Draft"),
             F("retainage", "Retainage %", "number", default=10),
             F("reviewed_by", "Reviewed by", "person"),
             F("review_note", "Review note", "long"),
             F("billed_in", "Billed in owner pay app", "text"),
             F("attachments", "Attachments", "attachments")],
     columns=["_no", "commitment", "period_to", "status", "_this_period"])

tool("payapp", title="Owner Pay Apps", one="Pay application",
     group="Cost", icon="pay_app", prefix="", width=1,
     title_field="period_to",
     statuses=["Draft", "Submitted", "Certified", "Paid"],
     closed=["Paid"],
     fields=[F("period_to", "Period to", "date", quick=True, required=True,
               default=today),
             F("lines", "Work this period", "lines",
               cols=[("item", "Item", "text"),
                     ("description", "Description", "text"),
                     ("scheduled", "Scheduled", "number"),
                     ("previous", "Previous", "number"),
                     ("this_period", "This period", "number"),
                     ("stored", "Stored materials", "number")]),
             F("status", "Status", "choice", default="Draft"),
             F("date", "Application date", "date", default=today),
             F("retainage_work", "Retainage on work %", "number",
               default=10),
             F("retainage_stored", "Retainage on stored %", "number",
               default=10),
             F("retainage_note", "Retainage rule", "text"),
             F("received", "Payment received", "money"),
             F("received_on", "Received on", "date"),
             F("notes", "Notes", "long"),
             F("attachments", "Attachments", "attachments")],
     columns=["_no", "period_to", "status", "_this_period", "_due",
              "received"])

# ------------------------------------------------------------- bidding
tool("bidpkg", title="Bid Packages", one="Bid package", group="Bidding",
     icon="bidtabs", prefix="BP-", width=3, title_field="title",
     statuses=["Draft", "Open", "Closed", "Awarded"],
     closed=["Closed", "Awarded"],
     fields=[F("title", "Package", quick=True, required=True),
             F("trades", "Trade / spec section", "csi", quick=True),
             F("due", "Bids due", "date", quick=True,
               default=in_workdays(10)),
             F("scope", "Scope of work", "long", quick=True),
             F("documents", "Bid documents", "attachments", quick=True),
             F("bidders", "Bidders", "lines", quick=True,
               cols=[("company", "Company", "text"),
                     ("contact", "Contact", "text"),
                     ("email", "Email", "text"),
                     ("status", "Status", "choice",
                      ["", "Invited", "Viewed", "Will Bid", "Won't Bid",
                       "Might Bid", "Bid Received", "Awarded"]),
                     ("amount", "Bid amount", "number"),
                     ("acks", "Addenda ack'd", "text"),
                     ("note", "Note", "text")]),
             F("status", "Status", "choice", default="Draft"),
             F("due_time", "Due time", default="2:00 PM"),
             F("sealed", "Sealed bids (numbers hidden until the bid "
                         "opening, after the due time)", "choice",
               options=["", "Yes"]),
             F("prebid", "Pre-bid meeting"),
             F("site_visit", "Site visit"),
             F("rfi_due", "Questions due by", "date"),
             F("contact", "Questions to", "person", default="@me"),
             F("specs", "Spec sections"),
             F("sheets", "Drawing sheets"),
             F("form", "Bid form (every bidder prices these lines)",
               "lines",
               cols=[("item", "Item", "text"),
                     ("description", "Description", "text"),
                     ("type", "Type", "choice",
                      ["Lump sum", "Unit price", "Allowance", "Alternate",
                       "Yes / No", "Text"]),
                     ("qty", "Qty / allowance $", "number"),
                     ("unit", "Unit", "text"),
                     ("note", "Note to bidders", "text")]),
             F("addenda", "Addenda", "lines",
               cols=[("number", "No.", "text"), ("date", "Issued", "date"),
                     ("description", "Description", "text")]),
             F("plugs", "Leveling plugs and adjustments", "lines",
               cols=[("bidder", "Bidder", "text"),
                     ("item", "Item", "text"),
                     ("kind", "Kind", "choice",
                      ["Plug", "Included", "Override", "Adjustment"]),
                     ("amount", "Amount", "number"),
                     ("note", "Why", "text")]),
             F("awarded_to", "Awarded to"),
             F("award_amount", "Award amount", "money"),
             F("letters", "Award and regret letters", "attachments"),
             F("attachments", "Other files", "attachments")],
     columns=["_no", "title", "trades", "due", "status", "_invited",
              "_will", "_received", "_low"])

# ------------------------------------------------------------- team
tool("member", title="Directory", one="Person", group="Team",
     icon="people", prefix="", width=1, title_field="name",
     statuses=[], fields=[
         F("name", "Name", quick=True, required=True),
         F("company", "Company", quick=True),
         F("email", "Email", quick=True),
         F("role", "Role", "choice", quick=True, options=ROLES,
           default="Subcontractor"),
         F("phone", "Phone"), F("trade", "Trade"),
         F("title_", "Job title"), F("notes", "Notes", "long")],
     columns=["name", "company", "role", "email", "phone", "trade"])

tool("distlist", title="Distribution Lists", one="List", group="Team",
     icon="mail", prefix="", width=1, title_field="name", statuses=[],
     fields=[F("name", "Name", quick=True, required=True),
             F("people", "People", "people", quick=True)],
     columns=["name", "people"])


def is_log(key):
    """A log (Daily Log, Time Cards): every entry stays useful once it's
    submitted, so the list opens on All and the nav counts them all (PM
    review NW-02: 13 submitted dailies were hidden behind 'Open')."""
    return bool(TOOLS.get(key, {}).get("log"))


def default_chip(key):
    t = TOOLS.get(key, {})
    return "Open" if t.get("statuses") and not t.get("log") else "All"


def nav_count(key, recs):
    t = TOOLS.get(key, {})
    if t.get("statuses") and not t.get("log"):
        return sum(1 for r in recs if not is_closed(key, r))
    return len(recs)


def line_totals(cols, rows):
    """Footer totals of a lines table: [(label, number, bad cells)].
    `cols` (key, label, type); `rows` [{key: text}]. A per-worker hours
    column isn't added up on its own: with a workers column next to it the
    total is man-hours, workers x hours on each row (PM review NW-03:
    'Hours each: 17' for 6 x 8 h + 2 x 9 h)."""
    from .. import dmoney
    keys = [c[0] for c in cols]
    each = "workers" in keys and "hours" in keys
    out = []
    for key, label, typ, *_ in cols:
        if typ != "number" or (each and key == "hours"):
            continue
        s, bad = 0.0, 0
        for r in rows:
            t = str(r.get(key) or "")
            if dmoney.bad(t):
                bad += 1
            elif t.strip():
                s += float(dmoney.D(t))
        out.append((label, s, bad))
    if each:
        mh, bad = 0.0, 0
        for r in rows:
            w, h = str(r.get("workers") or ""), str(r.get("hours") or "")
            if dmoney.bad(w) or dmoney.bad(h):
                bad += 1
            elif w.strip() and h.strip():
                mh += float(dmoney.D(w)) * float(dmoney.D(h))
        out.append(("Man-hours", mh, bad))
    return out


def fields_of(key):
    return TOOLS[key]["fields"]


def field(key, fkey):
    return next((f for f in TOOLS[key]["fields"] if f["key"] == fkey), None)


def defaults(key, me=""):
    out = {}
    for f in TOOLS[key]["fields"]:
        d = f.get("default")
        if d is None:
            continue
        if callable(d):
            d = d()
        if d == "@me":
            d = me
        out[f["key"]] = d
    return out


def is_closed(key, rec):
    t = TOOLS[key]
    return rec.get("status") in t.get("closed", ())


def ball_in_court(key, rec):
    """Who must act next (Procore's "ball in court"), always as text: a
    "to" with several people (a list) used to break the callers (#41)."""
    v = _ball(key, rec)
    if isinstance(v, (list, tuple)):
        v = "; ".join(str(x.get("name") if isinstance(x, dict) else x)
                      for x in v if x)
    elif isinstance(v, dict):
        v = v.get("name") or ""
    return str(v or "")


def _ball(key, rec):
    st = rec.get("status")
    if key == "rfi":
        if st == "Draft":
            return rec.get("from") or rec.get("_by")
        if st == "Open":
            return rec.get("to")
        return ""
    if key == "submittal":
        if st in ("Draft", "Not Submitted", "Revise and Resubmit"):
            return rec.get("responsible")
        for step in rec.get("workflow") or []:
            if not step.get("returned"):
                return step.get("reviewer")
        return ""
    if key == "punch":
        return {"Initiated": rec.get("assignee"),
                "Work Required": rec.get("assignee"),
                "Not Accepted": rec.get("assignee"),
                "Ready for Review": rec.get("manager"),
                "Ready to Close": rec.get("final_approver") or
                rec.get("manager")}.get(st, "")
    if key == "observation":
        return {"Initiated": rec.get("assignee"),
                "Not Accepted": rec.get("assignee"),
                "Ready for Review": rec.get("_by")}.get(st, "")
    if key == "issue":
        return rec.get("assignee") if st == "Open" else ""
    if key == "activity":
        return rec.get("responsible") if st == "In Progress" else ""
    if key == "transmittal":
        return (rec.get("to") or [""])[0] if st == "Sent" else ""
    return ""


def submit_by(rec):
    """Submittal due date: needed on site - lead time - review time."""
    need = rec.get("required_on_site")
    if not need:
        return ""
    try:
        d = date.fromisoformat(need)
    except ValueError:
        return ""
    days = int(rec.get("lead_days") or 0) + int(rec.get("review_days") or 0)
    return (d - timedelta(days=days)).isoformat()


def is_overdue(key, rec, today_=None):
    due = rec.get("due") or (rec.get("submit_by") if key == "submittal"
                             else "")
    if not due or is_closed(key, rec):
        return False
    return due < (today_ or date.today().isoformat())


def groups():
    order = ["Project", "Field", "Design", "Cost", "Bidding", "Documents",
             "Team"]
    out = {g: [] for g in order}
    for t in TOOLS.values():
        out.setdefault(t["group"], []).append(t)
    return [(g, ts) for g, ts in out.items() if ts]
