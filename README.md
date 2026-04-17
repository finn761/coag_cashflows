# coag_cashflows

Cashflows IPP payment integration for ERPNext POS Next.

A proper Frappe app (not a patch) — version-controlled, unit-tested, rebuilt into the ERPNext Docker image like `erpnext`, `crm`, and the `pos_next` fork.

## What it does

- Exposes a whitelisted REST API the POS Next frontend can call to take card payments through a Cashflows-connected SUNMI P3 terminal.
- Models each physical terminal as a `Cashflows Terminal` doctype (one record per SUNMI). Credentials + timeouts live in a single `Cashflows Settings` doctype.
- Stamps every POS Invoice with the Cashflows transaction id, auth code, card brand, last 4, and merchant id for downstream reconciliation.
- Safe for multiple concurrent stations: every API call is parameterised by `terminal_id`; no global state.

## Architecture

```
POS Next (Vue, in the browser on the iPad)
    │   frappe.call('coag_cashflows.api.payments.initiate_payment', {...})
    ▼
Frappe (backend, Python) — coag_cashflows.api.payments
    │   resolves terminal_id → Cashflows Terminal → IP + creds
    ▼
CashflowsClient (requests, typed wrapper)
    │   HTTP POST http://<terminal_ip>:8080/api/v2/transactions/sale.json
    ▼
SUNMI P3 terminal (Cashflows IPP firmware)
```

## Doctypes

| Doctype | Purpose |
|---|---|
| `Cashflows Settings` (single) | API credentials, default port, poll interval, timeouts. |
| `Cashflows Terminal` | One record per SUNMI P3. Holds IP, label, auto-populated serial + MID. |

## Custom fields (installed automatically)

### POS Profile
- `custom_cashflows_terminal` (Link → Cashflows Terminal)

### POS Invoice (all read-only, stamped on approval)
- `custom_cashflows_terminal`
- `custom_cashflows_txn_id`
- `custom_cashflows_auth_code`
- `custom_cashflows_card_brand`
- `custom_cashflows_last_4`
- `custom_cashflows_merchant_id`

## API

All endpoints are whitelisted and called via `frappe.call` from the browser. Every call is parameterised by `terminal_id` so two stations can hit two terminals concurrently.

### `coag_cashflows.api.payments.initiate_payment`
```
POST { terminal_id, amount_pence, pos_invoice? }
  -> { txn_id, status, is_active, amount_pence, ... }
```
Starts a sale. Returns immediately with the new transaction id. The terminal then displays the Cashflows "Tap/Insert/Swipe" prompt.

### `coag_cashflows.api.payments.check_payment_status`
```
POST { terminal_id, txn_id, pos_invoice? }
  -> { txn_id, status, is_active, result, auth_code, card_brand, last_4, merchant_id, ... }
```
Returns the current state of a transaction. The frontend polls this every `poll_interval_ms` (from Settings) until `is_active` is false.

On completion, the POS Invoice (if provided) is stamped with the result; the terminal record captures MID + TID the first time.

### `coag_cashflows.api.payments.ping_terminal`
```
POST { terminal_id } -> { ok, device, serial_number, model }
```
Health check. Updates `last_ping_ok`, `last_ping_at`, `last_ping_error` on the terminal record.

### `coag_cashflows.api.payments.list_terminals`
```
POST {} -> [{ terminal_id, label, terminal_ip, merchant_id }, ...]
```

## Installation (on Engine)

```bash
# 1. Add this app to the ERPNext build
# Edit /mnt/fast/erpnext/apps.json and add:
#   { "url": "https://github.com/finn761/coag_cashflows", "branch": "main" }

# 2. Rebuild the Docker image
cd /mnt/fast/erpnext
export APPS_JSON_BASE64=$(base64 -w 0 apps.json)
docker build \
  --build-arg=FRAPPE_BRANCH=version-15 \
  --build-arg=APPS_JSON_BASE64=$APPS_JSON_BASE64 \
  --build-arg=PYTHON_VERSION=3.11.6 \
  --build-arg=NODE_VERSION=20.19.2 \
  --tag=coag-erpnext:15-pos \
  --file=frappe_docker/images/custom/Containerfile \
  frappe_docker/
docker tag coag-erpnext:15-pos coag-erpnext:15

# 3. Bring up the new image
docker compose down && docker compose up -d

# 4. Install the app on the site
docker compose exec backend bench --site coag.local install-app coag_cashflows
```

## Post-install configuration

In the ERPNext UI:

1. **Cashflows Settings** → set `API Username` + `API Passcode` (from Cashflows support, NOT the terminal's on-screen API credentials).
2. **Cashflows Terminal** → create one record per SUNMI:
   - `BAR-1` → 192.168.0.177
   - `BAR-2` → 192.168.0.244
3. On each **POS Profile** (Coffee Menu / Bar Menu), set the default `Cashflows Terminal` — or leave blank if the iPad always picks its terminal from the URL.
4. Open a terminal record and click **Ping** to enrich it with the device serial. After the first real transaction, MID + TID will populate automatically.

## Running tests

```bash
# Unit tests (HTTP-level, mocked — no terminal needed)
docker compose exec backend bench --site coag.local run-tests --app coag_cashflows

# Or locally without Frappe:
cd coag_cashflows
PYTHONPATH=. python3 -m unittest coag_cashflows.tests.test_cashflows_client -v
```

## Extending

- Refunds: `CashflowsClient.initiate_refund()` is implemented; wrap it in a whitelisted API when needed.
- Transaction log doctype: add later for full audit + daily Xero journaling.
- Kiosk mode / receipt suppression: requires Cashflows firmware changes. Contact Greg Warner, implementations@cashflows.com.
