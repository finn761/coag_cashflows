"""Live smoke test — drive a real £0.01 sale on each terminal via the wrapper.

Usage:
    PYTHONPATH=. python3 scripts/live_smoke_test.py
"""

from __future__ import annotations

import sys
import time
from typing import NamedTuple

from coag_cashflows.utils.cashflows_client import (
    CashflowsAPIError,
    CashflowsClient,
    CashflowsError,
    CashflowsUnreachable,
    TransactionResult,
)


class Terminal(NamedTuple):
    station: str
    ip: str


TERMINALS = [
    Terminal("STATION-1", "192.168.0.177"),
    Terminal("STATION-2", "192.168.0.244"),
]

USERNAME = "camden"
PASSWORD = "camden2026!"
AMOUNT_PENCE = 1
POLL_INTERVAL_SEC = 0.6
MAX_WAIT_SEC = 90


def run_sale(station: str, ip: str) -> TransactionResult | None:
    print(f"\n=== {station} @ {ip} ===")
    client = CashflowsClient(ip, USERNAME, PASSWORD)

    try:
        started = client.initiate_sale(AMOUNT_PENCE)
    except CashflowsUnreachable as e:
        print(f"  UNREACHABLE: {e}")
        return None
    except CashflowsAPIError as e:
        print(f"  API ERROR: {e}")
        return None
    except CashflowsError as e:
        print(f"  ERROR: {e}")
        return None

    print(f"  initiated: txn_id={started.txn_id} status={started.status}")
    print(f"  terminal should now show 'Insert, tap or swipe card' — go tap it (up to {MAX_WAIT_SEC}s)...")

    deadline = time.time() + MAX_WAIT_SEC
    last_status = started.status
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SEC)
        try:
            current = client.get_transaction(started.txn_id)
        except CashflowsError as e:
            print(f"  poll error: {e}")
            continue

        if current.status != last_status:
            print(f"  status -> {current.status}  (is_active={current.is_active})")
            last_status = current.status

        if not current.is_active:
            return current

    print("  TIMED OUT waiting for completion")
    return None


def summarise(t: TransactionResult | None) -> None:
    if t is None:
        print("  RESULT: no result (unreachable/timeout/error)")
        return
    print("  RESULT ----------")
    print(f"    txn_id:     {t.txn_id}")
    print(f"    status:     {t.status}")
    print(f"    result:     {t.result}")
    print(f"    auth_code:  {t.auth_code}")
    print(f"    amount:     {t.amount_pence}p")
    print(f"    card_brand: {t.card_brand}")
    print(f"    last_4:     {t.last_4}")
    print(f"    merchant:   {t.merchant_id}")


def main() -> int:
    for term in TERMINALS:
        result = run_sale(term.station, term.ip)
        summarise(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
