# Who Warden is for, and what it does for them

Americans over 60 reported **$4.9 billion** in losses to online fraud in 2024, up 43% in one year, across 147,000
complaints ([FBI IC3 2024 report](https://ic3.gov/AnnualReport/Reports/2024_IC3Report.pdf)). The FBI says the real
number is higher, because most victims never report it.

The usual advice is "be careful what you click". Warden takes the clicking away: you FaceTime it, it does the risky
part, and the rules that protect your money are in code that neither a scammer nor the AI can talk around.

## Ten situations Warden handles

| # | The situation | What Warden does | Works today |
|---|---|---|---|
| 1 | **"Your PayPal account is locked" email** | Reads the inbox aloud, names the fake sender, refuses to sign in on the look-alike page | Yes, on the mock mailbox |
| 2 | **A text with a link** ("your package is held") | Opens it in look-only mode, checks the page, and says plainly whether it's fake | Yes |
| 3 | **"Your computer has a virus, call this number" pop-up** | Stops the page: "This is a fake warning. Don't call that number." | Yes |
| 4 | **Gift-card or wire "refund" scam** | Gift cards, wires and crypto are blocked outright, whatever anyone says | Yes |
| 5 | **A web page or email tries to give the AI orders** (prompt injection) | Page text is treated as information only; forwarding or deleting mail needs the owner's yes and button | Yes |
| 6 | **Small "test" charges, then a big one** | Account watch spots the pattern and asks "did you make this?" | Yes, on the mock bank |
| 7 | **Someone else picks up the phone** (a visitor, a carer, a thief) | Face and voice don't match the owner, so every tool stays locked and the family is alerted | Built; needs the owner's enrollment call |
| 8 | **A scammer coaches "just say yes"** | A spoken yes alone can't move money: it also takes the approve button, inside a spending limit | Yes |
| 9 | **A paper letter or a text on another phone** | Hold it up to the FaceTime camera; Warden reads it and says if it's a scam | Built, not yet tried on a live call |
| 10 | **Ordinary errands** (order dinner, check a balance) | Does them, reads back the price, asks once | Yes |

## Who benefits most

- **Older adults living alone.** One number to call, no app to learn.
- **Blind and low-vision users.** They can't see the misspelled address bar; Warden checks it for them and reads
  everything aloud.
- **Hard-of-hearing users.** Everything Warden says is captioned on the call screen.
- **Families and caregivers.** A dashboard of every action, alerts for anything blocked, and the power to approve
  or deny from their own phone.

## Why it's hard to fool

- **The AI is the helper, not the guard.** Spending limits, approvals and the scam checks are ordinary code.
  No prompt can raise the limit or skip the button.
- **Passwords never reach the AI.** Logins are filled from an encrypted vault, only on the exact saved site.
- **Only the owner can use it.** Face and voice must both match before any tool runs, checked throughout the call.
- **It's tested like an attacker would.** `make redteam` runs 14 attacks against the real safety gate; all are stopped.

## Honest limits

- It runs on mock bank, mail and shop sites. Real accounts are the next step, read-only first.
- The owner check matches identity, not liveness: a good photo or a voice recording could fool it. It is one
  layer on top of the approval rules, not a replacement for them.
- Warden calling you first (instead of you calling it) is written but has not been proven on a live line.
