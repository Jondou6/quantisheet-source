"""Service Settings: the invoice and agreement defaults in one place
(Chief's re-test, Nov 7: the 3.5% card fee could only be changed in the
settings file). open_window(parent) shows it.

- Credit card service fee %       service_card_fee_pct     (3.5)
- Default sales tax rate          service_tax_rate         (No tax)
- Invoice terms, days             service_invoice_terms_days (30)
- Member discount on repairs %    service_member_discount_pct (10)
- Agreement visits a year         service_agreement_visits (2)
- Renew agreements automatically  service_agreement_auto_renew (on)

Each invoice and agreement keeps the values it was made with; changing a
default here changes only new ones.
"""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QLineEdit,
                               QPushButton)

from .. import dmoney, settings
from . import agreements, uiutil, workorder


class SettingsError(ValueError):
    pass


def _pct(text, what, low, high):
    t = str(text or "").strip().rstrip("%").strip()
    if dmoney.bad(t, blank_ok=False):
        raise SettingsError(f"{what} is a percent, such as 3.5.")
    v = dmoney.D(t)
    if v < low or v > high:
        raise SettingsError(f"{what} is from {low}% to {high}%.")
    return f"{v.normalize():f}"


def _int(text, what, low, high):
    try:
        v = int(str(text or "").strip())
    except ValueError:
        raise SettingsError(f"{what} is a whole number.")
    if v < low or v > high:
        raise SettingsError(f"{what} is from {low} to {high}.")
    return v


def save(card_fee_pct=None, tax_rate=None, terms_days=None,
         discount_pct=None, visits=None, auto_renew=None):
    """Check every value first, then save them all (nothing half-saved)."""
    out = {}
    if card_fee_pct is not None:
        out["service_card_fee_pct"] = _pct(card_fee_pct,
                                           "The card fee", 0, 10)
    if tax_rate is not None:
        r = str(tax_rate)
        if r not in workorder.TAX_RATES:
            raise SettingsError("Pick a sales tax rate from the list.")
        out["service_tax_rate"] = r
    if terms_days is not None:
        out["service_invoice_terms_days"] = _int(terms_days,
                                                 "Invoice terms", 0, 365)
    if discount_pct is not None:
        d = _pct(discount_pct, "The member discount", 0, 50)
        out["service_member_discount_pct"] = d
    if visits is not None:
        out["service_agreement_visits"] = _int(visits, "Visits a year",
                                               1, 12)
    if auto_renew is not None:
        out["service_agreement_auto_renew"] = bool(auto_renew)
    for k, v in out.items():
        settings.set(k, v)
    return out


class SettingsWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Service Settings", parent)
        form = QFormLayout()
        self.card_fee = QLineEdit(workorder.card_fee_pct())
        self.card_fee.setAccessibleName("Credit card service fee percent")
        form.addRow("Credit card service fee %", self.card_fee)
        self.tax = QComboBox()
        for r in workorder.TAX_RATES:
            self.tax.addItem(workorder.tax_rate_text(r), r)
        self.tax.setCurrentIndex(self.tax.findData(
            workorder.default_tax_rate()))
        form.addRow("Default sales tax", self.tax)
        self.terms = QLineEdit(str(workorder.terms_days()))
        form.addRow("Invoice terms (days, 0 = due on receipt)", self.terms)
        d = agreements.defaults()
        self.discount = QLineEdit(str(d["discount_pct"]))
        form.addRow("Member discount on repairs %", self.discount)
        self.visits = QLineEdit(str(d["visits"]))
        form.addRow("Agreement visits a year", self.visits)
        self.auto_renew = QCheckBox("Renew agreements automatically")
        self.auto_renew.setChecked(bool(d["auto_renew"]))
        form.addRow("", self.auto_renew)
        self.root.addLayout(form)
        self.save_button = QPushButton("Save")
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(lambda *_a: self.save_clicked())
        self.root.addWidget(self.save_button)
        self.finish()

    def save_clicked(self):
        def go():
            return save(card_fee_pct=self.card_fee.text(),
                        tax_rate=self.tax.currentData(),
                        terms_days=self.terms.text(),
                        discount_pct=self.discount.text(),
                        visits=self.visits.text(),
                        auto_renew=self.auto_renew.isChecked())
        if self.guard(go) is not None:
            self.msg.setText("Saved. New invoices and agreements use these; "
                             "ones already made keep theirs.")


def open_window(parent=None):
    return uiutil.show(SettingsWindow(parent))
