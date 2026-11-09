"""Handoff — escrow and proof-of-work settlement for agent labour.

The package has three parts:

* ``ledger``  — a hash-chained, replayable record of every money and proof event.
* ``escrow``  — the job state machine, mirrored one-to-one by the NEAR contract
                in ``contracts/handoff``.
* ``agents``  — a buyer, workers and an arbiter that actually run the loop.

Nothing here needs a network, a key or a chain to run. The chain is where the
money would live; the ledger is how anyone re-checks that the money was earned.
"""

from .model import YOCTO, Bid, Delivery, Job, Task
from .ledger import Ledger, LedgerError
from .escrow import Escrow, IllegalTransition, STATES, TRANSITIONS
from .criteria import Verdict, verify

__all__ = [
    "YOCTO",
    "Bid",
    "Delivery",
    "Job",
    "Task",
    "Ledger",
    "LedgerError",
    "Escrow",
    "IllegalTransition",
    "STATES",
    "TRANSITIONS",
    "Verdict",
    "verify",
]
__version__ = "0.1.0"
