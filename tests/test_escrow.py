"""The state machine: who may move, what it costs, and what cannot be undone."""

from __future__ import annotations

import unittest

from handoff.escrow import (
    ASSIGNED,
    DELIVERED,
    DISPUTED,
    FEE_BPS,
    FUNDED,
    OPEN,
    REFUNDED,
    RELEASED,
    RESOLVED,
    TERMINAL,
    Escrow,
    IllegalTransition,
    fee_on,
)

NEAR = 10**24


def fresh() -> Escrow:
    return Escrow(escrow_id="job-1", buyer="buyer.testnet", arbiter="arbiter.testnet", amount_yocto=10 * NEAR)


class TestStateMachine(unittest.TestCase):
    def test_happy_path_reaches_released(self):
        e = fresh()
        e.apply("fund", "buyer.testnet", 1, terms_hash="terms")
        e.apply("assign", "buyer.testnet", 2, worker="scribe.testnet", price_yocto=6 * NEAR)
        e.apply("submit", "scribe.testnet", 3, proof_hash="proof")
        e.apply("release", "buyer.testnet", 4)
        self.assertEqual(e.state, RELEASED)
        self.assertIn(e.state, TERMINAL)

    def test_worker_cannot_take_the_money(self):
        e = fresh()
        e.apply("fund", "buyer.testnet", 1)
        e.apply("assign", "buyer.testnet", 2, worker="scribe.testnet")
        e.apply("submit", "scribe.testnet", 3, proof_hash="p")
        with self.assertRaises(IllegalTransition):
            e.apply("release", "scribe.testnet", 4)
        self.assertEqual(e.state, DELIVERED)

    def test_stranger_cannot_submit(self):
        e = fresh()
        e.apply("fund", "buyer.testnet", 1)
        e.apply("assign", "buyer.testnet", 2, worker="scribe.testnet")
        with self.assertRaises(IllegalTransition):
            e.apply("submit", "other.testnet", 3, proof_hash="p")

    def test_cannot_skip_the_delivery(self):
        e = fresh()
        e.apply("fund", "buyer.testnet", 1)
        e.apply("assign", "buyer.testnet", 2, worker="scribe.testnet")
        with self.assertRaises(IllegalTransition):
            e.apply("release", "buyer.testnet", 3)

    def test_release_pays_price_minus_fee(self):
        e = fresh()
        e.apply("fund", "buyer.testnet", 1)
        e.apply("assign", "buyer.testnet", 2, worker="scribe.testnet", price_yocto=6 * NEAR)
        e.apply("submit", "scribe.testnet", 3, proof_hash="p")
        e.apply("release", "buyer.testnet", 4)
        self.assertEqual(e.settlement["amount_yocto"], 6 * NEAR - fee_on(6 * NEAR))
        self.assertEqual(e.settlement["fee_yocto"], 6 * NEAR * FEE_BPS // 10_000)
        self.assertEqual(e.settlement["amount_yocto"] + e.settlement["fee_yocto"], 6 * NEAR)

    def test_refund_returns_everything_and_charges_nothing(self):
        e = fresh()
        e.apply("fund", "buyer.testnet", 1)
        e.apply("refund", "buyer.testnet", 2)
        self.assertEqual(e.state, REFUNDED)
        self.assertEqual(e.settlement["amount_yocto"], 10 * NEAR)
        self.assertEqual(e.settlement["fee_yocto"], 0)

    def test_arbiter_split_conserves_the_escrow(self):
        e = fresh()
        e.apply("fund", "buyer.testnet", 1)
        e.apply("assign", "buyer.testnet", 2, worker="scribe.testnet", price_yocto=6 * NEAR)
        e.apply("submit", "scribe.testnet", 3, proof_hash="p")
        e.apply("dispute", "buyer.testnet", 4)
        e.apply("resolve", "arbiter.testnet", 5, to_worker_bps=7500)
        s = e.settlement
        self.assertEqual(e.state, RESOLVED)
        self.assertEqual(s["amount_yocto"] + s["fee_yocto"] + s["refund_yocto"], 6 * NEAR)
        self.assertEqual(s["to_worker_bps"], 7500)

    def test_dispute_is_the_buyers_move_only(self):
        e = fresh()
        e.apply("fund", "buyer.testnet", 1)
        e.apply("assign", "buyer.testnet", 2, worker="scribe.testnet")
        e.apply("submit", "scribe.testnet", 3, proof_hash="p")
        with self.assertRaises(IllegalTransition):
            e.apply("dispute", "scribe.testnet", 4)

    def test_terminal_states_do_not_move(self):
        e = fresh()
        e.apply("fund", "buyer.testnet", 1)
        e.apply("refund", "buyer.testnet", 2)
        for event in ("fund", "assign", "submit", "release", "dispute", "resolve", "expire"):
            with self.assertRaises(IllegalTransition, msg=event):
                e.apply(event, "buyer.testnet", 3, worker="scribe.testnet")

    def test_expire_refunds_but_only_from_a_funded_or_assigned_job(self):
        e = fresh()
        with self.assertRaises(IllegalTransition):
            e.apply("expire", "anyone", 1)
        e.apply("fund", "buyer.testnet", 2)
        e.apply("expire", "anyone", 3)
        self.assertEqual(e.state, REFUNDED)

    def test_fee_is_zero_for_tiny_amounts_and_never_negative(self):
        self.assertEqual(fee_on(0), 0)
        self.assertEqual(fee_on(1), 0)
        self.assertGreaterEqual(fee_on(NEAR), 0)

    def test_illegal_event_names_do_not_mutate(self):
        e = fresh()
        with self.assertRaises(IllegalTransition):
            e.apply("teleport", "buyer.testnet", 1)
        self.assertEqual(e.state, OPEN)


if __name__ == "__main__":
    unittest.main()
