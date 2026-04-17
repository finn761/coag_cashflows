"""Cashflows Settings — site-wide config for the Cashflows integration."""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class CashflowsSettings(Document):
    """Single Doctype. One record per site."""

    def validate(self):
        if self.poll_interval_ms is not None and self.poll_interval_ms < 100:
            frappe.throw("Poll Interval must be at least 100ms (terminal rate limits).")
        if (
            self.payment_timeout_seconds is not None
            and self.payment_timeout_seconds < 10
        ):
            frappe.throw("Payment Timeout must be at least 10 seconds.")


def get_credentials() -> tuple[str, str]:
    """Return (api_username, api_password) from settings.

    Raises if credentials are not configured.
    """
    settings = frappe.get_cached_doc("Cashflows Settings")
    if not settings.api_username or not settings.api_password:
        frappe.throw(
            "Cashflows credentials are not configured. "
            "Go to Cashflows Settings and enter the API username and passcode.",
            title="Cashflows not configured",
        )
    # `api_password` is a Password fieldtype — Frappe decrypts on access.
    return settings.api_username, settings.get_password("api_password")


def get_timeouts() -> dict[str, int]:
    """Return timeout config as a dict of ints with safe defaults."""
    settings = frappe.get_cached_doc("Cashflows Settings")
    return {
        "connect": int(settings.connect_timeout_seconds or 3),
        "read": int(settings.read_timeout_seconds or 10),
        "poll_interval_ms": int(settings.poll_interval_ms or 500),
        "payment_timeout_seconds": int(settings.payment_timeout_seconds or 150),
        "port": int(settings.default_port or 8080),
    }
