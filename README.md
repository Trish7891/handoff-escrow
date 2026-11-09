# Handoff

**Escrow and proof-of-work settlement for agent labour.**

An agent does a job, the buyer pays — but only after a machine checks the work.
Handoff is the missing middle: a hash-chained ledger of every event, a job state
machine that is the same in Python and in a NEAR contract, and an offline report
that shows the payment *and* the failures that stopped it.

No accounts. No dashboard. Three commands reproduce every claim below.

```bash
python3 -m handoff demo     # run three jobs end to end, write artifacts/
python3 -m handoff verify   # replay the hash chain and confirm nothing moved
python3 -m handoff tamper   # edit a past entry: the chain rejects it
```

No dependencies outside the standard library. Python 3.10+.

## The problem it is aimed at

Agents can already find work and do work. What they cannot do is get paid without
a human in the loop, because the buyer has to trust that the artifact is real and
the worker has to trust that the money exists. Every marketplace built for humans
solves this with accounts, ratings and a support queue — none of which an agent
can use, and none of which scale to a 0.02 NEAR job.

Handoff makes the payment condition explicit up front, mechanical at delivery,
and auditable afterwards:

1. **Money is escrowed before work starts**, so the worker never works on credit.
2. **Criteria are machine-checkable** (`file_exists`, `json_keys`, `matches`,
   `words_at_most`, `command_exit_zero`, `artifact_sha256`), so the release is a
   function, not a judgement call.
3. **Every event is hash-chained**, so a buyer who rewrites their log has to
   rewrite every later entry and still match the hash the worker published at
   delivery time.
4. **Taste is quarantined in the dispute path**, where an arbiter applies a
   published rule and its split lands in the same ledger.

## What the demo actually does

One shared ledger, three jobs, three different endings:

| job | winner | outcome | verdict | money conserved |
|---|---|---|---|---|
| `clean` | `scribe-01.near` | `released` | pass | yes |
| `bad` | `scribe-02.near` | `refunded` | fail | yes |
| `dispute` | `scribe-04.near` | `resolved` | fail (4/5) | yes |

- **clean** — three bids, the cheapest is filtered out on reputation, the buyer
  takes `scribe-01` at 60% of budget. Five criteria pass; escrow releases 99.5%
  to the worker and 0.5% to the treasury. The worker then hires `scribe-03` for a
  follow-up job out of the money it just earned — a second payment, still with no
  human signature.
- **bad** — `scribe-02` runs a weaker invoice parser, gets the total wrong
  (`22091.04`), and the arithmetic check exits non-zero. No release. The escrow
  refunds the buyer in full and the worker is paid nothing. The failure is
  printed, not swallowed.
- **dispute** — `scribe-04` gets the structured fields right but pads the summary
  past the agreed word cap, so 4 of 5 checks pass. The buyer disputes rather than
  refunding outright; the arbiter's published rule pays in proportion to passing
  checks (80%), and the split, the rule and the evidence hash all land in the
  ledger. A worker who disagrees can quote entry numbers instead of arguing.

After `demo`, `artifacts/` holds `ledger.json` (57 entries), `results.json`, the
per-job workspaces, and `report.html` — one standalone file, no CDN, no
JavaScript, no web fonts, readable with the network unplugged.

## Repository layout

```
handoff/
  model.py       integer yoctoNEAR money, canonical JSON, hashing, task types
  ledger.py      append-only hash chain; replay and verification
  escrow.py      the job state machine, and who may fire which event
  criteria.py    fail-closed verifiers; unknown criteria never pass
  agents.py      buyer, workers and arbiter; deterministic bidding and delivery
  scenarios.py   the three jobs above, on one clock and one ledger
  report.py      the offline HTML report
  cli.py         demo / verify / tamper
contracts/handoff/
  src/lib.rs     the same state table, enforced on chain, with 7 unit tests
tests/           38 tests: parity, ledger, escrow, criteria, end-to-end
docs/TRUST.md    the threat model, and what this deliberately does not solve
```

## The contract

`contracts/handoff/src/lib.rs` mirrors `handoff/escrow.py` one-to-one, and
`tests/test_parity.py` parses the Rust source as text so the two cannot drift
apart silently — a divergence fails the Python suite, not a review.

```
OPEN --fund--> FUNDED --assign--> ASSIGNED --submit--> DELIVERED
FUNDED/ASSIGNED --expire--> REFUNDED        DELIVERED --release--> RELEASED
DELIVERED --dispute--> DISPUTED --resolve--> RESOLVED
FUNDED/DELIVERED/DISPUTED --refund--> REFUNDED
```

Money rules the contract enforces, not documents:

- `fund` requires the **exact** attached budget; the terms hash and the deadline
  are locked at the same time.
- `assign` returns the difference between budget and price immediately.
- `release` pays the worker the price net of a fee capped at 500 bps — a fee above
  5% fails to deploy rather than quietly taking the worker's money.
- `resolve` charges the fee only on the worker's share and returns the rest; the
  three legs always sum to the escrowed price.
- `expire` is callable by anyone, but only after the deadline, and only refunds.
- `submit` checks legality before it touches state, so an out-of-order call panics
  with the state it refused rather than a null dereference.

```bash
cargo test --manifest-path contracts/handoff/Cargo.toml   # 7 passed
```

## Tests

```bash
python3 -m unittest discover -s tests -t .    # 38 passed
```

The suite is not decoration: `test_replay_is_byte_identical` runs the whole
simulation twice in separate directories and asserts the ledger head and balances
match; `test_worker_cannot_take_the_money` and `test_stranger_cannot_submit` prove authority
is enforced;
`test_unknown_kind_fails_closed` and `test_path_traversal_is_refused_not_followed`
prove a malformed criterion costs the worker the job rather than paying them for
nothing.

## Limits, stated plainly

- **Verification is only as good as the criteria.** A buyer who writes vague
  criteria gets a vague verdict, and a worker who accepts them has accepted that
  risk. Handoff makes the criteria explicit and hashed; it cannot make them wise.
- **The arbiter is a trust assumption.** The rule is published and its output is
  in the ledger, but a dishonest arbiter can still split badly. Multiple arbiters
  with a stake is the obvious next step and is not built here.
- **The Python engine is the demo, not the deployment.** On chain, one contract
  instance holds one job; there is no factory, registry or indexer yet, so
  discovering jobs is out of scope for this version.
- **Amounts are simulated.** The NEAR figures in the demo are yoctoNEAR integers
  moved between in-memory accounts; the contract is unit-tested, not deployed to
  testnet with real deposits.
- **No reputation portability.** Reputation moves within a run; it is not
  attested across markets, and nothing here prevents a worker from starting over
  under a new key.

## Status

Working demo (three scenarios, verified chain, offline report), contract with unit
tests, parity test between the two. Built for the NEAR Hackathon, Track 07 —
Agent Economy.

Licence: MIT.
