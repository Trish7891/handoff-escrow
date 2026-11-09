"""The Python engine and the Rust contract must not drift apart.

The demo runs on `handoff/escrow.py`; the chain runs on `contracts/handoff/src/lib.rs`.
If those two disagree about which event is legal in which state, then "RELEASED"
means one thing to the buyer's laptop and another to the money. So this test reads
the Rust source as text and compares the tables.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from handoff.escrow import AUTHORITY, FEE_BPS, STATES, TRANSITIONS

RS = Path(__file__).resolve().parent.parent / "contracts" / "handoff" / "src" / "lib.rs"


def rust_table() -> set[tuple[str, str, str]]:
    src = RS.read_text()
    block = src.split("pub const TRANSITIONS", 1)[1].split("];", 1)[0]
    return {(s, e, n) for s, e, n in re.findall(r'\("([A-Z]+)",\s*"([a-z]+)",\s*"([A-Z]+)"\)', block)}


class TestParity(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RS.exists(), f"missing contract at {RS}")
        self.rust = rust_table()
        self.python = {(s, e, n) for (s, e), n in TRANSITIONS.items()}

    def test_same_transitions(self):
        self.assertEqual(
            sorted(self.rust - self.python), [], "in the Rust contract but not in escrow.py"
        )
        self.assertEqual(
            sorted(self.python - self.rust), [], "in escrow.py but not in the Rust contract"
        )

    def test_same_events_have_an_authority(self):
        events = {e for _, e, _ in self.rust}
        self.assertEqual(events - set(AUTHORITY), set(), "event with no authority rule")

    def test_same_states(self):
        src = RS.read_text()
        used = set(re.findall(r'"([A-Z]+)"', src.split("pub const TRANSITIONS", 1)[1].split("];", 1)[0]))
        self.assertEqual(used, set(STATES))

    def test_terminal_states_are_terminal(self):
        for state in ("RELEASED", "REFUNDED", "RESOLVED"):
            self.assertEqual(
                [t for t in self.rust if t[0] == state], [], f"{state} must have no exits"
            )

    def test_fee_fits_the_contract_cap(self):
        m = re.search(r"FEE_CAP_BPS: u16 = (\d+)", RS.read_text())
        assert m is not None, "contract lost FEE_CAP_BPS"
        cap = int(m.group(1))
        self.assertLessEqual(FEE_BPS, cap)


if __name__ == "__main__":
    unittest.main()
