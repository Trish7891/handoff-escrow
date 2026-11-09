"""An append-only, hash-chained record of every event that moved money or proof.

Why chain the hashes instead of just appending JSON lines: a buyer can rewrite
their own log. A buyer who wants to claim "the worker was never paid" has to
rewrite every later entry and still match the hash the worker published at
delivery time. The chain does not stop lying; it makes lying detectable by any
third party holding one later hash — which is what the worker posts on X or
hands to the arbiter.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

GENESIS = "0" * 64


class LedgerError(Exception):
    pass


def _hash_entry(seq: int, ts: float, kind: str, payload: dict, prev: str) -> str:
    body = json.dumps(
        {"seq": seq, "ts": round(ts, 6), "kind": kind, "payload": payload, "prev": prev},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(body).hexdigest()


@dataclass
class Entry:
    seq: int
    ts: float
    kind: str
    payload: dict
    prev: str
    hash: str

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "kind": self.kind,
            "payload": self.payload,
            "prev": self.prev,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Entry":
        return cls(
            seq=int(d["seq"]),
            ts=float(d["ts"]),
            kind=str(d["kind"]),
            payload=dict(d["payload"]),
            prev=str(d["prev"]),
            hash=str(d["hash"]),
        )


class Ledger:
    """Deterministic: pass ``clock`` to make timestamps reproducible in tests."""

    def __init__(self, clock=None):
        self.entries: list[Entry] = []
        self._clock = clock or time.time
        self._started = self._clock()

    # -- writing -----------------------------------------------------------
    def append(self, kind: str, **payload) -> Entry:
        prev = self.entries[-1].hash if self.entries else GENESIS
        seq = len(self.entries)
        ts = self._clock()
        h = _hash_entry(seq, ts, kind, payload, prev)
        e = Entry(seq=seq, ts=ts, kind=kind, payload=payload, prev=prev, hash=h)
        self.entries.append(e)
        return e

    # -- reading -----------------------------------------------------------
    @property
    def head(self) -> str:
        return self.entries[-1].hash if self.entries else GENESIS

    def of_kind(self, kind: str) -> list[Entry]:
        return [e for e in self.entries if e.kind == kind]

    def verify(self) -> tuple[bool, int | None]:
        """Recompute every hash from genesis. Returns (ok, first_bad_seq)."""
        prev = GENESIS
        for i, e in enumerate(self.entries):
            if e.seq != i:
                return False, i
            if e.prev != prev:
                return False, i
            if _hash_entry(e.seq, e.ts, e.kind, e.payload, e.prev) != e.hash:
                return False, i
            prev = e.hash
        return True, None

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "head": self.head,
            "entries": [e.to_dict() for e in self.entries],
        }

    def save(self, path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def load(cls, path) -> "Ledger":
        try:
            doc = json.loads(Path(path).read_text())
        except OSError as exc:
            raise LedgerError(f"cannot read ledger: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LedgerError(f"ledger is not json: {exc}") from exc
        led = cls()
        led.entries = [Entry.from_dict(d) for d in doc["entries"]]
        ok, bad = led.verify()
        if not ok:
            raise LedgerError(f"ledger broken at entry {bad}")
        return led
