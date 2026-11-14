# Warden

An AI security guardian you FaceTime. Built for the people scammers target most: older adults, and people who are blind or deaf and can't see or hear the warning signs.

You call Warden (a [Chert](https://www.trychert.com) FaceTime line) and say what you need: "check my email", "did anything strange happen at my bank?", "order me a pizza". It does it for you in a real browser, and a security layer checks every page and every action before anything reaches you. When Warden spots a fraudulent charge on its own, **it FaceTimes you**.

Pitch: *Scammers target people who can't see the warning signs. Warden sees them for you, and only for you.*

![Warden on a FaceTime call: a real-time human video avatar that speaks with Grok's voice](docs/warden-avatar.jpg)

*What you see when you FaceTime Warden: a live video avatar (Anam) speaking Grok's replies. This frame was captured from a call.*

See [USE_CASES.md](USE_CASES.md) for who it helps and the ten situations it handles, and [DEMO.md](DEMO.md) for the three-minute video script.

## What it does

- **Does the risky clicking for you.** Reads your inbox aloud, checks your bank, places an order, opens a link someone sent you, all by voice.
- **Blocks scams before they reach you.** Look-alike domains, fake login pages, "call this number" pop-ups, gift-card and wire requests, and instructions hidden in emails aimed at the AI.
- **Calls you when something is wrong.** An account watch runs on a timer. A new suspicious charge triggers a FaceTime Video call: "I found a $400 charge at a store you haven't used before. Did you make it?"
- **Only obeys its owner.** The caller's face and voice must both match the enrolled owner before any tool runs. Anyone else is refused and the family is alerted.
- **Can't spend on a spoken yes alone.** Money, sending and deleting need a spoken yes plus a press of the approve button, inside a spending limit.
- **Can't rewrite its own history.** Every action is fingerprinted and anchored on Solana; editing or deleting a log entry is detected.
- **Accessible by design.** Everything is spoken for people who can't see, and captioned on the call screen for people who can't hear.

## Built with

| Technology | What Warden uses it for |
| --- | --- |
| **[Chert](https://www.trychert.com)** | The FaceTime line. It gives Warden a real number, bridges each call's audio and video to the agent, and places Warden's outgoing calls. |
| **Grok (xAI)** | The voice you talk to (Grok Voice, speech to speech) and the planner that drives the browser (Grok 4.3). |
| **Solana** | The tamper-evident action log. Fingerprints of every action are anchored on devnet with the Memo program. |
| **LiveKit** | Agents framework and real-time rooms; LiveKit Inference serves the models. |
| **Anam** | The optional real-human video avatar on the call. |
| **Gemini (Google)** | Reading a letter or screen held up to the camera. |
| **OpenCV (YuNet, SFace) and WeSpeaker via sherpa-onnx** | Owner check: face and voice matching, run locally. |
| **Playwright, FastAPI, SQLite** | The browser worker, the orchestrator and dashboard, and storage. |

Built with Claude Code as the coding agent.

## How it fits together

```
          you call Warden                         Warden calls you
FaceTime ───────────────▶ Chert line ◀─────────────────────────────── account watch finds a bad charge
                              │
                              ▼
                        LiveKit room ◀─ agent/agent.py   Grok Voice · owner check (face + voice)
                                              │ HTTP       call screen or human avatar
                                              ▼
dashboard + approve button ◀──────────▶ orchestrator     tasks · safety gate · scam guard · vault
                                              │            account watch · action log ──▶ Solana
                                              ▼
                                   worker (Playwright browser, planned by Grok) ─▶ websites
```

- **Voice and browsing both use Grok** through LiveKit Inference, so the model keys are your LiveKit project's. The default voice is Grok Voice speech-to-speech (`LEND_VOICE_MODE=pipeline` switches to speech-to-text → Grok → text-to-speech). Reading a letter on camera uses `google/gemini-3.8-flash` through the same gateway. `LEND_PLANNER=claude` switches browsing to a local Claude Code login.
- **The safety rules are plain code**, not model behaviour. `make redteam` proves it with scripted attackers and no AI at all.
- **Everything runs against mock sites**: a bank, a mailbox, a pizza shop and four scam sites. Warden never touches real money.

## Setup

```bash
make setup        # .venv, deps, Chromium, .env, encrypted vault with the mock-site test logins
make models       # face and voice matching models for the owner check (about 65 MB, run locally)
make solana       # optional: devnet wallet so the action log is anchored on Solana
make test         # 64 tests
make redteam      # 14 attack scenarios, no keys needed
```

For anything that talks (the harness or a real call), put your LiveKit Cloud project's values in `.env.local`:

```
LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
AGENT_NAME=<a name no other team uses>
```

Optional extras, all in `.env` or `.env.local` (see `.env.example`):

- **Warden calls you:** `CHERT_API_KEY`, `CHERT_PROJECT_ID`, `CHERT_LINE_ID`, `USER_PHONE` (a number verified on your Chert project) and `AUDIT_INTERVAL_S=45`.
- **Human avatar:** `ANAM_API_KEY` and `ANAM_AVATAR_ID` (anam.ai free plan: 30 minutes a month, 3 minutes per call).
- **Solana:** after `make solana`, fund the printed wallet with free test SOL at https://faucet.solana.com.

## Run

| Command | What it runs |
| --- | --- |
| `make demo` | Mock sites + orchestrator + dashboard + approve-button page + text harness. No Chert needed. |
| `make mocks` | Mock bank, mail, pizza and four scam sites on :8100 (admin and **Inject fraud** at http://localhost:8100) |
| `make orchestrator` | Task API, safety gate, dashboard at http://127.0.0.1:8200, approve button at `/button` |
| `make agent` + `make chert` | The real FaceTime line (also needs `make mocks` and `make orchestrator`) |
| `make enroll` | Makes the next FaceTime Video call an enrollment call: Warden learns the caller as its owner |
| `make harness` | Talk to Warden by typing. Same tools as the call. `--no-llm` for keyword mode. |
| `make redteam` | Scam scorecard (used by the Grok Bot automation, see `GROK_BOT.md`) |
| `make worker GOAL="read my inbox"` | One goal straight through the worker, without the orchestrator |
| `python scripts/fake_caller.py` | Self-test without Chert: a simulated caller checks audio both ways. `--outbound` simulates a call Warden places; `--face photo.jpg --voice b` puts a face on camera and uses a second voice, to test the owner check. |

## Safety model

**Tiers** (`orchestrator/policy.py`), decided before every browser action:

| Tier | Actions | Needs |
| --- | --- | --- |
| 0 | read, navigate, type a draft | nothing |
| 1 | reversible changes (add to cart) | the caller's spoken request on the call |
| 2 | money, send, delete, card freeze, sign out devices | spoken yes **and** approve-button press (or caregiver approval) within 60 s, under the spending limit; caregiver notified |
| 3 | typing passwords, codes, card or account numbers; changing recovery info; new payees; gift cards, wires, crypto | never |

Sites outside the safe list open **look-only**: the guard inspects them, and nothing can be clicked or typed.

**Scam guard** (`orchestrator/guard.py`) runs on every page load before the model sees the page: look-alike and homoglyph domains, punycode, brand/host mismatch, login forms on origins with no saved login, fake-support phone numbers, gift card / crypto / wire requests, requests for codes or passwords, urgency, link text that doesn't match its address, and text aimed at AI assistants. A dangerous page ends the task, is closed, and the caregiver is told. Warden only opens an address the caller said themselves; a link inside an email is followed from that email, never guessed.

**Owner check** (`agent/verify.py`): on a FaceTime Video call the caller's face (OpenCV YuNet + SFace) and voice (WeSpeaker speaker embedding) are compared with the enrolled owner about once a second, on this computer. Until both match, every tool except "stop" is refused in code, and a mismatch alerts the caregiver. Handing the phone to someone else re-locks it within seconds. Only numeric embeddings are stored (`data/owner/`), never photos or recordings. On calls Warden places to the owner's own verified number, the voice alone is checked. It matches identity, not liveness: a good photo passes the face half, so the voice and the approval rules still have to hold. `LEND_VERIFY=off` disables it.

**Credentials** live in an encrypted vault (`data/vault.enc`, key in `.env`). A login is filled by Playwright only on the exact origin it was saved for. The model never sees it, and the gate blocks typing into password fields.

**Untrusted content**: page and email text reaches the model only inside `<untrusted_page_content>` blocks. Even a fully compromised planner can't forward or delete mail, because those actions need the person's approval (tested).

**Approve button**: a big on-screen button at `/button` (keyboard: Space or Enter). After it is pressed, Warden reports the result on the call without being asked.

**Account watch and outgoing calls** (`orchestrator/audit.py`): with `AUDIT_INTERVAL_S` set, Warden reads bank transactions, sign-ins and the inbox on a timer and flags small test charges followed by a large one, new merchants, amounts far above the usual (median/MAD), duplicates, new-device sign-ins, security notices and phishing emails. A new suspicious charge makes Warden FaceTime the owner and open with what it found; wording is always "looks unusual, did you make this?". It doesn't call while a call is already in progress, or twice about the same finding. Scam emails go on the dashboard report instead of a phone call.

**Lockdown**: `POST /lockdown` stops every task and refuses everything except looking for 30 minutes. The dashboard shows a red banner, and only the caregiver can clear it there.

**Tamper-evident log on Solana** (`orchestrator/chain.py`): an AI that touches your money should not be able to rewrite its own history. Every action-log entry is fingerprinted into a hash chain, and every few seconds the newest fingerprint is written to Solana (devnet) in a Memo transaction, so one transaction of 0.000005 SOL commits to the whole log so far. The dashboard links each entry to its transaction, and **Verify log** recomputes the chain and compares it with Solana; a changed or deleted entry is reported by number. Only fingerprints go on chain, never emails, amounts or names. If Solana is unreachable Warden keeps working and entries show as pending.

## The call screen

By default the caller sees the human avatar shown at the top (it needs Anam keys). Without them, or with `LEND_AVATAR=off`, `agent/face.py` draws the call screen below: a glowing orb with the Warden shield, a live waveform, a status line, a security chip (Protected / Checking it's you / Owner verified / Not the owner / Scam blocked) and a large caption of what Warden is saying. The chips and captions exist only on this drawn screen, which makes it the better choice for deaf and hard-of-hearing callers.

![The drawn call screen: listening, working, scam blocked, not the owner](docs/warden-face-preview.png)

## Environment

See `.env.example`. `.env`, `.env.local`, `data/` and `models/` are gitignored. Mock-site logins are fake and work nowhere else.

| Variable | Meaning |
| --- | --- |
| `LEND_VOICE_MODE` | `grok-voice` (default, speech to speech) or `pipeline` |
| `LEND_PLANNER` | `grok` (default) or `claude` |
| `LEND_GROK_MODEL`, `LEND_VOICE_LLM`, `LEND_VISION_MODEL` | model IDs on LiveKit Inference |
| `LEND_VERIFY` | `both` (default: face and voice) or `off` |
| `LEND_FACE_MIN`, `LEND_VOICE_MIN` | pass marks for the owner check (defaults 0.40 and 0.62) |
| `ANAM_API_KEY`, `ANAM_AVATAR_ID`, `LEND_AVATAR` | human avatar; `LEND_AVATAR=off` to use the drawn call screen |
| `CHERT_API_KEY`, `CHERT_PROJECT_ID`, `CHERT_LINE_ID` | outgoing calls and iMessage; with no key, they are only printed |
| `USER_PHONE`, `CAREGIVER_PHONE` | numbers verified on your Chert project |
| `AUDIT_INTERVAL_S` | seconds between automatic account checks (0 = off) |
| `LEND_OUTBOUND_VIDEO` | `1` (default) for FaceTime Video on outgoing calls, `0` for Audio |
| `SOLANA_RPC`, `LEND_CHAIN` | Solana cluster (devnet by default); `LEND_CHAIN=off` disables anchoring |

## What is verified, and what isn't

**Verified on a real FaceTime line**

- Calling Warden and talking to it, audio both ways, with the human avatar.
- Warden placing a FaceTime Video call on its own about 50 seconds after a fraudulent charge was injected, speaking the alert and hearing the reply.
- The action log being anchored on Solana devnet and verified against it; a secretly edited entry being reported.

**Verified in simulation or tests, not yet on a live call**

- The owner check: enrollment, the owner returning with a different photo, a stranger refused, and the owner's photo with a different voice refused, using a simulated caller with a photo as its camera and synthetic voices. Face matching was also checked on public-domain portraits (same person 0.82, different people 0.14 to 0.31).
- Every demo conversation (email, scam links, ordering with a choice, bank fraud, card freeze) through the text harness, which uses the same model and tools as the call.
- Safety tiers, scam guard, approvals, lockdown and the log chain: 64 tests, including the 14 red-team scenarios.

**Not verified**

- The owner check with a real person's face and voice over FaceTime; pass marks may need tuning.
- Reading a letter held up to the caller's camera on a live call.
- Live iMessage (caregiver alerts, enlarged screenshots); these run in mock mode.

## Known limits

- Chert trial calls are capped at 5 minutes and the free avatar plan at 3 minutes per call. Tasks keep running in the orchestrator after a call ends.
- The laptop must stay on: the agent, orchestrator and browser run on it.
- The approve button is a page on that laptop, so approving a payment during a call Warden placed means being near it.
- Browser agents are slow and sometimes wrong. Scripted skills cover the demo paths; step and time limits stop runaways.
- Real banks block automated browsers and need 2FA. Warden is demoed on mock sites and never touches real money.
- The owner check has no liveness detection, and a non-speaking user can't give voice commands yet.
- Fraud scoring and look-alike detection have false positives (for example, a new shop you really used, or a domain that happens to contain a brand name).
- The dashboard has no login. It listens on this computer only.
