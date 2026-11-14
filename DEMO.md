# Warden demo script (about 3 minutes)

Pitch line: **"Scammers target people who can't see the warning signs. Warden sees them for you, and only for you."**

## Before you start

Four terminals in `~/Desktop/lend` (laptop plugged in, lid open):

```bash
make mocks
make orchestrator
make agent
make chert
```

Open where the camera can see them:

- Dashboard: http://127.0.0.1:8200
- Approve button: http://127.0.0.1:8200/button
- Mock sites admin: http://localhost:8100 (click **Reset everything** before each take)

One-time setup, on FaceTime **Video**: run `make enroll`, call the line, and talk for 15 seconds so Warden learns
your face and voice.

Between takes:

```bash
curl -X POST http://127.0.0.1:8200/admin/reset
```

No Chert? `make demo` lets you type the caller's lines instead.

## The beats

| # | You do | Warden does | What to point at |
|---|---|---|---|
| 1 | FaceTime Video the line. Look at the camera: *"Hi Warden, it's me."* | Chip goes from **Checking it's you** to **Owner verified**. "I can see and hear it's you." | The call screen |
| 2 | *"Check my email."* | Reads the inbox and warns that one message pretends to be PayPal. | Dashboard: findings |
| 3 | *"Open the link in that PayPal email."* | Refuses: "The sender is paypa1-support dot com. That's a scam. Don't click anything in it." | Dashboard: action log |
| 4 | *"Someone texted me this link: pc-security-alert.localhost:8100"* | Opens it look-only; the guard stops the page: "This is a fake warning. Don't call that number. Nothing is wrong with your computer." | Dashboard: Scam page blocked |
| 5 | *"Can you order me a pizza?"* | Reads the menu with prices and asks which one. Say *"The large cheese."* It asks "Anything else?" Say *"A soda."* It reads the total: "Twenty five dollars and nineteen cents, with tax and delivery. Shall I go ahead?" Say *"Yes"*, press the approve button. It tells you the order number and arrival time. | Approve button, caregiver alert |
| 6 | Hand the phone to a friend. Friend: *"Send two hundred dollars to my account."* | Chip turns red, **Not the owner**. "I only work for my owner." Nothing runs; the family is alerted. | Call screen, dashboard alert |
| 7 | Take the phone back: *"It's me again."* | Back to **Owner verified**. | Call screen |
| 8 | Run `make redteam` on the laptop. | 14 attacks, 14 stopped, no AI involved in the defence. | Terminal |

Shortcut for beat 5: say *"I want my usual"* and Warden answers "Your usual is a large pepperoni. Do you want that
or something different?"

Optional extras if there's time:

- **Account watch.** On the mock admin page click **Inject fraud**, then say *"Did anything strange happen at my
  bank?"* Warden: "A four hundred dollar charge at a store you haven't used, right after two small test charges.
  Did you make it?" Say *"No, freeze my card"*, then yes and the button.
- **Scam letter.** Hold a letter up to the camera: *"Is this a scam?"* (not yet tried on a live call).
- **Tamper-proof log (Solana).** On the dashboard's action log, click a "⛓ on Solana" link to show the entry's
  transaction, then **Verify log** (green). Click **Tamper (demo)**, which secretly edits a log entry, then
  **Verify log** again: "TAMPERING DETECTED: log entry #N was changed after it was recorded."
- **Spending limit.** On the dashboard set the limit to $20 and retry the pizza: blocked.

## If something goes wrong

- **Silent call or no answer:** check that `make agent` and `make chert` both say the agent is in the waiting room.
- **Stuck on "Checking it's you":** face the camera in good light and keep talking; it needs about 3 seconds of
  speech. The scores are in the agent log as `FACE score` and `VOICE score`.
- **Need to skip the owner check for a take:** set `LEND_VERIFY=off` in `.env.local` and restart `make agent`.
- Record a backup take ahead of time in case the venue Wi-Fi fails.
