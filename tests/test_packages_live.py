"""Nov 4: live package status with carrier keys. Fake carrier answers
only - nothing goes on the network in tests."""
import json
import os

import pytest

from app import packages, packages_live as PL


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path))
    PL._tokens.clear()
    return tmp_path


def fake(routes):
    calls = []

    def http(method, url, headers=None, data=None):
        calls.append((method, url, headers or {}, data))
        for key, ans in routes.items():
            if key in url:
                if isinstance(ans, Exception):
                    raise ans
                return ans
        raise AssertionError("unexpected " + url)
    http.calls = calls
    return http


def test_keys_saved_only_when_complete(cfg):
    PL.save_keys({"UPS": {"client_id": "a", "client_secret": ""},
                  "DHL": {"api_key": "k1"}})
    k = PL.load_keys()
    assert "UPS" not in k and k["DHL"] == {"api_key": "k1"}
    assert PL.has_keys("DHL") and not PL.has_keys("FedEx")
    assert os.path.isfile(os.path.join(str(cfg), "carrier_keys.json"))
    assert PL.status("FedEx", "123456789012") is None        # no keys


def test_each_carrier(cfg):
    keys = {"UPS": {"client_id": "i", "client_secret": "s"},
            "FedEx": {"api_key": "i", "secret_key": "s"},
            "USPS": {"consumer_key": "i", "consumer_secret": "s"},
            "DHL": {"api_key": "k"}}
    http = fake({
        "/security/v1/oauth/token": {"access_token": "T1", "expires_in": 3600},
        "/api/track/v1/details/": {"trackResponse": {"shipment": [{
            "package": [{"currentStatus": {"description": "Delivered"},
                         "activity": [{"status": {"description":
                                                  "Delivered"},
                                       "location": {"address": {
                                           "city": "AIKEN",
                                           "stateProvince": "SC"}},
                                       "date": "20261103", "time": "1015"}],
                         "deliveryDate": [{"date": "20261103"}]}]}]}},
        "/oauth/token": {"access_token": "T2", "expires_in": 3600},
        "/track/v1/trackingnumbers": {"output": {"completeTrackResults": [{
            "trackResults": [{"latestStatusDetail": {
                "code": "IT", "description": "In transit"},
                "dateAndTimes": [{"type": "ESTIMATED_DELIVERY",
                                  "dateTime": "2026-11-06T20:00:00"}],
                "scanEvents": [{"eventDescription": "Departed FedEx hub",
                                "date": "2026-11-04T05:00:00",
                                "scanLocation": {"city": "MEMPHIS",
                                                 "stateOrProvinceCode":
                                                 "TN"}}]}]}]}},
        "/oauth2/v3/token": {"access_token": "T3", "expires_in": 3600},
        "/tracking/v3/tracking/": {"statusSummary": "Out for delivery",
                                   "status": "Out for Delivery",
                                   "expectedDeliveryDate": "2026-11-04",
                                   "trackingEvents": [{
                                       "eventType": "Out for Delivery",
                                       "eventCity": "AIKEN",
                                       "eventState": "SC"}]},
        "/track/shipments": {"shipments": [{"status": {
            "statusCode": "transit", "description": "Processed",
            "timestamp": "2026-11-04T08:00:00"},
            "estimatedTimeOfDelivery": "2026-11-07"}]}})
    u = PL.status("UPS", "1Z999AA10123456784", keys, http)
    assert u["delivered"] and "AIKEN" in u["last_event"]
    f = PL.status("FedEx", "123456789012", keys, http)
    assert f["status"] == "In transit" and f["eta"].startswith("2026-11-06")
    assert not f["delivered"]
    s = PL.status("USPS", "9400100000000000000000", keys, http)
    assert s["status"] == "Out for delivery" and not s["delivered"]
    d = PL.status("DHL", "1234567890", keys, http)
    assert d["eta"] == "2026-11-07"
    dhl = [c for c in http.calls if "/track/shipments" in c[1]][0]
    assert dhl[2]["DHL-API-Key"] == "k"
    # tokens are reused
    PL.status("UPS", "1Z999AA10123456784", keys, http)
    assert sum("/security/v1/oauth/token" in c[1] for c in http.calls) == 1


def test_check_marks_delivered_and_reports_errors(cfg):
    items = []
    packages.add(items, "1234567890")                    # DHL
    packages.add(items, "123456789012")                  # FedEx, no keys
    keys = {"DHL": {"api_key": "k"}}
    http = fake({"/track/shipments": {"shipments": [{"status": {
        "statusCode": "delivered", "description": "Delivered"}}]}})
    n, errors = PL.check(items, keys, http)
    assert n == 1 and not errors and items[0]["delivered"]
    assert items[0]["live"]["status"] == "Delivered" and items[0]["checked"]
    assert "live" not in items[1]
    items[0]["delivered"] = False
    bad = fake({"/track/shipments": PL.LiveError("too many lookups today")})
    n, errors = PL.check(items, keys, bad)
    assert n == 0 and "too many" in errors["1234567890"]


def test_offline_policy_stops_lookups(cfg, monkeypatch):
    from app import policy
    monkeypatch.setattr(policy, "get", lambda name, default=None:
                        True if name == "OfflineMode" else default)
    assert PL.status("DHL", "1234567890", {"DHL": {"api_key": "k"}},
                     fake({})) is None


def test_window_buttons(cfg, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: 0))
    from app import packages_ui
    items = []
    packages.add(items, "1234567890")
    packages.save(items)
    d = packages_ui.PackageTracker()
    assert d.check_status() == 0                         # no keys yet
    d.carrier_keys({"DHL": {"api_key": "k"}})
    n = d.check_status(http=fake({"/track/shipments": {"shipments": [{
        "status": {"statusCode": "transit", "description": "Processed"},
        "estimatedTimeOfDelivery": "2026-11-07"}]}}))
    assert n == 1
    assert "Processed" in d.table.item(0, 9).text()
    assert "due 2026-11-07" in d.table.item(0, 9).text()
    d.close()
