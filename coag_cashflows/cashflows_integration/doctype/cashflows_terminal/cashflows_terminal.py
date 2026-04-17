"""Cashflows Terminal — one record per physical SUNMI P3 device."""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from coag_cashflows.cashflows_integration.doctype.cashflows_settings.cashflows_settings import (
    get_credentials,
    get_timeouts,
)
from coag_cashflows.utils.cashflows_client import (
    CashflowsClient,
    CashflowsError,
)


class CashflowsTerminal(Document):
    """A Cashflows-connected payment terminal."""

    def validate(self):
        # Normalise IP (strip whitespace) and terminal_id (uppercase).
        if self.terminal_ip:
            self.terminal_ip = self.terminal_ip.strip()
        if self.terminal_id:
            self.terminal_id = self.terminal_id.strip().upper()

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    def get_client(self) -> CashflowsClient:
        """Return a configured client for this terminal.

        Credentials and timeouts are pulled from Cashflows Settings.
        """
        if not self.is_active:
            frappe.throw(
                f"Terminal {self.terminal_id} is disabled.",
                title="Terminal disabled",
            )

        username, password = get_credentials()
        tmo = get_timeouts()
        return CashflowsClient(
            terminal_ip=self.terminal_ip,
            username=username,
            password=password,
            port=int(self.port or tmo["port"]),
            connect_timeout=tmo["connect"],
            read_timeout=tmo["read"],
        )

    # ------------------------------------------------------------------
    # Health / enrichment
    # ------------------------------------------------------------------
    @frappe.whitelist()
    def ping(self) -> dict:
        """Ping the terminal and enrich this record with device info.

        Updates: last_ping_ok, last_ping_at, last_ping_error, serial_number, model.
        Returns a plain dict summary for the caller.
        """
        username, password = get_credentials()
        tmo = get_timeouts()
        client = CashflowsClient(
            terminal_ip=self.terminal_ip,
            username=username,
            password=password,
            port=int(self.port or tmo["port"]),
            connect_timeout=tmo["connect"],
            read_timeout=tmo["read"],
        )

        ok = False
        error: str | None = None
        device: dict = {}

        try:
            if not client.ping():
                error = "Terminal did not respond to ping."
            else:
                device = client.get_device()
                ok = True
        except CashflowsError as e:
            error = str(e)

        self.last_ping_ok = 1 if ok else 0
        self.last_ping_at = now_datetime()
        self.last_ping_error = error or ""
        if device:
            serial = device.get("serial_number")
            model = device.get("family") or device.get("model")
            if serial:
                self.serial_number = serial
            if model:
                self.model = model
        self.save(ignore_permissions=True)

        return {
            "ok": ok,
            "error": error,
            "device": device,
            "serial_number": self.serial_number,
            "model": self.model,
        }


def get_terminal(terminal_id: str) -> CashflowsTerminal:
    """Load and return an active Cashflows Terminal by id. Raises if disabled/missing."""
    if not terminal_id:
        frappe.throw("terminal_id is required.", title="Missing terminal")
    if not frappe.db.exists("Cashflows Terminal", terminal_id):
        frappe.throw(
            f"Cashflows Terminal '{terminal_id}' does not exist.",
            title="Unknown terminal",
        )
    doc = frappe.get_doc("Cashflows Terminal", terminal_id)
    if not doc.is_active:
        frappe.throw(
            f"Cashflows Terminal '{terminal_id}' is disabled.",
            title="Terminal disabled",
        )
    return doc
