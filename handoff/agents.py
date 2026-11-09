"""Three agents and the market they trade in.

The loop is the whole pitch of the project: an agent earns money by delivering
verified work, and spends that money hiring another agent. No human signs a
payment, because the payment condition was a hash the buyer published before
the money moved.

Everything is deterministic. Given the same scenario name, the same bytes come
out, which is what makes the demo reviewable and the tests meaningful.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .criteria import Verdict, verify
from .escrow import Escrow, IllegalTransition, fee_on
from .ledger import Ledger
from .model import YOCTO, Bid, Delivery, Task, near, sha256_file

TREASURY = "treasury.near"


@dataclass
class Account:
    name: str
    balance: int = 0
    reputation: int = 50
    earned: int = 0
    spent: int = 0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "balance": near(self.balance),
            "balance_yocto": self.balance,
            "reputation": self.reputation,
            "earned": near(self.earned),
            "spent": near(self.spent),
        }


@dataclass
class WorkerAgent:
    """A worker that does a real, checkable transformation of its inputs.

    ``quality`` is the honest/dishonest knob used by the scenarios: a careful
    worker computes the field it was asked for, a sloppy one guesses. Both get
    scored by the same verifier, which is the point.
    """

    name: str
    quality: str = "careful"  # careful | sloppy | partial
    cost: int = YOCTO // 1000
    rate_bps: int = 6000  # ask as basis points of the buyer's budget

    def quote(self, task: Task, account: Account) -> Bid:
        base = max(task.budget_yocto * self.rate_bps // 10_000, self.cost)
        price = base if self.quality == "careful" else base * 85 // 100
        return Bid(worker=self.name, price_yocto=price, reputation=account.reputation)

    def execute(self, task: Task, workspace: Path) -> Delivery:
        """Do the job. Writes into ``workspace`` and returns its own receipt."""
        ws = Path(workspace)
        out = ws / "out"
        out.mkdir(parents=True, exist_ok=True)
        src = task.criteria[0].params.get("path", "inbox/invoice.txt")

        text = ""
        for cand in ws.rglob("*.txt"):
            text = cand.read_text(errors="replace")
            break

        fields = self._extract(text, sloppy=self.quality == "sloppy")
        (out / "invoice.json").write_text(json.dumps(fields, indent=2) + "\n")
        summary = (
            f"# {task.title}\n\n"
            f"Vendor {fields['vendor']} invoice {fields['invoice_number']} for "
            f"{fields['currency']} {fields['total']} is due {fields['due_date']}.\n"
            f"Source: {Path(src).name}. Fields were extracted mechanically and the "
            f"arithmetic re-checked against the line items before writing.\n"
        )
        (out / "summary.md").write_text(summary)
        if self.quality == "partial":
            # Structured file is right, summary is padded: 4 of 5 checks pass.
            (out / "summary.md").write_text(summary + ("Padding sentence. " * 60))
            exit_code = 0
        exit_code = 0 if self.quality == "careful" else 1
        art = out / "invoice.json"
        return Delivery(
            job_id=task.id,
            worker=self.name,
            artifact=str(art.relative_to(ws)),
            artifact_sha256=sha256_file(art),
            exit_code=exit_code,
            notes="fields parsed from the invoice text",
        )

    @staticmethod
    def _extract(text: str, sloppy: bool = False) -> dict:
        def grab(pattern, default=""):
            m = re.search(pattern, text, re.IGNORECASE)
            return m.group(1).strip() if m else default

        vendor = grab(r"^Vendor:\s*(.+)$", "unknown")
        number = grab(r"Invoice\s*(?:No\.?|Number|#)\s*[:#]?\s*([A-Z0-9-]+)", "unknown")
        currency = grab(r"Currency:\s*([A-Z]{3})", "USD")
        due = grab(r"Due(?:\s*date)?:\s*(\d{4}-\d{2}-\d{2})", "unknown")

        amounts = re.findall(r"(\d+\.\d{2})", text)
        total = 0.0
        for a in amounts:
            total += float(a)
        if sloppy:
            total = total * 1.15  # "close enough" — and it is not
        # The invoice states its own total; use line-item arithmetic only as a check.
        m = re.search(r"^\s*Total(?:\s+due)?:\s*([A-Z]{3})\s*(\d+\.\d{2})", text, re.IGNORECASE | re.MULTILINE)
        stated = m.group(2) if m else ""
        if stated and not sloppy:
            total = float(stated)
        return {
            "vendor": vendor,
            "invoice_number": number,
            "total": round(total, 2),
            "due_date": due,
            "currency": currency,
        }


@dataclass
class BuyerAgent:
    name: str
    max_price: int
    min_reputation: int = 40

    def choose(self, bids: list[Bid]) -> Bid | None:
        """Cheapest bid that clears the reputation floor and the price ceiling."""
        ok = [b for b in bids if b.reputation >= self.min_reputation and b.price_yocto <= self.max_price]
        return min(ok, key=lambda b: (b.price_yocto, -b.reputation)) if ok else None


@dataclass
class ArbiterAgent:
    name: str
    rule: str = "proportional"  # proportional | worker | buyer
    workdir: Path | None = None

    def rule_on(self, escrow: Escrow, verdict: Verdict | None, delivery: Delivery) -> int:
        """Return basis points to the worker. Deterministic and written down."""
        if self.rule == "worker":
            return 10_000
        if self.rule == "buyer":
            return 0
        if verdict is not None and verdict.passed:
            return 10_000
        if verdict is not None:
            good = sum(1 for c in verdict.checks if c.ok)
            return max(0, min(10_000, good * 10_000 // max(1, len(verdict.checks))))
        return 0


class Economy:
    """Accounts, escrows and one ledger. Money only moves through this class."""

    def __init__(self, ledger: Ledger, root: Path):
        self.ledger = ledger
        self.root = Path(root)
        self.accounts: dict[str, Account] = {}
        self.escrows: dict[str, Escrow] = {}
        self._seq = 0
        self.initial_total = 0
        self.treasury = Account(TREASURY)
        self.accounts[TREASURY] = self.treasury

    # -- accounts ----------------------------------------------------------
    def open_account(self, name: str, yocto: int, reputation: int = 50) -> Account:
        acc = Account(name=name, balance=yocto, reputation=reputation)
        self.accounts[name] = acc
        self.initial_total += yocto
        self.ledger.append("wallet.open", account=name, balance_yocto=yocto)
        return acc

    def _debit(self, name: str, amount: int, why: str) -> None:
        acc = self.accounts[name]
        if acc.balance < amount:
            raise ValueError(f"{name} cannot cover {near(amount)} NEAR for {why}")
        acc.balance -= amount
        self.ledger.append("wallet.debit", account=name, amount_yocto=amount, reason=why)

    def _credit(self, name: str, amount: int, why: str) -> None:
        acc = self.accounts.setdefault(name, Account(name=name))
        acc.balance += amount
        self.ledger.append("wallet.credit", account=name, amount_yocto=amount, reason=why)

    # -- jobs --------------------------------------------------------------
    def post(self, task: Task, buyer: str, arbiter: str) -> Escrow:
        self._seq += 1
        eid = f"job-{self._seq:03d}"
        esc = Escrow(
            escrow_id=eid,
            buyer=buyer,
            arbiter=arbiter,
            amount_yocto=task.budget_yocto,
        )
        self.escrows[eid] = esc
        self.ledger.append(
            "job.posted",
            escrow_id=eid,
            buyer=buyer,
            title=task.title,
            terms_hash=task.terms_hash,
            criteria=[c.kind for c in task.criteria],
            budget_yocto=task.budget_yocto,
        )
        return esc

    def fund(self, esc: Escrow, ts: float) -> None:
        self._debit(esc.buyer, esc.amount_yocto, f"fund {esc.escrow_id}")
        esc.apply(
            "fund",
            actor=esc.buyer,
            ts=ts,
            ledger=self.ledger,
            terms_hash=esc.terms_hash,
            deadline_ts=ts + 600,
        )

    def assign(self, esc: Escrow, bid: Bid, ts: float) -> None:
        buyer = self.accounts[esc.buyer]
        if bid.price_yocto > esc.amount_yocto:
            raise ValueError("bid exceeds the funded amount")
        # Refund the difference between funded budget and agreed price.
        diff = esc.amount_yocto - bid.price_yocto
        esc.apply(
            "assign",
            actor=esc.buyer,
            ts=ts,
            ledger=self.ledger,
            worker=bid.worker,
            price_yocto=bid.price_yocto,
        )
        if diff:
            self._credit(esc.buyer, diff, f"unused escrow {esc.escrow_id}")
        buyer.spent += bid.price_yocto

    def submit(self, esc: Escrow, delivery: Delivery, ts: float) -> None:
        esc.apply("submit", actor=esc.worker or "", ts=ts, ledger=self.ledger, proof_hash=delivery.evidence_hash)
        self.ledger.append(
            "delivery.received",
            escrow_id=esc.escrow_id,
            worker=delivery.worker,
            artifact=delivery.artifact,
            artifact_sha256=delivery.artifact_sha256,
            evidence_hash=delivery.evidence_hash,
        )

    def settle(self, esc: Escrow, verdict: Verdict, ts: float, *, action: str = "auto") -> str:
        """Release, refund, or dispute — the only place money leaves escrow."""
        worker = self.accounts.get(esc.worker or "", Account(name=esc.worker or "?"))
        if action == "auto":
            action = "release" if verdict.passed else "refund"
        if action == "release":
            esc.apply("release", actor=esc.buyer, ts=ts, ledger=self.ledger)
            st = esc.settlement
            self._credit(st["to"], st["amount_yocto"], f"payout {esc.escrow_id}")
            if st["fee_yocto"]:
                self._credit(TREASURY, st["fee_yocto"], f"fee {esc.escrow_id}")
            worker.earned += st["amount_yocto"]
            worker.reputation = min(100, worker.reputation + 3)
        elif action == "refund":
            esc.apply("refund", actor=esc.buyer, ts=ts, ledger=self.ledger)
            st = esc.settlement
            self._credit(st["to"], st["amount_yocto"], f"refund {esc.escrow_id}")
            if esc.worker:
                worker.reputation = max(0, worker.reputation - 2)
        elif action == "dispute":
            esc.apply("dispute", actor=esc.buyer, ts=ts, ledger=self.ledger)
        else:
            raise ValueError(action)
        self.ledger.append(
            "settlement",
            escrow_id=esc.escrow_id,
            action=action,
            verdict=verdict.to_dict(),
            settlement=esc.settlement or None,
        )
        return action

    def resolve(self, esc: Escrow, arbiter: ArbiterAgent, bps: int, ts: float) -> None:
        esc.apply("resolve", actor=arbiter.name, ts=ts, ledger=self.ledger, to_worker_bps=bps)
        st = esc.settlement
        if st["amount_yocto"]:
            self._credit(st["to"], st["amount_yocto"], f"ruling payout {esc.escrow_id}")
        if st["fee_yocto"]:
            self._credit(TREASURY, st["fee_yocto"], f"fee {esc.escrow_id}")
        if st["refund_yocto"]:
            self._credit(esc.buyer, st["refund_yocto"], f"ruling refund {esc.escrow_id}")
        worker = self.accounts.get(esc.worker or "")
        if worker:
            worker.earned += st["amount_yocto"]

    # -- invariants --------------------------------------------------------
    def total(self) -> int:
        return sum(a.balance for a in self.accounts.values()) + sum(
            e.amount_yocto for e in self.escrows.values() if e.state not in {"RELEASED", "REFUNDED", "RESOLVED"}
        )

    def conserved(self) -> bool:
        return self.total() == self.initial_total

    def balances(self) -> dict[str, dict]:
        return {n: a.as_dict() for n, a in sorted(self.accounts.items())}


def workspace_for(root: Path, name: str, source: str) -> Path:
    ws = Path(root) / name
    if ws.exists():
        shutil.rmtree(ws)
    (ws / "inbox").mkdir(parents=True)
    (ws / "inbox" / "invoice.txt").write_text(source)
    return ws
