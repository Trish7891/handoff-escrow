"""The ledger's one promise: any edit to the past is visible from the present."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from handoff.ledger import GENESIS, Ledger, LedgerError


def build() -> Ledger:
    led = Ledger(clock=lambda: 1_700_000_000.0)
    led.append("job.posted", job="job-1", buyer="buyer.testnet", budget_yocto=10)
    led.append("wallet.debit", account="buyer.testnet", amount_yocto=10, reason="fund")
    led.append("escrow.event", escrow_id="job-1", event="fund", from_state="OPEN", to_state="FUNDED")
    return led


class TestLedger(unittest.TestCase):
    def test_chain_verifies(self):
        led = build()
        ok, at = led.verify()
        self.assertTrue(ok)
        self.assertIsNone(at)
        self.assertEqual(led.entries[0].prev, GENESIS)

    def test_links_are_hashes_of_the_previous_entry(self):
        led = build()
        for prev, cur in zip(led.entries, led.entries[1:]):
            self.assertEqual(cur.prev, prev.hash)

    def test_edited_amount_breaks_at_that_entry(self):
        led = build()
        led.entries[1].payload["amount_yocto"] = 999
        ok, at = led.verify()
        self.assertFalse(ok)
        self.assertEqual(at, led.entries[1].seq)

    def test_removed_entry_breaks_the_next_link(self):
        led = build()
        del led.entries[1]
        ok, at = led.verify()
        self.assertFalse(ok)
        self.assertEqual(at, 1)  # the position that no longer holds the entry it should

    def test_reordered_entries_break(self):
        led = build()
        led.entries[1], led.entries[2] = led.entries[2], led.entries[1]
        ok, _ = led.verify()
        self.assertFalse(ok)

    def test_saved_and_loaded_is_identical(self):
        led = build()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ledger.json"
            led.save(p)
            again = Ledger.load(p)
        self.assertEqual(again.head, led.head)
        self.assertTrue(again.verify()[0])
        self.assertEqual(json.dumps(again.to_dict(), sort_keys=True), json.dumps(led.to_dict(), sort_keys=True))

    def test_missing_file_is_a_ledger_error(self):
        with self.assertRaises(LedgerError):
            Ledger.load("/nonexistent/ledger.json")


if __name__ == "__main__":
    unittest.main()
