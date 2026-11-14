# Warden demo script

Pitch frame: **"Scammers target people who can't see the warning signs. Warden sees them for you."**

## Before you start

Four terminals in `~/Desktop/lend` (laptop plugged in, lid open):

```bash
make mocks
make orchestrator
make agent
make chert
```

Open three browser windows where the camera can see them:

- Dashboard: http://127.0.0.1:8200
- Approve button: http://127.0.0.1:8200/button
- Mock sites admin: http://localhost:8100 (click **Reset everything** before each take)

Reset Warden's own history between takes:

```bash
curl -X POST http://127.0.0.1:8200/admin/reset
```

No Chert? Run `make demo` and type the caller's lines instead of speaking them.

## The six beats

1. **Phishing stopped.** Call the line. Say: *"Check my email."*
   Warden reads the inbox and warns that one message claims to be PayPal but comes from "paypa1-support dot com".
   Say: *"Open it anyway."* Warden refuses to sign in or follow the link. If it does open the link, the guard stops the page and the dashboard shows "Scam page blocked".

2. **Prompt injection blocked.** Say: *"What's the one for my AI assistant?"*
   Warden reads it as content, says it's suspicious, and does nothing it asks. Show the dashboard action log: no forward, no delete.

3. **Account compromise caught.** Hang up. On the mock admin page click **Inject fraud**, then on the dashboard click **Run account check**.
   - With live callbacks set up: the phone rings. *"I found a $400 charge at a store you haven't used before, right after two small test charges. Did you make it?"*
   - Otherwise: call Warden and say *"Check my accounts."* It says the same thing.

   Say: *"No. Freeze my card."* Warden reads the approval. Say *"Yes"*, then press the approve button. The card freezes and the dashboard shows the caregiver alert.

4. **Tech-support scam.** Say: *"Someone texted me a link, open it: pc-security-alert.localhost:8100"* (or paste it into the dashboard's task box).
   Warden: *"This is a fake warning. Don't call that number. Nothing is wrong with your computer."*

5. **Normal life still works.** Say: *"Order me a large pepperoni."*
   Yes to the cart, yes to the $24 order, press the button. Warden reads the order number and arrival time.

6. **Scam letter (optional, FaceTime Video).** Hold the letter up. Say: *"Is this a scam?"*
   In mock mode Warden reads the sample letter in `tests/fixtures/`.

7. **Dashboard.** Scroll through findings, blocked actions, approvals. Change the spending limit to $20 and retry the pizza: blocked.

Close with the red team: run `make redteam` on screen. 12 attacks, 12 defended, no AI involved in the defence.

## Backup recording

Record takes ahead of time in case the venue Wi-Fi fails.

- **Phone:** Control Center → Screen Recording (long-press, turn the microphone on), then make the FaceTime call.
- **Laptop:** QuickTime Player → File → New Screen Recording, with the dashboard and the approve button visible.
- Record each beat as its own take. Reset both sites between takes.
- A keyboard-only version works too: `make demo` and type. Record the terminal next to the dashboard.
- Calls are capped at 5 minutes, so beats 1–2 and beats 3–5 work best as two separate calls.
