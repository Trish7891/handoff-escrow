# Submitting Handoff to NEAR HACKATHON

Form: <https://nearhackathon.com/#apply> · API: `POST https://nearhackathon.com/api/applications`
Closes **14 Nov 2026 · 23:59 UTC** = **Sun 15 Nov · 01:59 SAST**.
One repository can be submitted once. A mistake is fixed by
<https://nearhackathon.com/request-changes>, never by submitting again.

## What only you can supply

1. **A contact email** (max 160 chars, at most 2 submissions per email).
2. **A NEAR mainnet account** for the payout — a named one like `trishan.near`,
   or a 64-character implicit account. If you have none: <https://wallet.near.org>
   → create account (Google/email sign-in, no card, no purchase) → copy the
   address. Prizes are paid there, so it must be one you control.
3. **The public X post** — see `docs/X_POST.md`. It must say the project was
   built at NEAR HACKATHON, tag `@NEARProtocol` and `#NEARHackathon`, and carry
   the screenshot (`docs/demo.png`, copied to your desktop as `handoff-demo.png`).

## The payload, as it will be sent

| Field | Value |
|---|---|
| `projectName` | `Handoff` |
| `leadName` | `Trishan Rajkumar` |
| `email` | *yours* |
| `size` | `1` |
| `tracks` | `["agents"]` (07 Agent Economy) |
| `nearAddress` | *yours* |
| `projectUrl` | `https://github.com/Trish7891/handoff-escrow` |
| `demoUrl` | the X post URL |
| `idea` | `docs/idea.txt` — 1,798 chars, limit 2,000 |
| `consent` | `true` |
| `website` | **left out deliberately** — any non-empty value rejects the submission |

`docs/idea.txt` covers the problem, the product, and how NEAR fits (per-job
escrow contract on `near-sdk 5`, terms the buyer cannot alter, payouts to NEAR
account ids, parity between the Rust and Python state machines).

## Send it

```bash
cd ~/projects/handoff-escrow
python3 tools/submit_near.py \
  --email you@example.com \
  --wallet you.near \
  --demo-url "https://x.com/totem1zn/status/XXXXXXXX"
```

That prints the exact JSON and validates every field locally, then stops.
Add `--confirm` to send. `201` means saved. `400` means a named field failed —
fix it and resend; the script reuses the same `requestId`, so a retry cannot
create a second submission. `409` means the repository or email was already
used — stop and ask for a change request instead.

Or do it in the browser: fill the form at `#apply` with the values above, leave
website empty, tick the consent box, submit.

## Tracks

`agents` is the intended fit and is what the script sends. The rules let a
project sit in every track it fits, and `swarms` describes "coordination
markets, bidding … settlement between agents", which is literally this loop. Add
it with `--tracks agents,swarms` if you want the second pool; it is one
submission either way.

## After

Results by **18 Nov 2026 · 23:59 UTC**. Prize payouts go to the `nearAddress`
in the payload.
