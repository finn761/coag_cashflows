"""Stress test the coag_cashflows whitelisted API end-to-end.

Exercises every documented code path against the live ERPNext API and the two
live SUNMI P3 terminals. Scenarios that require a physical tap prompt you.

Usage:
    PYTHONPATH=. python3 scripts/stress_test.py

Scenarios (menu-driven):
    1. Health — ping both terminals + list_terminals (free, no tap)
    2. Sequential sale on STATION-1 (tap once, £0.01)
    3. Sequential sale on STATION-2 (tap once, £0.01)
    4. Parallel sales on both terminals (tap both, £0.02 total)
    5. Cancel via API mid-flow on STATION-1 (no tap, no charge)
    6. Rapid back-to-back (3 sales on STATION-1 in sequence, 3 taps, £0.03)
    7. Decline path — requires a low-balance card to test; skip if unsure.
    0. Run all tap-free scenarios (1 + 5)
"""

from __future__ import annotations

import concurrent.futures
import json
import sys
import time
import urllib.parse
import urllib.request

TOKEN = "e184eb972996ecd:24bf763876520c9"
BASE = "http://192.168.0.50:9080/api/method/coag_cashflows.api.payments"


def call(method: str, params: dict) -> dict:
    """Call a whitelisted endpoint and return the unwrapped `message` payload."""
    req = urllib.request.Request(
        f"{BASE}.{method}",
        data=urllib.parse.urlencode(params).encode(),
        headers={"Authorization": f"token {TOKEN}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["message"]


def poll(terminal_id: str, txn_id: str, max_sec: float = 150) -> dict | None:
    """Poll until !is_active or timeout. Returns the final state or None."""
    last = None
    t0 = time.time()
    while time.time() - t0 < max_sec:
        time.sleep(0.6)
        m = call("check_payment_status", {"terminal_id": terminal_id, "txn_id": txn_id})
        if m["status"] != last:
            print(f"    [{terminal_id}] -> {m['status']} (active={m['is_active']})")
            last = m["status"]
        if not m["is_active"]:
            return m
    return None


def run_sale(terminal_id: str, amount_pence: int = 1) -> dict | None:
    """Start a sale, prompt the user to tap, poll to completion."""
    print(f"\n--- {terminal_id}: initiating £{amount_pence / 100:.2f} ---")
    started = call("initiate_payment", {"terminal_id": terminal_id, "amount_pence": amount_pence})
    print(f"    txn_id={started['txn_id']}  status={started['status']}")
    print(f"    >>> TAP {terminal_id} NOW <<<")
    return poll(terminal_id, started["txn_id"])


def summarise(label: str, result: dict | None) -> None:
    if result is None:
        print(f"  [{label}] TIMEOUT or error")
        return
    if result.get("result") == "approved":
        print(
            f"  [{label}] APPROVED  auth={result.get('auth_code')}  "
            f"card={result.get('card_brand')} ...{result.get('last_4')}  "
            f"mid={result.get('merchant_id')}"
        )
    else:
        print(f"  [{label}] {result.get('result') or result.get('status')} — {result.get('status_details')}")


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def scenario_health() -> None:
    print("\n=== 1. Health ===")
    for tid in ("STATION-1", "STATION-2"):
        r = call("ping_terminal", {"terminal_id": tid})
        print(f"  {tid}: ok={r['ok']}  serial={r.get('serial_number')}  model={r.get('model')}")
    t = call("list_terminals", {})
    print(f"  list_terminals: {len(t)} terminal(s)")
    for row in t:
        print(f"    - {row['terminal_id']} @ {row['terminal_ip']}  mid={row.get('merchant_id')}")


def scenario_sequential(terminal_id: str) -> None:
    print(f"\n=== {terminal_id} sequential ===")
    summarise(terminal_id, run_sale(terminal_id))


def scenario_parallel() -> None:
    print("\n=== Parallel sales (tap both) ===")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(run_sale, "STATION-1")
        f2 = ex.submit(run_sale, "STATION-2")
        r1, r2 = f1.result(), f2.result()
    print()
    summarise("STATION-1", r1)
    summarise("STATION-2", r2)


def scenario_cancel() -> None:
    print("\n=== Cancel via API ===")
    started = call("initiate_payment", {"terminal_id": "STATION-1", "amount_pence": 1})
    print(f"  initiated: {started['txn_id']}")
    print("  waiting 3s then letting it time out on the Cashflows side (not tapping)...")
    time.sleep(3)
    # Poll once to confirm it's active
    m = call("check_payment_status", {"terminal_id": "STATION-1", "txn_id": started["txn_id"]})
    print(f"  after 3s: status={m['status']} active={m['is_active']}")
    print("  NOTE: the IPP API has no documented cancel endpoint — cashier must press red X on the terminal, or let it time out.")
    print("  Please press the red X on STATION-1 now, or wait ~2.5min for timeout.")
    final = poll("STATION-1", started["txn_id"], max_sec=180)
    summarise("STATION-1 cancel", final)


def scenario_rapid(n: int = 3) -> None:
    print(f"\n=== {n} rapid sequential sales on STATION-1 ===")
    results = []
    for i in range(n):
        print(f"\n  -- Sale {i + 1} of {n} --")
        r = run_sale("STATION-1")
        results.append(r)
        summarise(f"sale {i + 1}", r)
    approved = sum(1 for r in results if r and r.get("result") == "approved")
    print(f"\n  Summary: {approved}/{n} approved")


SCENARIOS = {
    "1": ("Health (no tap)", scenario_health),
    "2": ("Sequential STATION-1 (1 tap, £0.01)", lambda: scenario_sequential("STATION-1")),
    "3": ("Sequential STATION-2 (1 tap, £0.01)", lambda: scenario_sequential("STATION-2")),
    "4": ("Parallel both terminals (2 taps, £0.02)", scenario_parallel),
    "5": ("Cancel via API / red X (no charge)", scenario_cancel),
    "6": ("Rapid 3× on STATION-1 (3 taps, £0.03)", lambda: scenario_rapid(3)),
    "0": ("All tap-free (health + cancel)", lambda: (scenario_health(), scenario_cancel())),
}


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Cashflows API stress test")
        print("=" * 50)
        for key, (label, _) in SCENARIOS.items():
            print(f"  {key}. {label}")
        choice = input("\nChoose scenario (or comma-separated list): ").strip()
        args = [c.strip() for c in choice.split(",") if c.strip()]

    for arg in args:
        if arg in SCENARIOS:
            _, fn = SCENARIOS[arg]
            fn()
        else:
            print(f"Unknown scenario: {arg}")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
