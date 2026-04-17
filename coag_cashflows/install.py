"""Installation hooks.

Called by Frappe on ``bench install-app coag_cashflows`` (after_install) and on
``bench migrate`` (after_migrate). Both hooks are idempotent — they create
custom fields and default records only if they do not already exist.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


# -------- custom fields --------


# POS Profile gets the link to which terminal this station uses.
POS_PROFILE_FIELDS = [
    {
        "fieldname": "custom_cashflows_section",
        "label": "Cashflows",
        "fieldtype": "Section Break",
        "insert_after": "write_off_cost_center",
        "collapsible": 1,
    },
    {
        "fieldname": "custom_cashflows_terminal",
        "label": "Cashflows Terminal",
        "fieldtype": "Link",
        "options": "Cashflows Terminal",
        "insert_after": "custom_cashflows_section",
        "description": (
            "The terminal this station pays through. Each station (iPad) must bind "
            "to a specific terminal — do not share one terminal across stations."
        ),
    },
]


# POS Invoice gets read-only stamps for audit / reconciliation.
POS_INVOICE_FIELDS = [
    {
        "fieldname": "custom_cashflows_section",
        "label": "Cashflows",
        "fieldtype": "Section Break",
        "insert_after": "amended_from",
        "collapsible": 1,
    },
    {
        "fieldname": "custom_cashflows_terminal",
        "label": "Cashflows Terminal",
        "fieldtype": "Link",
        "options": "Cashflows Terminal",
        "insert_after": "custom_cashflows_section",
        "read_only": 1,
    },
    {
        "fieldname": "custom_cashflows_txn_id",
        "label": "Cashflows Transaction ID",
        "fieldtype": "Data",
        "insert_after": "custom_cashflows_terminal",
        "read_only": 1,
    },
    {
        "fieldname": "custom_cashflows_auth_code",
        "label": "Auth Code",
        "fieldtype": "Data",
        "insert_after": "custom_cashflows_txn_id",
        "read_only": 1,
    },
    {
        "fieldname": "custom_cashflows_col_break",
        "fieldtype": "Column Break",
        "insert_after": "custom_cashflows_auth_code",
    },
    {
        "fieldname": "custom_cashflows_card_brand",
        "label": "Card Brand",
        "fieldtype": "Data",
        "insert_after": "custom_cashflows_col_break",
        "read_only": 1,
    },
    {
        "fieldname": "custom_cashflows_last_4",
        "label": "Last 4",
        "fieldtype": "Data",
        "insert_after": "custom_cashflows_card_brand",
        "read_only": 1,
    },
    {
        "fieldname": "custom_cashflows_merchant_id",
        "label": "Merchant ID",
        "fieldtype": "Data",
        "insert_after": "custom_cashflows_last_4",
        "read_only": 1,
    },
]


CUSTOM_FIELDS = {
    "POS Profile": POS_PROFILE_FIELDS,
    "POS Invoice": POS_INVOICE_FIELDS,
}


def _create_custom_fields() -> None:
    create_custom_fields(CUSTOM_FIELDS, ignore_validate=True, update=True)


# -------- hooks --------


def after_install() -> None:
    """Called once when the app is first installed on a site."""
    _create_custom_fields()
    frappe.db.commit()


def after_migrate() -> None:
    """Called on every `bench migrate` — keep custom fields in sync with code."""
    _create_custom_fields()
