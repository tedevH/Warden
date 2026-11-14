# Lend

A FaceTime security guardian for people who can't safely navigate the internet on their own. They call Lend (a [Chert](https://www.trychert.com) FaceTime line), say what they want, and a Claude-driven browser does it. A security layer checks every page and action: it blocks look-alike logins, gift-card and wire scams, and instructions hidden in emails. Anything risky needs a spoken yes plus a physical button press.

Pitch: *Scammers target people who can't see the warning signs. Lend sees them for you.*

## Status

| # | Milestone | State |
| --- | --- | --- |
| 1 | Mock sites + seed + reset | **Done** |
| 2 | Browser worker on typed goals | **Done** |
| 3 | Orchestrator, safety gate, scam guard, injection tests | Next |
| 4 | Account audit | |
| 5 | Button bridge | |
| 6 | Caregiver dashboard | |
| 7 | Voice agent with mock harness | |
| 8 | Chert integration | |
| 9 | Outbound callback + iMessage | |
| 10 | Polish, DEMO.md | |

## Setup

```bash
make setup      # .venv (Python 3.12) + deps, creates .env from .env.example
make mocks      # all mock sites on :8100
make test
```

## Mock sites

One process, routed by hostname. Every `*.localhost` name resolves to this machine, so each site is a separate origin. It listens on loopback only.

| URL | What |
| --- | --- |
| http://localhost:8100 | Admin: links, **Inject fraud**, **Inject phishing**, **Reset** |
| http://maplebank.localhost:8100 | Maple Bank (legit): accounts, transactions, report, card freeze, transfer, new payee, security (sign-ins, sign out others, recovery email) |
| http://mail.localhost:8100 | Postbox Mail (legit): inbox, message view, forward, delete, sent |
| http://pizza.localhost:8100 | Slice Street Pizza (legit): menu, cart, checkout with saved test card, confirmation + ETA |
| http://secure-maplebankk-login.localhost:8100 | Scam: look-alike Maple Bank login → "enter the code we texted you" |
| http://paypa1-support.localhost:8100 | Scam: look-alike PayPal login (linked from the phishing email) |
| http://pc-security-alert.localhost:8100 | Scam: fake virus warning, countdown, "call 1-888-555-0199" |
| http://refund-center.localhost:8100 | Scam: "$349.99 refund", pay the fee in gift cards |

Seeded inbox: bank statement, a note from the grandson, a PG&E bill, a pharmacy notice, a **PayPal phish** from `paypa1-support.com` (the link text says paypal.com, but it goes to the look-alike), a **prompt-injection** email asking the AI to forward everything and delete itself, and a **gift-card refund** scam.

Demo endpoints (on `localhost:8100`):
- `POST /admin/inject_fraud`: adds $1 and $2 "test" charges, a $400 charge at a new merchant, a new-device sign-in, and a bank alert email
- `POST /admin/inject_phishing`: adds a Maple Bank look-alike "account locked" email
- `POST /admin/reset`: back to seed
- `GET /admin/state`: card frozen, sent mail, orders, transfers, what scam sites "captured" (field names only, never values)

Test credentials come from `.env` (`MOCK_BANK_*`, `MOCK_MAIL_*`). They are fake and only work on these mock sites.

## Browser worker

Claude runs locally through the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview), using your Claude Code login, so no API key is needed. Claude gets only the worker's browser tools (`goto`, `click`, `type`, `select`, `login`, `run_skill`, `done`, `need_user`, …). It has no shell, file or web tools, and none of your personal MCP servers or settings.

```bash
make worker GOAL="read my inbox"
.venv/bin/python -m worker.browser_worker "order me a large pepperoni" --yes      # auto-approve risky clicks
.venv/bin/python -m worker.browser_worker "show my last 10 transactions" --no-skills --headed
```

- **Observe:** a numbered list of interactive elements plus visible text (`worker/observe.py`), wrapped in `<untrusted_page_content>`. A page can't close that block early.
- **Login:** `login()` fills the saved login only on the exact origin it was saved for. Claude never sees the password, and the gate refuses to type into password fields.
- **Skills:** `read_inbox`, `bank_transactions`, `pizza_checkout`. They go through the same gated actions.
- **Gate:** for now a terminal y/N prompt for risky clicks (`ConsoleGate`). Milestone 3 replaces it with the orchestrator's policy and scam guard.
- `LEND_MODEL` (default `sonnet`), `MAX_STEPS` (30), `TASK_TIMEOUT_S` (300).

## Chert TODOs

None yet. Chert-specific code starts in milestone 7, inside `agent/chert_adapter.py`.

## Known limits

- The mock sites keep state in memory, so restarting `make mocks` resets them.
