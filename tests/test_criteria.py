"""Criteria are the payment condition, so their failure mode matters more than their success."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from handoff.criteria import verify
from handoff.model import Criterion, Delivery, sha256_file


def delivery(ws: Path, artifact: str = "summary.md") -> Delivery:
    p = ws / artifact
    return Delivery(
        job_id="job-1",
        worker="scribe.testnet",
        artifact=artifact,
        artifact_sha256=sha256_file(p) if p.exists() else "",
        exit_code=0,
    )


class TestCriteria(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        (self.ws / "summary.md").write_text("Three lines.\nAll true.\nDone.\n")
        (self.ws / "meta.json").write_text(json.dumps({"total": "ZAR 6229.55", "vendor": "KOS"}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_passing_set(self):
        crit = [
            Criterion("file_exists", {"path": "summary.md", "min_bytes": 10}),
            Criterion("json_keys", {"path": "meta.json", "keys": ["total", "vendor"]}),
            Criterion("words_at_most", {"path": "summary.md", "max": 50}),
            Criterion("matches", {"path": "meta.json", "pattern": "6229\\.55"}),
        ]
        v = verify(delivery(self.ws), crit, self.ws)
        self.assertTrue(v.passed, v.summary())
        self.assertEqual(len(v.checks), 4)

    def test_one_failure_fails_the_verdict_and_is_named(self):
        crit = [
            Criterion("file_exists", {"path": "summary.md"}),
            Criterion("matches", {"path": "meta.json", "pattern": "9999\\.99"}),
        ]
        v = verify(delivery(self.ws), crit, self.ws)
        self.assertFalse(v.passed)
        self.assertEqual([c.kind for c in v.failures], ["matches"])
        self.assertIn("matches", v.summary())

    def test_unknown_kind_fails_closed(self):
        v = verify(delivery(self.ws), [Criterion("vibes_are_good", {})], self.ws)
        self.assertFalse(v.passed)
        self.assertIn("unknown criterion", v.checks[0].detail)

    def test_path_traversal_is_refused_not_followed(self):
        v = verify(delivery(self.ws), [Criterion("file_exists", {"path": "../../etc/passwd"})], self.ws)
        self.assertFalse(v.passed)
        self.assertIn("escapes workspace", v.checks[0].detail)

    def test_artifact_hash_must_match(self):
        d = delivery(self.ws)
        good = verify(d, [Criterion("artifact_sha256", {"sha256": d.artifact_sha256})], self.ws)
        bad = verify(d, [Criterion("artifact_sha256", {"sha256": "0" * 64})], self.ws)
        self.assertTrue(good.passed)
        self.assertFalse(bad.passed)

    def test_command_must_be_a_list(self):
        v = verify(delivery(self.ws), [Criterion("command_exit_zero", {"cmd": "rm -rf /"})], self.ws)
        self.assertFalse(v.passed)
        self.assertIn("verifier error", v.checks[0].detail)

    def test_failing_command_is_a_failure_not_a_crash(self):
        v = verify(delivery(self.ws), [Criterion("command_exit_zero", {"cmd": ["false"]})], self.ws)
        self.assertFalse(v.passed)

    def test_pass_is_independent_of_criterion_order(self):
        crit = [
            Criterion("matches", {"path": "meta.json", "pattern": "KOS"}),
            Criterion("file_exists", {"path": "summary.md"}),
        ]
        v1 = verify(delivery(self.ws), crit, self.ws)
        v2 = verify(delivery(self.ws), list(reversed(crit)), self.ws)
        self.assertEqual(v1.passed, v2.passed)
        self.assertEqual(sorted(c.kind for c in v1.checks), sorted(c.kind for c in v2.checks))


if __name__ == "__main__":
    unittest.main()
