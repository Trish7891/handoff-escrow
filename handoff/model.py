"""Data carried between a buyer agent, a worker agent and the arbiter.

Amounts are integer yoctoNEAR (1 NEAR = 10**24 yoctoNEAR) exactly as the
contract stores them. Never float money.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

YOCTO = 10**24


def near(amount_yocto: int) -> str:
    """Format yoctoNEAR for humans: 15 digits of precision, trailing zeros cut."""
    whole, frac = divmod(amount_yocto, YOCTO)
    s = f"{whole}.{frac:024d}".rstrip("0").rstrip(".")
    return s or "0"


def canonical(obj) -> bytes:
    """Stable JSON encoding — byte-identical on every machine, so hashes agree."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def sha256_json(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class Criterion:
    """One machine-checkable acceptance condition.

    ``kind`` selects a verifier in ``handoff.criteria``. A job is paid only when
    every criterion passes; the point of the format is that the condition is
    agreed *before* the money moves, so "did the work" is not a matter of taste.
    """

    kind: str
    params: dict = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "params": dict(self.params), "note": self.note}


@dataclass(frozen=True)
class Task:
    """The thing being bought: a brief plus acceptance criteria."""

    id: str
    title: str
    brief: str
    criteria: tuple[Criterion, ...]
    budget_yocto: int
    deadline_s: int = 3600

    @property
    def terms_hash(self) -> str:
        """Hash of the terms, published before funding — the contract stores it."""
        return sha256_json(
            {
                "id": self.id,
                "title": self.title,
                "brief": self.brief,
                "criteria": [c.to_dict() for c in self.criteria],
                "budget": self.budget_yocto,
                "deadline_s": self.deadline_s,
            }
        )


@dataclass(frozen=True)
class Bid:
    worker: str
    price_yocto: int
    reputation: int  # 0-100, earned from settled jobs
    note: str = ""


@dataclass
class Delivery:
    job_id: str
    worker: str
    artifact: str  # path, relative to the job workspace
    artifact_sha256: str
    exit_code: int
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def evidence_hash(self) -> str:
        return sha256_json(self.to_dict())


@dataclass
class Job:
    """A funded unit of work. ``state`` is owned by Escrow, not by the job."""

    task: Task
    buyer: str
    worker: str | None = None
    price_yocto: int = 0
    proof_hash: str = ""
    escrow_id: str = ""

    def to_dict(self) -> dict:
        return {
            "escrow_id": self.escrow_id,
            "buyer": self.buyer,
            "worker": self.worker,
            "price_yocto": self.price_yocto,
            "terms_hash": self.task.terms_hash,
            "proof_hash": self.proof_hash,
            "task": {
                "id": self.task.id,
                "title": self.task.title,
                "criteria": [c.to_dict() for c in self.task.criteria],
                "budget_yocto": self.task.budget_yocto,
            },
        }
