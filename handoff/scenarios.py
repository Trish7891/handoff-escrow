"""Three runs of the same loop: a job that pays, one that does not, and one split.

Each scenario builds a fresh set of accounts on a shared ledger so the report can
show a single chain containing all three outcomes. Timestamps come from a tick
clock, so the artifacts are byte-identical on every run.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .agents import (
    ArbiterAgent,
    BuyerAgent,
    Economy,
    WorkerAgent,
    workspace_for,
)
from .criteria import verify
from .ledger import Ledger
from .model import YOCTO, Criterion, Task, near

INVOICE = """Vendor: Kalahari Office Supplies (Pty) Ltd
Invoice No: KOS-2291
Date: 2026-11-03
Due date: 2026-12-03
Currency: ZAR

Description                 Qty     Unit      Amount
A4 paper (box)               12    289.50    3474.00
Toner cartridge HP 26A        2    899.00    1798.00
Courier                       1    145.00     145.00

Subtotal: ZAR 5417.00
VAT 15%: ZAR 812.55
Total due: ZAR 6229.55
"""

INVOICE_2 = INVOICE.replace("KOS-2291", "KOS-2304").replace("2026-12-03", "2026-12-10")


class Tick:
    """Deterministic clock: every ledger event is 37 seconds after the last."""

    def __init__(self, start: float = 1_762_400_000.0, step: float = 37.0):
        self.t = start
        self.step = step

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def invoice_task(tid: str, budget: float, source: str = "inbox/invoice.txt") -> Task:
    """The commodity job: pull five fields out of a supplier invoice, prove them."""
    return Task(
        id=tid,
        title="Extract supplier invoice fields",
        brief=(
            "Read the invoice in inbox/, write out/invoice.json with vendor, "
            "invoice_number, total, due_date and currency, plus out/summary.md "
            "under 120 words."
        ),
        criteria=(
            Criterion("file_exists", {"path": "out/invoice.json", "min_bytes": 80}, "the deliverable exists"),
            Criterion("json_keys", {"path": "out/invoice.json", "keys": ["vendor", "invoice_number", "total", "due_date", "currency"]}, "all five fields"),
            Criterion(
                "command_exit_zero",
                {
                    "cmd": [
                        "python3",
                        "-c",
                        "import json;d=json.load(open('out/invoice.json'));"
                        "assert abs(d['total']-6229.55)<0.01, d['total'];"
                        "assert d['invoice_number']=='KOS-2291', d['invoice_number']",
                    ]
                },
                "the numbers are the invoice's numbers",
            ),
            Criterion("words_at_most", {"path": "out/summary.md", "max": 120}, "summary stays short"),
            Criterion("matches", {"path": "out/invoice.json", "pattern": '"currency": "ZAR"'}, "currency is the invoice currency"),
        ),
        budget_yocto=int(budget * YOCTO),
        deadline_s=900,
    )


def run_clean(root: Path, ledger: Ledger, tick: Tick) -> dict:
    """A careful worker wins on reputation-adjusted price and gets paid on proof."""
    eco = Economy(ledger, root)
    eco.open_account("buyer.kalahari", 5 * YOCTO, reputation=80)
    eco.open_account("scribe-01.near", YOCTO // 20, reputation=62)
    eco.open_account("scribe-02.near", YOCTO // 20, reputation=34)
    eco.open_account("scribe-03.near", YOCTO // 20, reputation=71)
    eco.open_account("arbiter.near", YOCTO // 100, reputation=95)

    task = invoice_task("inv-2291", budget=0.02)
    esc = eco.post(task, buyer="buyer.kalahari", arbiter="arbiter.near")
    eco.fund(esc, tick())

    workers = [
        WorkerAgent("scribe-01.near", quality="careful"),
        WorkerAgent("scribe-02.near", quality="sloppy"),
        WorkerAgent("scribe-03.near", quality="careful", rate_bps=7400),
    ]
    bids = [w.quote(task, eco.accounts[w.name]) for w in workers]
    bids[0] = replace(bids[0], note="parses line items, re-checks the stated total")
    bids[1] = replace(bids[1], note="cheapest bid")
    bids[2] = replace(bids[2], note="premium rate")

    buyer = BuyerAgent("buyer.kalahari", max_price=int(0.018 * YOCTO), min_reputation=45)
    won = buyer.choose(bids)
    assert won is not None, "no acceptable bid"
    eco.assign(esc, won, tick())

    ws = workspace_for(root, "clean", INVOICE)
    agent = next(w for w in workers if w.name == won.worker)
    delivery = agent.execute(task, ws)
    eco.submit(esc, delivery, tick())
    verdict = verify(delivery, task.criteria, ws)
    eco.settle(esc, verdict, tick())

    # Round two: the worker now spends its earnings hiring a peer. No human in
    # the loop — the buyer here is an agent whose balance came from job one.
    sub_task = invoice_task("inv-2304", budget=0.006, source="inbox/invoice.txt")
    sub_esc = eco.post(sub_task, buyer=won.worker, arbiter="arbiter.near")
    eco.fund(sub_esc, tick())
    peer_agent = WorkerAgent("scribe-03.near", quality="careful")
    peer_bid = peer_agent.quote(sub_task, eco.accounts["scribe-03.near"])
    eco.assign(sub_esc, peer_bid, tick())
    sub_ws = workspace_for(root, "clean-sub", INVOICE_2)
    # The sub-job reuses the structural criteria only: the arithmetical assertion
    # is written for invoice 2291 and would be a lie against 2304.
    sub_criteria = [sub_task.criteria[0], sub_task.criteria[1], sub_task.criteria[3]]
    sub_delivery = peer_agent.execute(sub_task, sub_ws)
    eco.submit(sub_esc, sub_delivery, tick())
    sub_verdict = verify(sub_delivery, sub_criteria, sub_ws)
    eco.settle(sub_esc, sub_verdict, tick(), action="release" if sub_verdict.passed else "refund")

    return {
        "id": "clean",
        "label": "Job paid on proof",
        "narrative": (
            "Three workers bid. The cheapest is filtered out on reputation, so the buyer takes "
            "scribe-01 at 60% of budget. The worker delivers a JSON file and a short summary; "
            "five criteria are evaluated mechanically; escrow releases 99.5% to the worker and "
            "0.5% to the treasury. The worker then hires scribe-03 for a follow-up job out of the "
            "money it just earned — the second payment needs no human signature either."
        ),
        "task": {"title": task.title, "budget": near(task.budget_yocto)},
        "bids": [
            {"worker": b.worker, "price": near(b.price_yocto), "reputation": b.reputation, "note": b.note}
            for b in bids
        ],
        "winner": won.worker,
        "verdict": verdict.to_dict(),
        "outcome": "released",
        "second_job": {
            "buyer": won.worker,
            "worker": peer_bid.worker,
            "price": near(peer_bid.price_yocto),
            "verdict": sub_verdict.to_dict(),
            "outcome": sub_esc.state,
        },
        "balances": eco.balances(),
        "conserved": eco.conserved(),
        "escrow_ids": [esc.escrow_id, sub_esc.escrow_id],
    }


def run_bad_proof(root: Path, ledger: Ledger, tick: Tick) -> dict:
    """Cheap and wrong: the verifier refuses, the buyer keeps the money."""
    eco = Economy(ledger, root)
    eco.open_account("buyer.ledgerline", 3 * YOCTO, reputation=70)
    eco.open_account("scribe-02.near", YOCTO // 20, reputation=55)
    eco.open_account("scribe-01.near", YOCTO // 20, reputation=62)
    eco.open_account("arbiter.near", YOCTO // 100, reputation=95)

    task = invoice_task("inv-2291-b", budget=0.02)
    esc = eco.post(task, buyer="buyer.ledgerline", arbiter="arbiter.near")
    eco.fund(esc, tick())

    workers = [WorkerAgent("scribe-02.near", quality="sloppy"), WorkerAgent("scribe-01.near", quality="careful")]
    bids = [w.quote(task, eco.accounts[w.name]) for w in workers]
    bids[0] = replace(bids[0], note="undercuts by 15%")
    bids[1] = replace(bids[1], note="the careful bid")

    buyer = BuyerAgent("buyer.ledgerline", max_price=int(0.018 * YOCTO), min_reputation=50)
    won = buyer.choose(bids)
    assert won is not None, "no acceptable bid"
    eco.assign(esc, won, tick())

    ws = workspace_for(root, "bad", INVOICE)
    agent = next(w for w in workers if w.name == won.worker)
    delivery = agent.execute(task, ws)
    eco.submit(esc, delivery, tick())
    verdict = verify(delivery, task.criteria, ws)
    eco.settle(esc, verdict, tick())  # auto: refund, because the verdict failed

    return {
        "id": "bad",
        "label": "Job refused on bad proof",
        "narrative": (
            "The cheapest bid wins, and it is wrong: the worker multiplies the line items by a "
            "fudge factor instead of using the stated total. The assertion criterion fails, so "
            "the escrow refunds the buyer in full, the worker is paid nothing, and its "
            "reputation drops. The failure is in the ledger with the failing assertion text, so "
            "the worker can see exactly which claim it could not back."
        ),
        "task": {"title": task.title, "budget": near(task.budget_yocto)},
        "bids": [
            {"worker": b.worker, "price": near(b.price_yocto), "reputation": b.reputation, "note": b.note}
            for b in bids
        ],
        "winner": won.worker,
        "verdict": verdict.to_dict(),
        "outcome": "refunded",
        "balances": eco.balances(),
        "conserved": eco.conserved(),
        "escrow_ids": [esc.escrow_id],
    }


def run_dispute(root: Path, ledger: Ledger, tick: Tick) -> dict:
    """Mostly done: the buyer disputes, the arbiter splits, both sides can see why."""
    eco = Economy(ledger, root)
    eco.open_account("buyer.umoya", 3 * YOCTO, reputation=75)
    eco.open_account("scribe-04.near", YOCTO // 20, reputation=48)
    eco.open_account("arbiter.near", YOCTO // 100, reputation=95)

    task = invoice_task("inv-2291-c", budget=0.02)
    esc = eco.post(task, buyer="buyer.umoya", arbiter="arbiter.near")
    eco.fund(esc, tick())

    worker = WorkerAgent("scribe-04.near", quality="partial")
    bids = [worker.quote(task, eco.accounts[worker.name])]
    bids[0] = replace(bids[0], note="only bidder")
    buyer = BuyerAgent("buyer.umoya", max_price=int(0.018 * YOCTO), min_reputation=40)
    won = buyer.choose(bids)
    assert won is not None, "no acceptable bid"
    eco.assign(esc, won, tick())

    ws = workspace_for(root, "dispute", INVOICE)
    delivery = worker.execute(task, ws)
    eco.submit(esc, delivery, tick())
    verdict = verify(delivery, task.criteria, ws)

    # The buyer does not auto-refund: the fields are right, the summary is padded.
    eco.settle(esc, verdict, tick(), action="dispute")
    arbiter = ArbiterAgent("arbiter.near", rule="proportional")
    bps = arbiter.rule_on(esc, verdict, delivery)
    passed = sum(1 for c in verdict.checks if c.ok)
    eco.resolve(esc, arbiter, bps, tick())

    return {
        "id": "dispute",
        "label": "Job split by an arbiter",
        "narrative": (
            "The structured file is correct but the summary is padded past the agreed limit, so "
            f"{passed} of {len(verdict.checks)} checks pass. The buyer disputes instead of "
            "refunding outright. The arbiter's published rule pays in proportion to passing "
            f"checks — {bps / 100:.0f}% here — and the split, the rule and the evidence hash all "
            "land in the same ledger. A worker who disagrees can quote entry numbers instead of "
            "arguing about vibes."
        ),
        "task": {"title": task.title, "budget": near(task.budget_yocto)},
        "bids": [
            {"worker": b.worker, "price": near(b.price_yocto), "reputation": b.reputation, "note": b.note}
            for b in bids
        ],
        "winner": won.worker,
        "verdict": verdict.to_dict(),
        "arbiter": {"rule": arbiter.rule, "to_worker_bps": bps, "to_worker": near(bps * task.budget_yocto // 10_000)},
        "outcome": "resolved",
        "balances": eco.balances(),
        "conserved": eco.conserved(),
        "escrow_ids": [esc.escrow_id],
    }


SCENARIOS = [run_clean, run_bad_proof, run_dispute]


def run_all(root: Path) -> dict:
    root = Path(root)
    tick = Tick()
    ledger = Ledger(clock=tick)
    results = []
    for fn in SCENARIOS:
        start = len(ledger.entries)
        res = fn(root, ledger, tick)
        res["events"] = [e.to_dict() for e in ledger.entries[start:]]
        results.append(res)
    ok, bad = ledger.verify()
    return {
        "scenarios": results,
        "ledger": {
            "entries": len(ledger.entries),
            "head": ledger.head,
            "verified": ok,
            "broken_at": bad,
            "total_volume": near(
                sum(
                    (e.payload.get("settlement") or {}).get("amount_yocto", 0)
                    + (e.payload.get("settlement") or {}).get("fee_yocto", 0)
                    for e in ledger.of_kind("settlement")
                )
            ),
        },
    }
