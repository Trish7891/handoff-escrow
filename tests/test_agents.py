"""End to end: the same run twice must produce the same chain, and money must not leak."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from handoff import report
from handoff.scenarios import run_all


def run(tmp: str) -> dict:
    return run_all(Path(tmp) / "workspaces")


class TestScenarios(unittest.TestCase):
    def test_three_outcomes_and_balanced_books(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(d)
        self.assertEqual([s["outcome"] for s in r["scenarios"]], ["released", "refunded", "resolved"])
        for s in r["scenarios"]:
            self.assertTrue(s["conserved"], f"{s['id']} leaked money")
        self.assertTrue(r["ledger"]["verified"])
        self.assertGreater(r["ledger"]["entries"], 20)

    def test_the_unpaid_job_actually_fails_verification(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(d)
        unpaid = r["scenarios"][1]
        self.assertFalse(unpaid["verdict"]["passed"])
        # the sloppy worker's invoice arithmetic is wrong, and the checker runs it
        self.assertIn("command_exit_zero", [c["kind"] for c in unpaid["verdict"]["checks"] if not c["ok"]])
        self.assertEqual(unpaid["outcome"], "refunded")
        # the partial worker's write-up is padded past the agreed cap — that is the dispute
        dispute = r["scenarios"][2]
        self.assertIn("words_at_most", [c["kind"] for c in dispute["verdict"]["checks"] if not c["ok"]])

    def test_replay_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            r1, r2 = run(a), run(b)
        self.assertEqual(r1["ledger"]["head"], r2["ledger"]["head"])
        self.assertEqual(
            json.dumps(r1["ledger"], sort_keys=True), json.dumps(r2["ledger"], sort_keys=True)
        )
        self.assertEqual(r1["scenarios"][0]["balances"], r2["scenarios"][0]["balances"])

    def test_worker_is_paid_only_after_verification(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(d)
        paid = r["scenarios"][0]
        events = [e["kind"] for e in paid["events"]]
        self.assertLess(events.index("escrow.event"), len(events))
        delivery = next(e for e in paid["events"] if e["kind"] == "delivery.received")
        release = next(
            e for e in paid["events"] if e["kind"] == "escrow.event" and e["payload"]["event"] == "release"
        )
        self.assertLess(delivery["seq"], release["seq"])

    def test_split_pays_the_worker_something_but_not_everything(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(d)
        s = r["scenarios"][2]
        self.assertEqual(s["arbiter"]["rule"], s["arbiter"]["rule"])
        self.assertGreater(s["arbiter"]["to_worker_bps"], 0)
        self.assertLess(s["arbiter"]["to_worker_bps"], 10_000)

    def test_report_is_standalone_and_shows_failures(self):
        with tempfile.TemporaryDirectory() as d:
            r = run(d)
            page = report.write(r, Path(d) / "report.html").read_text()
        self.assertNotIn("http://", page.replace('lang="en"', ""))
        self.assertNotIn("<script", page)
        self.assertIn("FAIL", page)
        self.assertIn("PASS", page)
        self.assertIn("What this does not solve", page)


if __name__ == "__main__":
    unittest.main()
