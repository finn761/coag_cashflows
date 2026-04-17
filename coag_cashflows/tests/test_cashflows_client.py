"""Unit tests for the Cashflows HTTP client wrapper.

These tests do not touch a real terminal — they mock the `requests` module.
Run with: ``bench --site coag.local run-tests --app coag_cashflows``
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from coag_cashflows.utils.cashflows_client import (
    CashflowsAPIError,
    CashflowsClient,
    CashflowsError,
    CashflowsUnreachable,
    TransactionResult,
)


def _mock_response(status_code: int = 200, json_body: dict | None = None):
    r = MagicMock()
    r.ok = 200 <= status_code < 300
    r.status_code = status_code
    r.json.return_value = json_body or {"success": True}
    r.text = str(json_body)
    return r


class TestTransactionResultFromApi(unittest.TestCase):
    def test_normalises_approved_txn(self):
        api_body = {
            "transaction": {
                "id": "abc-123",
                "status": "approved",
                "is_active": False,
                "result": "approved",
                "amount": 405,
                "auth_code": "AJAVBD",
                "account_number": "5***********7039",
                "reference_number": "R1",
                "status_details": "ok",
                "tags": {"50": "4445424954204D415354455243415244"},
                "online_request": {"merchant_number": "5963863", "terminal_id": "37657587"},
            }
        }
        t = TransactionResult.from_api(api_body)
        self.assertEqual(t.txn_id, "abc-123")
        self.assertEqual(t.status, "approved")
        self.assertFalse(t.is_active)
        self.assertEqual(t.auth_code, "AJAVBD")
        self.assertEqual(t.amount_pence, 405)
        self.assertEqual(t.last_4, "7039")
        self.assertEqual(t.merchant_id, "5963863")
        self.assertIn("MASTERCARD", (t.card_brand or "").upper())

    def test_handles_no_card_data(self):
        t = TransactionResult.from_api(
            {"transaction": {"id": "x", "status": "starting", "amount": 1, "account_number": "*****"}}
        )
        self.assertIsNone(t.last_4)
        self.assertIsNone(t.merchant_id)


class TestCashflowsClient(unittest.TestCase):
    def setUp(self):
        self.client = CashflowsClient("1.2.3.4", "user", "pass")

    def test_constructor_rejects_missing_ip(self):
        with self.assertRaises(ValueError):
            CashflowsClient("", "u", "p")

    def test_constructor_rejects_missing_creds(self):
        with self.assertRaises(ValueError):
            CashflowsClient("1.2.3.4", "", "p")
        with self.assertRaises(ValueError):
            CashflowsClient("1.2.3.4", "u", "")

    @patch("coag_cashflows.utils.cashflows_client.requests.request")
    def test_ping_returns_true_on_success(self, req):
        req.return_value = _mock_response(200, {"success": True, "ping": True})
        self.assertTrue(self.client.ping())

    @patch("coag_cashflows.utils.cashflows_client.requests.request")
    def test_ping_returns_false_on_connection_error(self, req):
        req.side_effect = requests.ConnectionError("boom")
        self.assertFalse(self.client.ping())

    @patch("coag_cashflows.utils.cashflows_client.requests.request")
    def test_initiate_sale_rejects_zero_amount(self, _req):
        with self.assertRaises(ValueError):
            self.client.initiate_sale(0)

    @patch("coag_cashflows.utils.cashflows_client.requests.request")
    def test_initiate_sale_returns_txn(self, req):
        req.return_value = _mock_response(
            200,
            {
                "success": True,
                "transaction": {
                    "id": "t1",
                    "status": "starting",
                    "is_active": True,
                    "amount": 100,
                },
            },
        )
        result = self.client.initiate_sale(100)
        self.assertEqual(result.txn_id, "t1")
        self.assertEqual(result.status, "starting")
        self.assertTrue(result.is_active)

    @patch("coag_cashflows.utils.cashflows_client.requests.request")
    def test_unreachable_on_timeout(self, req):
        req.side_effect = requests.Timeout("slow")
        with self.assertRaises(CashflowsUnreachable):
            self.client.get_device()

    @patch("coag_cashflows.utils.cashflows_client.requests.request")
    def test_api_error_on_non_success_body(self, req):
        req.return_value = _mock_response(
            200, {"success": False, "error": "bad"}
        )
        with self.assertRaises(CashflowsAPIError):
            self.client.get_device()


if __name__ == "__main__":
    unittest.main()
