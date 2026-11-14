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

## The video script (about 3 minutes)

Film the phone standing next to the laptop so both are in shot. Your lines are in quotes; Warden's wording varies.

**1. What Warden is (0:00–0:25, to camera, phone in hand)**

> "This is Warden. It's an AI security guard you FaceTime. Instead of going online yourself, you call Warden and
> tell it what you need: check my email, look at my bank, order dinner. It does it for you in a real browser, and it
> checks every page and every message for scams before anything reaches you. It's built for the people scammers
> target most: older adults, and people who are blind or deaf and can't see or hear the warning signs."

**2. Why it matters (0:25–0:35)**

> "People over 60 lost 4.9 billion dollars to online scams last year. Scam warnings are visual and audible: a
> misspelled address, a red banner, a tone of voice. If you can't see or can't hear, you miss them."

**3. It knows its owner (0:35–0:50)** FaceTime Video the line. *"Hi Warden, it's me."* The chip goes from
**Checking it's you** to **Owner verified**.

**4. Can't see (0:50–1:35)** Turn the laptop away or close your eyes; do it all by voice.
- *"Check my email."* Warden reads the inbox and flags the PayPal message: the sender is "paypa1" with a number 1.
  To camera: "A screen reader would just say PayPal."
- *"Can you order me a pizza?"* Pick one by voice, say *"Yes"*, press the **space bar** to approve.
  To camera: "A scammer can coach someone into saying yes. They can't press that button."

**5. Can't hear (1:35–2:00)** Mute the phone on camera.
- *"Someone texted me this link: pc-security-alert.localhost:8100"*
- The call screen turns red, shows **Scam blocked**, and the caption reads the warning. To camera: "Sound off, and
  the warning still lands." (Needs the orb call screen, not the human avatar.)

**6. Can't be impersonated (2:00–2:20)** Hand the phone to a friend: *"Send two hundred dollars to my account."*
The chip turns red, **Not the owner**; Warden refuses and the dashboard shows the caregiver alert.

**7. Can't rewrite its history (2:20–2:45, laptop screen recording)** In the action log click a "⛓ on Solana"
link, then **Verify log** (green), **Tamper (demo)**, **Verify log** (red).

> "Every action is anchored on Solana, so nobody can edit the record, including the AI."

**8. Close (2:45–3:00)** Run `make redteam`: 14 attacks, 14 stopped.

> "Warden runs on a Chert FaceTime line, talks and browses with Grok from xAI, and anchors its log on Solana.
> It sees the warning signs for you, and only for you."

## The beats (quick reference)

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

Credits line to say at the end: *"Warden runs on a Chert FaceTime line, talks and browses with Grok from xAI, and
anchors its action log on Solana."* (Full list in the README under "Built with".)

Optional extras if there's time:

- **Account watch.** On the mock admin page click **Inject fraud**, then say *"Did anything strange happen at my
  bank?"* Warden: "A four hundred dollar charge at a store you haven't used, right after two small test charges.
  Did you make it?" Say *"No, freeze my card"*, then yes and the button.
- **Scam letter.** Hold a letter up to the camera: *"Is this a scam?"* (not yet tried on a live call).
- **Tamper-proof log (Solana).** On the dashboard's action log, click a "⛓ on Solana" link to show the entry's
  transaction, then **Verify log** (green). Click **Tamper (demo)**, which secretly edits a log entry, then
  **Verify log** again: "TAMPERING DETECTED: log entry #N was changed after it was recorded."
- **Warden calls you.** With `AUDIT_INTERVAL_S=45` and a Chert API key in `.env`, hang up, click **Inject fraud** on
  the mock admin page, and wait: within about a minute your phone rings. "Hi, it's Warden. I'm calling because I
  noticed something. I found a four hundred dollar charge at a store you haven't used before. Did you make it?"
  Say *"No, freeze my card"*, then yes and the button. Without a key, the call is printed in `data/chert_mock.log`.
- **Spending limit.** On the dashboard set the limit to $20 and retry the pizza: blocked.

## If something goes wrong

- **Silent call or no answer:** check that `make agent` and `make chert` both say the agent is in the waiting room.
- **Stuck on "Checking it's you":** face the camera in good light and keep talking; it needs about 3 seconds of
  speech. The scores are in the agent log as `FACE score` and `VOICE score`.
- **Need to skip the owner check for a take:** set `LEND_VERIFY=off` in `.env.local` and restart `make agent`.
- Record a backup take ahead of time in case the venue Wi-Fi fails.
