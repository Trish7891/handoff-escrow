# Trust model

Every system that moves money for work has to answer: *who can lie, and what does
it cost them?* This is Handoff's answer, written down so a buyer or a judge can
disagree with it specifically.

## The three parties

- **Buyer** — funds the job, writes the criteria, assigns a price, releases or
  disputes. Cannot move money to itself after work is accepted without the ledger
  showing it.
- **Worker** — bids, delivers an artifact plus the hash of that artifact. Its only
  on-chain move is `submit`. It cannot release funds to itself.
- **Arbiter** — resolves a dispute with a published rule. In this version a single
  account; see *Known weakness* below.

## What each party can and cannot do

| Actor | Can | Cannot |
|---|---|---|
| Buyer | fund, assign, release, refund, dispute | submit as the worker, resolve its own dispute |
| Worker | bid, submit evidence | release, refund, dispute, resolve |
| Arbiter | resolve, once disputed | act before a dispute, release on its own initiative |
| Anyone | expire a job past its deadline | expire a job before its deadline, move money |

Authority is a table in `handoff/escrow.py:AUTHORITY` and an `only(...)` check per
method in the contract. It is not scattered through handlers.

## What the hash chain buys you

Each entry commits to `(seq, ts, kind, payload, prev_hash)`. The worker publishes
the hash of its delivery event at submit time. Therefore:

- A buyer who edits a past "amount" must recompute every later entry, **and** the
  final hash must still equal the one the worker kept. It will not.
- A buyer who deletes the delivery event breaks the `prev` link of the next entry.
- A buyer who reorders entries changes `seq`, which is inside the hash.

`python3 -m handoff tamper` performs exactly this edit and prints the entry number
where verification stops. The detection is not cryptographic identity — anyone can
build a *new* valid chain from scratch — it is **evidence of a specific published
history**, which is the thing a dispute actually needs.

## Fail-closed criteria

`verify()` treats an unknown criterion kind as a failure, refuses paths that
escape the workspace, requires `command_exit_zero` to receive a list (never a
shell string), and runs with a timeout. A buyer cannot smuggle a passing verdict
in with a criterion the checker does not understand, and a worker cannot use
`../..` to satisfy `file_exists`. Both directions matter: the first protects the
buyer, the second protects everyone else.

## Known weakness: one arbiter

`resolve(to_worker_bps)` trusts a single account. That account can split 100/0 in
either direction. The mitigation in this version is disclosure, not cryptography:
the rule name and its output are in the ledger, so a bad arbiter produces a
permanently visible record. The real fix — a panel with staked arbiters, drawn per
dispute, with slashing on provable misbehaviour — is designed for and not built.

## What this does not solve

- **Sybil workers.** A new key starts at reputation 50. Nothing here makes
  reputation expensive to abandon.
- **Criteria gaming.** A worker that learns exactly which checks run can satisfy
  the letter of them. Handoff narrows the gap by hashing the criteria with the
  terms before funding, but a buyer who writes a weak spec gets a weak job.
- **Privacy.** Artifact hashes are on a public ledger. Deliverable contents are
  not, but their existence and timing are.
- **Dispute cost.** Arbitration is not free in reality; this version assigns it a
  fee split but models no bond, no delay and no appeal.
