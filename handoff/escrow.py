"""The job state machine. This is the single source of truth for both runtimes.

``contracts/handoff/src/lib.rs`` implements exactly the transitions below, with
the same names and the same guards; ``tests/test_parity.py`` reads the Rust file
and fails the build if the two tables ever drift. Keeping the table here means
the demo and the chain cannot disagree about what "released" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OPEN = "OPEN"
FUNDED = "FUNDED"
ASSIGNED = "ASSIGNED"
DELIVERED = "DELIVERED"
DISPUTED = "DISPUTED"
RELEASED = "RELEASED"
REFUNDED = "REFUNDED"
RESOLVED = "RESOLVED"

STATES = (OPEN, FUNDED, ASSIGNED, DELIVERED, DISPUTED, RELEASED, REFUNDED, RESOLVED)
TERMINAL = frozenset({RELEASED, REFUNDED, RESOLVED})

#: (state, event) -> next state
TRANSITIONS: dict[tuple[str, str], str] = {
    (OPEN, "fund"): FUNDED,
    (FUNDED, "assign"): ASSIGNED,
    (FUNDED, "refund"): REFUNDED,
    (FUNDED, "expire"): REFUNDED,
    (ASSIGNED, "submit"): DELIVERED,
    (ASSIGNED, "expire"): REFUNDED,
    (DELIVERED, "release"): RELEASED,
    (DELIVERED, "refund"): REFUNDED,
    (DELIVERED, "dispute"): DISPUTED,
    (DISPUTED, "resolve"): RESOLVED,
    (DISPUTED, "refund"): REFUNDED,
}

#: Events that must be signed by a specific party. Enforced by the contract's
#: ``assert_eq!(env::predecessor_account_id(), ..)`` guards, mirrored by Escrow.
AUTHORITY = {
    "fund": "buyer",
    "assign": "buyer",
    "submit": "worker",
    "release": "buyer",
    "refund": "buyer",
    "dispute": "buyer",
    "resolve": "arbiter",
    "expire": "anyone",
}

FEE_BPS = 50  # 0.50% of released value, paid to the treasury; zero on refunds


class IllegalTransition(Exception):
    pass


def fee_on(amount_yocto: int) -> int:
    return amount_yocto * FEE_BPS // 10_000


@dataclass
class Escrow:
    """One job's money. Holds no keys: it is a ledger position, not a wallet."""

    escrow_id: str
    buyer: str
    arbiter: str
    amount_yocto: int
    deadline_ts: float = 0.0
    state: str = OPEN
    worker: str | None = None
    proof_hash: str = ""
    terms_hash: str = ""
    settlement: dict = field(default_factory=dict)

    def allowed(self, event: str) -> bool:
        return (self.state, event) in TRANSITIONS

    def apply(self, event: str, actor: str, ts: float, ledger=None, **kw) -> str:
        """Apply one event, or raise. Returns the new state.

        The authority check runs before the transition check so that a stranger
        poking at a funded job gets "not your call", not a free state probe.
        """
        required = AUTHORITY.get(event, "anyone")
        if required != "anyone" and actor != getattr(self, required, None):
            raise IllegalTransition(
                f"{event} requires {required}={getattr(self, required, None)!r}, got {actor!r}"
            )
        key = (self.state, event)
        if key not in TRANSITIONS:
            raise IllegalTransition(f"{event} is not legal in {self.state}")
        nxt = TRANSITIONS[key]

        if event == "fund":
            self.terms_hash = kw.get("terms_hash", self.terms_hash)
            self.deadline_ts = kw.get("deadline_ts", self.deadline_ts)
        elif event == "assign":
            self.worker = kw["worker"]
            self.amount_yocto = kw.get("price_yocto", self.amount_yocto)
        elif event == "submit":
            self.proof_hash = kw["proof_hash"]
        elif event == "release":
            fee = fee_on(self.amount_yocto)
            self.settlement = {
                "to": self.worker,
                "amount_yocto": self.amount_yocto - fee,
                "fee_yocto": fee,
            }
        elif event == "refund":
            self.settlement = {"to": self.buyer, "amount_yocto": self.amount_yocto, "fee_yocto": 0}
        elif event == "resolve":
            to_worker_bps = int(kw["to_worker_bps"])
            to_worker = self.amount_yocto * to_worker_bps // 10_000
            fee = fee_on(to_worker)
            self.settlement = {
                "to": self.worker,
                "amount_yocto": to_worker - fee,
                "fee_yocto": fee,
                "refund_yocto": self.amount_yocto - to_worker,
                "to_worker_bps": to_worker_bps,
            }

        self.state = nxt
        if ledger is not None:
            ledger.append(
                "escrow.event",
                escrow_id=self.escrow_id,
                event=event,
                actor=actor,
                from_state=key[0],
                to_state=nxt,
                amount_yocto=self.amount_yocto,
                proof_hash=self.proof_hash,
                settlement=self.settlement or None,
                ts=round(ts, 6),
            )
        return nxt
