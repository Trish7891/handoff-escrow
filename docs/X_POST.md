# Demo post for X

Three things only you can do: post from **@totem1zn**, give me a **NEAR wallet
address**, then paste both links into the form. Everything below is ready to copy.

The image to attach is `docs/demo.png` in this repo — also copied to your Windows
desktop as `handoff-demo.png`.

## Post 1 — the one required post (274 characters)

```
Every agent marketplace stalls at the same point: who pays whom, and when?

Handoff: buyer escrows, worker delivers an artifact + its hash, a machine checks the work, then money moves.

Built at NEAR HACKATHON @NEARProtocol #NEARHackathon
github.com/Trish7891/handoff-escrow
```

Attach `handoff-demo.png`. That satisfies "a demo video or screenshots" — the
rules do not require video.

## Replies, if you want the detail (optional, but they read well)

**2/4**

```
Three jobs, one ledger, three endings:
· clean: 5/5 checks → released, 99.5% to the worker, 0.5% fee
· bad: the invoice math is wrong → refunded, worker paid nothing
· dispute: summary padded past the limit → 4/5 → arbiter splits 80/20

The failure is printed, not swallowed.
```

**3/4**

```
The buyer's log can't be quietly rewritten. Each entry commits to the previous
one, and the worker publishes the hash of its delivery at submit time.

Edit a past amount and verification stops at entry 15:

python3 -m handoff tamper
```

**4/4**

```
38 Python tests, 7 contract tests, and one test that parses the Rust source and
fails if the on-chain transition table drifts from the Python one.

python3 -m handoff demo · verify · tamper

No dependencies outside the standard library.
```

## If you would rather record a video

`demo` prints the three-scenario table, then `verify` prints the passing head,
then `tamper` prints the broken entry. Screen-record those three commands and
nothing else — under a minute, no narration needed. Only do this if it is quick:
screenshots already meet the requirement.
