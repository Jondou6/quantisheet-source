"""1.1.1 Help Center pages and the What's New snippet.

The pages register when app.help_111 is imported (app/helpcenter.py
imports it right after SHORTCUTS). Show Me stays off on these pages.
"""
import json
import os

from app import help_111, helpcenter


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tut(i):
    return next(t for t in helpcenter.T if t["id"] == i)


def _text(t):
    return " ".join([t["title"], t["goal"]] + t["steps"] + t["tips"])


def test_pages_register_once():
    ids = [t["id"] for t in helpcenter.T]
    assert list(help_111.PAGE_IDS) == [
        i for i in ids if i in help_111.PAGE_IDS]
    for i in help_111.PAGE_IDS:
        assert ids.count(i) == 1
        t = _tut(i)
        assert t["try"] == []
        assert t["practice"] is False
        assert len(t["steps"]) >= 3
        assert t["tips"]
    help_111.register()
    assert [t["id"] for t in helpcenter.T].count("onewindow") == 1
    keys = [k for _a, k in helpcenter.SHORTCUTS]
    assert keys.count("Ctrl+Alt+C") == 1


def test_stated_topics_are_on_a_page():
    blob = " ".join(_text(_tut(i)) for i in help_111.PAGE_IDS)
    for phrase in (
            "New Window", "Estimator", "PM", "Service", "Office",
            "quick bar", "Set Scale", "Edit Text Here", "Redact Area",
            "New RFI Here", "Paste Here", "Insert Pages", "Ctrl+K",
            "1</b> through <b>9", "Space", "F10", "Customize Shortcuts",
            "Export", "Ctrl+Alt+C", "rescaled", "sheets, boxes, rolls",
            "Tags vs Schedule", "Carry Takeoff Forward", "multiplier",
            "Color Takeoff By", "Show Only This Item", "Bulk Edit Selected",
            "Tab", "counted once", "Auto Scale (Read Sheets)",
            "Service Work Order", "Dispatch Board", "T&amp;M Tag",
            "Service Agreements", "Build-to-Service Handover",
            "Refrigerant Log", "Backflow Test Report",
            "Flat-Rate Pricebook", "Tech Recommendations", "Truck Stock",
            "Equipment &amp; Service Records",
            "Customer Quote With Options",
            "Copy Yesterday's Crews", "Checklist Templates",
            "Import Job Cost Report", "Publish to Job Cost",
            "Allow This Duplicate", "Self-Approval",
            "Rotate Payroll Key", "Waiting on Me", "Safety Meetings",
            "Save incident", "Copy yesterday's plan", "Show reminders",
            "Log call", "has this file open",
            "Up to date · last checked"):
        assert phrase in blob, phrase


def test_new_help_names_no_competing_products():
    banned = ("Bluebeam", "Adobe", "PlanSwift", "On-Screen Takeoff",
              "Excel", "AutoCAD", "DocuSign")
    for rel in ("app/help_111.py",):
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        for word in banned:
            assert word not in text, (rel, word)
