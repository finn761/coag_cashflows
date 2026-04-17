"""HTTP client wrapper around the Cashflows IPP REST API.

Single source of truth for all terminal I/O. All other modules in this app MUST
route terminal calls through this class so that error handling, timeouts, and
credential management stay in one place.

Spec reference: https://developer.cashflows.com/api_reference/ipp.html
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests


class CashflowsError(Exception):
    """Base class for all Cashflows client errors."""


class CashflowsUnreachable(CashflowsError):
    """Raised when the terminal cannot be reached (network / timeout)."""


class CashflowsAPIError(CashflowsError):
    """Raised when the terminal returns a non-success response."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class TransactionResult:
    """Canonical, UI-friendly shape of a Cashflows transaction state.

    Callers should treat this as the stable return type; the raw response shape
    from the IPP API can change between firmware versions.
    """

    txn_id: str
    status: str  # e.g. "starting" | "in_progress" | "approved" | "declined" | "cancelled"
    is_active: bool  # true while the txn is still on the terminal
    result: str | None  # "approved" | "declined" | "cancelled" | None while in-flight
    amount_pence: int
    auth_code: str | None = None
    card_brand: str | None = None
    last_4: str | None = None
    merchant_id: str | None = None
    reference_number: str | None = None
    status_details: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "TransactionResult":
        """Normalise an IPP `transaction` payload into our stable shape."""
        txn = payload.get("transaction", payload)

        online_request = txn.get("online_request") or {}
        account = txn.get("account_number") or ""
        last_4 = account[-4:] if account and account != "*****" else None

        # Card brand comes from the EMV tag 50 (application label) or the
        # response_text.display. We take whichever is most human-readable.
        card_brand = None
        tags = txn.get("tags") or {}
        tag_50 = tags.get("50")
        if tag_50:
            try:
                card_brand = bytes.fromhex(tag_50).decode("ascii", errors="ignore").strip()
            except ValueError:
                card_brand = None

        return cls(
            txn_id=txn.get("id", ""),
            status=txn.get("status", "unknown"),
            is_active=bool(txn.get("is_active", False)),
            result=txn.get("result"),
            amount_pence=int(txn.get("amount", 0)),
            auth_code=txn.get("auth_code"),
            card_brand=card_brand,
            last_4=last_4,
            merchant_id=str(online_request.get("merchant_number"))
            if online_request.get("merchant_number")
            else None,
            reference_number=txn.get("reference_number"),
            status_details=txn.get("status_details"),
            raw=txn,
        )


class CashflowsClient:
    """Client for a single Cashflows-connected SUNMI P3 terminal.

    Example
    -------
    >>> c = CashflowsClient("192.168.0.177", "camden", "camden2026!")
    >>> c.ping()
    True
    >>> txn = c.initiate_sale(amount_pence=100)
    >>> c.get_transaction(txn.txn_id)
    """

    # Sensible defaults; callers can override per instance.
    DEFAULT_CONNECT_TIMEOUT_SEC = 3
    DEFAULT_READ_TIMEOUT_SEC = 10

    def __init__(
        self,
        terminal_ip: str,
        username: str,
        password: str,
        port: int = 8080,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_SEC,
        read_timeout: float = DEFAULT_READ_TIMEOUT_SEC,
    ):
        if not terminal_ip:
            raise ValueError("terminal_ip is required")
        if not username or not password:
            raise ValueError("username and password are required")

        self.base_url = f"http://{terminal_ip}:{port}/api/v2"
        self._auth = (username, password)
        self._timeout = (connect_timeout, read_timeout)

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        auth_required: bool = True,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method,
                url,
                auth=self._auth if auth_required else None,
                json=json,
                headers={"Content-Type": "application/json"} if json is not None else None,
                timeout=self._timeout,
            )
        except requests.Timeout as e:
            raise CashflowsUnreachable(f"Timeout talking to {url}") from e
        except requests.ConnectionError as e:
            raise CashflowsUnreachable(f"Cannot reach {url}: {e}") from e
        except requests.RequestException as e:
            raise CashflowsError(f"HTTP error calling {url}: {e}") from e

        try:
            body = response.json()
        except ValueError as e:
            raise CashflowsAPIError(
                f"Non-JSON response from {url}", response.status_code, response.text
            ) from e

        if not response.ok or not body.get("success", False):
            raise CashflowsAPIError(
                f"{method} {url} failed: {body}",
                response.status_code,
                body,
            )

        return body

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def ping(self) -> bool:
        """Unauthenticated connectivity check. Returns True if terminal responds."""
        try:
            body = self._request("GET", "/ping.json", auth_required=False)
            return bool(body.get("ping"))
        except CashflowsError:
            return False

    def get_device(self) -> dict[str, Any]:
        """Returns device manufacturer, family, serial number."""
        body = self._request("GET", "/device.json")
        return body.get("device", {})

    def get_current_screen(self) -> dict[str, Any]:
        """Returns the current on-screen content of the terminal (read-only)."""
        body = self._request("GET", "/screens/current.json")
        return body.get("scene", {})

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------
    def initiate_sale(self, amount_pence: int) -> TransactionResult:
        """Start a sale on the terminal. Returns immediately with the new txn id.

        The terminal then displays the "Tap/Insert/Swipe" prompt and waits for
        the cardholder. Use `get_current_transaction()` to poll for progress.
        """
        if amount_pence < 1:
            raise ValueError("amount_pence must be >= 1")
        body = self._request(
            "POST", "/transactions/sale.json", json={"amount": int(amount_pence)}
        )
        return TransactionResult.from_api(body)

    def initiate_refund(self, amount_pence: int) -> TransactionResult:
        """Start a refund flow on the terminal."""
        if amount_pence < 1:
            raise ValueError("amount_pence must be >= 1")
        body = self._request(
            "POST", "/transactions/refund.json", json={"amount": int(amount_pence)}
        )
        return TransactionResult.from_api(body)

    def get_current_transaction(self) -> TransactionResult | None:
        """Return the in-flight transaction on the terminal, if any.

        Returns None if the terminal is idle (no active transaction).
        """
        try:
            body = self._request("GET", "/transactions/current.json")
        except CashflowsAPIError as e:
            # The IPP API returns a non-success body when there is no current
            # transaction; surface that as None rather than an exception.
            if e.status_code == 404 or (isinstance(e.body, dict) and e.body.get("transaction") is None):
                return None
            raise
        if not body.get("transaction"):
            return None
        return TransactionResult.from_api(body)

    def get_latest_transaction(self) -> TransactionResult | None:
        """Return the most recently completed transaction on the terminal."""
        body = self._request("GET", "/transactions/latest.json")
        if not body.get("transaction"):
            return None
        return TransactionResult.from_api(body)

    def get_transaction(self, txn_id: str) -> TransactionResult:
        """Return a specific transaction's current state by id."""
        if not txn_id:
            raise ValueError("txn_id is required")
        body = self._request("GET", f"/transactions/{txn_id}.json")
        return TransactionResult.from_api(body)
