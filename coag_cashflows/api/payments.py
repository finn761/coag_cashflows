"""Whitelisted payment API for the POS Next frontend.

Endpoints (called via `frappe.call` from the browser):

- ``coag_cashflows.api.payments.initiate_payment``
  POST { terminal_id, amount_pence, pos_invoice? } -> { txn_id, status, ... }

- ``coag_cashflows.api.payments.check_payment_status``
  POST { terminal_id, txn_id } -> { status, result, auth_code, ... }

- ``coag_cashflows.api.payments.ping_terminal``
  POST { terminal_id } -> { ok, device, serial_number, model }

Two stations hit two different terminals in parallel safely because every call
is parameterised by ``terminal_id``; there is no shared state in this module.
"""

from __future__ import annotations

from typing import Any

import frappe

from coag_cashflows.cashflows_integration.doctype.cashflows_terminal.cashflows_terminal import (
    get_terminal,
)
from coag_cashflows.utils.cashflows_client import (
    CashflowsAPIError,
    CashflowsError,
    CashflowsUnreachable,
    TransactionResult,
)


# -------- internal helpers --------


def _serialise(result: TransactionResult) -> dict[str, Any]:
    """Convert a TransactionResult into a JSON-safe dict for the browser."""
    return {
        "txn_id": result.txn_id,
        "status": result.status,
        "is_active": result.is_active,
        "result": result.result,
        "amount_pence": result.amount_pence,
        "auth_code": result.auth_code,
        "card_brand": result.card_brand,
        "last_4": result.last_4,
        "merchant_id": result.merchant_id,
        "reference_number": result.reference_number,
        "status_details": result.status_details,
    }


def _enrich_terminal_from_txn(terminal_id: str, result: TransactionResult) -> None:
    """Capture MID/TID onto the Terminal record the first time we see them."""
    if not result.merchant_id:
        return
    try:
        doc = frappe.get_doc("Cashflows Terminal", terminal_id)
    except frappe.DoesNotExistError:
        return

    changed = False
    if result.merchant_id and not doc.merchant_id:
        doc.merchant_id = result.merchant_id
        changed = True

    tid = (result.raw.get("online_request") or {}).get("terminal_id")
    if tid and not doc.terminal_acquirer_id:
        doc.terminal_acquirer_id = str(tid)
        changed = True

    if changed:
        doc.save(ignore_permissions=True)


def _write_result_to_invoice(pos_invoice: str | None, terminal_id: str, result: TransactionResult) -> None:
    """Stamp Cashflows details onto the POS Invoice if one was passed.

    Silently skipped if no invoice, if the invoice doesn't exist, or if the
    custom fields have not yet been installed (robust to partial setup).
    """
    if not pos_invoice:
        return
    if not frappe.db.exists("POS Invoice", pos_invoice):
        return

    updates = {
        "custom_cashflows_terminal": terminal_id,
        "custom_cashflows_txn_id": result.txn_id,
        "custom_cashflows_auth_code": result.auth_code,
        "custom_cashflows_card_brand": result.card_brand,
        "custom_cashflows_last_4": result.last_4,
        "custom_cashflows_merchant_id": result.merchant_id,
    }
    try:
        frappe.db.set_value(
            "POS Invoice",
            pos_invoice,
            {k: v for k, v in updates.items() if v is not None},
            update_modified=False,
        )
    except Exception:
        # Custom fields may not yet be installed; log and carry on.
        frappe.log_error(
            title="coag_cashflows: write POS Invoice failed",
            message=frappe.get_traceback(),
        )


# -------- whitelisted API --------


@frappe.whitelist()
def initiate_payment(
    terminal_id: str,
    amount_pence: int | str,
    pos_invoice: str | None = None,
) -> dict[str, Any]:
    """Start a sale on the specified terminal. Returns immediately.

    Parameters
    ----------
    terminal_id : str
        The Cashflows Terminal record id (e.g. "BAR-1").
    amount_pence : int
        Amount in pence (e.g. 405 for £4.05).
    pos_invoice : str, optional
        If provided, the resulting transaction details are stamped onto the POS
        Invoice when the transaction completes (via check_payment_status).
    """
    try:
        amount_pence_int = int(amount_pence)
    except (TypeError, ValueError):
        frappe.throw("amount_pence must be an integer (pence).")

    if amount_pence_int < 1:
        frappe.throw("amount_pence must be at least 1.")

    terminal = get_terminal(terminal_id)
    client = terminal.get_client()

    try:
        result = client.initiate_sale(amount_pence_int)
    except CashflowsUnreachable as e:
        frappe.throw(f"Terminal '{terminal_id}' is not reachable: {e}")
    except CashflowsAPIError as e:
        frappe.throw(f"Terminal '{terminal_id}' rejected the sale: {e}")
    except CashflowsError as e:
        frappe.throw(f"Cashflows error: {e}")

    return {
        **_serialise(result),
        "terminal_id": terminal_id,
        "pos_invoice": pos_invoice,
    }


@frappe.whitelist()
def check_payment_status(
    terminal_id: str,
    txn_id: str,
    pos_invoice: str | None = None,
) -> dict[str, Any]:
    """Return the current state of a transaction.

    The frontend polls this endpoint every ``poll_interval_ms`` (from
    Cashflows Settings) until ``is_active`` is False. When the transaction
    finalises, the POS Invoice (if provided) is stamped with the result.
    """
    if not txn_id:
        frappe.throw("txn_id is required.")

    terminal = get_terminal(terminal_id)
    client = terminal.get_client()

    try:
        result = client.get_transaction(txn_id)
    except CashflowsUnreachable as e:
        frappe.throw(f"Terminal '{terminal_id}' is not reachable: {e}")
    except CashflowsError as e:
        frappe.throw(f"Cashflows error: {e}")

    # On completion, capture MID/TID onto the terminal and invoice.
    if not result.is_active:
        _enrich_terminal_from_txn(terminal_id, result)
        if result.result == "approved":
            _write_result_to_invoice(pos_invoice, terminal_id, result)

    return {
        **_serialise(result),
        "terminal_id": terminal_id,
        "pos_invoice": pos_invoice,
    }


@frappe.whitelist()
def ping_terminal(terminal_id: str) -> dict[str, Any]:
    """Ping a terminal and return its device info. Updates the terminal record."""
    terminal = get_terminal(terminal_id)
    return terminal.ping()


@frappe.whitelist()
def list_terminals() -> list[dict[str, Any]]:
    """Return minimal info about every active terminal. Useful for the station picker."""
    rows = frappe.get_all(
        "Cashflows Terminal",
        filters={"is_active": 1},
        fields=["name", "terminal_id", "label", "terminal_ip", "merchant_id"],
        order_by="terminal_id asc",
    )
    return rows
