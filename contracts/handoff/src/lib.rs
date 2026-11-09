//! One contract instance holds one job.
//!
//! The transition table below is the same table as `handoff/escrow.py`; a Python
//! test parses this file and fails if the two disagree. Deploying a contract per
//! job keeps the attack surface small (no maps, no iteration, no storage
//! management) and makes the buyer's terms a property of the account that holds
//! the money rather than a row in someone else's database.

use near_sdk::{env, near, require, AccountId, NearToken, PanicOnDefault, Promise};

const FEE_CAP_BPS: u16 = 500; // a fee above 5% is a bug, not a business model

/// (state, event) -> next state. Mirrored by handoff/escrow.py:TRANSITIONS.
pub const TRANSITIONS: &[(&str, &str, &str)] = &[
    ("OPEN", "fund", "FUNDED"),
    ("FUNDED", "assign", "ASSIGNED"),
    ("FUNDED", "refund", "REFUNDED"),
    ("FUNDED", "expire", "REFUNDED"),
    ("ASSIGNED", "submit", "DELIVERED"),
    ("ASSIGNED", "expire", "REFUNDED"),
    ("DELIVERED", "release", "RELEASED"),
    ("DELIVERED", "refund", "REFUNDED"),
    ("DELIVERED", "dispute", "DISPUTED"),
    ("DISPUTED", "resolve", "RESOLVED"),
    ("DISPUTED", "refund", "REFUNDED"),
];

pub fn next_state(state: &str, event: &str) -> Option<&'static str> {
    TRANSITIONS
        .iter()
        .find(|(s, e, _)| *s == state && *e == event)
        .map(|(_, _, n)| *n)
}

#[near(serializers = [json, borsh])]
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Settlement {
    pub to: AccountId,
    pub amount_yocto: u128,
    pub fee_yocto: u128,
    pub refund_yocto: u128,
    pub to_worker_bps: u16,
}

#[near(serializers = [json])]
#[derive(Clone, Debug)]
pub struct JobView {
    pub buyer: AccountId,
    pub arbiter: AccountId,
    pub worker: Option<AccountId>,
    pub state: String,
    pub budget_yocto: u128,
    pub price_yocto: u128,
    pub terms_hash: String,
    pub proof_hash: String,
    pub deadline_ns: u64,
    pub fee_bps: u16,
    pub settlement: Option<Settlement>,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Contract {
    buyer: AccountId,
    arbiter: AccountId,
    worker: Option<AccountId>,
    state: String,
    budget_yocto: u128,
    price_yocto: u128,
    terms_hash: String,
    proof_hash: String,
    deadline_ns: u64,
    fee_bps: u16,
    settlement: Option<Settlement>,
}

#[near]
impl Contract {
    /// The buyer deploys the job and names the arbiter and the treasury fee.
    #[init]
    pub fn new(buyer: AccountId, arbiter: AccountId, budget_yocto: u128, fee_bps: u16) -> Self {
        require!(fee_bps <= FEE_CAP_BPS, "fee above cap");
        Self {
            buyer,
            arbiter,
            worker: None,
            state: "OPEN".to_string(),
            budget_yocto,
            price_yocto: budget_yocto,
            terms_hash: String::new(),
            proof_hash: String::new(),
            deadline_ns: 0,
            fee_bps,
            settlement: None,
        }
    }

    /// Fund exactly the advertised budget. The terms hash locks the brief.
    #[payable]
    pub fn fund(&mut self, terms_hash: String, deadline_ns: u64) {
        self.only(self.buyer.clone(), "fund");
        require!(
            env::attached_deposit() == NearToken::from_yoctonear(self.budget_yocto),
            "attach exactly the budget"
        );
        require!(deadline_ns > env::block_timestamp(), "deadline in the past");
        self.terms_hash = terms_hash;
        self.deadline_ns = deadline_ns;
        self.go("fund");
    }

    /// Pick a worker at a price at or below budget; the difference goes back at once.
    pub fn assign(&mut self, worker: AccountId, price_yocto: u128) {
        self.only(self.buyer.clone(), "assign");
        require!(price_yocto <= self.budget_yocto, "price above budget");
        require!(price_yocto > 0, "price must be positive");
        self.worker = Some(worker.clone());
        self.price_yocto = price_yocto;
        self.go("assign");
        let change = self.budget_yocto - price_yocto;
        if change > 0 {
            let _ = Promise::new(self.buyer.clone()).transfer(NearToken::from_yoctonear(change));
        }
    }

    /// The worker's only move: publish the hash of what it delivered.
    pub fn submit(&mut self, evidence_hash: String) {
        self.require_legal("submit");
        let worker = self.worker.clone().expect("no worker");
        self.only(worker, "submit");
        require!(!evidence_hash.is_empty(), "empty evidence hash");
        self.proof_hash = evidence_hash;
        self.go("submit");
    }

    /// The buyer releases. The worker is paid the fee net; the fee goes to the arbiter's
    /// account only if the arbiter is also the treasury — deploy with `treasury.near` for
    /// a real fee split, or fee_bps = 0 for a pure two-party escrow.
    pub fn release(&mut self) {
        self.only(self.buyer.clone(), "release");
        let worker = self.worker.clone().expect("no worker");
        let fee = self.fee_on(self.price_yocto);
        let net = self.price_yocto - fee;
        self.settlement = Some(Settlement {
            to: worker.clone(),
            amount_yocto: net,
            fee_yocto: fee,
            refund_yocto: 0,
            to_worker_bps: 10_000,
        });
        self.go("release");
        let _ = Promise::new(worker).transfer(NearToken::from_yoctonear(net));
        if fee > 0 {
            let _ = Promise::new(self.arbiter.clone()).transfer(NearToken::from_yoctonear(fee));
        }
    }

    /// Buyer cancels; legal while funded, assigned, or delivered-but-contested.
    pub fn refund(&mut self) {
        self.only(self.buyer.clone(), "refund");
        self.settlement = Some(Settlement {
            to: self.buyer.clone(),
            amount_yocto: self.price_yocto,
            fee_yocto: 0,
            refund_yocto: self.price_yocto,
            to_worker_bps: 0,
        });
        self.go("refund");
        let _ = Promise::new(self.buyer.clone()).transfer(NearToken::from_yoctonear(self.price_yocto));
    }

    /// Buyer refuses to judge alone.
    pub fn dispute(&mut self) {
        self.only(self.buyer.clone(), "dispute");
        self.go("dispute");
    }

    /// The arbiter splits the escrowed price. Fee is charged on the worker's share only.
    pub fn resolve(&mut self, to_worker_bps: u16) {
        self.only(self.arbiter.clone(), "resolve");
        require!(to_worker_bps <= 10_000, "bps above 100%");
        let worker = self.worker.clone().expect("no worker");
        let to_worker = self.price_yocto * (to_worker_bps as u128) / 10_000;
        let fee = self.fee_on(to_worker);
        let net = to_worker - fee;
        let back = self.price_yocto - to_worker;
        self.settlement = Some(Settlement {
            to: worker.clone(),
            amount_yocto: net,
            fee_yocto: fee,
            refund_yocto: back,
            to_worker_bps,
        });
        self.go("resolve");
        if net > 0 {
            let _ = Promise::new(worker).transfer(NearToken::from_yoctonear(net));
        }
        if fee > 0 {
            let _ = Promise::new(self.arbiter.clone()).transfer(NearToken::from_yoctonear(fee));
        }
        if back > 0 {
            let _ = Promise::new(self.buyer.clone()).transfer(NearToken::from_yoctonear(back));
        }
    }

    /// Anyone may expire a stale job, but only after its deadline has passed.
    pub fn expire(&mut self) {
        require!(
            env::block_timestamp() >= self.deadline_ns && self.deadline_ns > 0,
            "deadline not reached"
        );
        self.settlement = Some(Settlement {
            to: self.buyer.clone(),
            amount_yocto: self.price_yocto,
            fee_yocto: 0,
            refund_yocto: self.price_yocto,
            to_worker_bps: 0,
        });
        self.go("expire");
        let _ = Promise::new(self.buyer.clone()).transfer(NearToken::from_yoctonear(self.price_yocto));
    }

    // -- views ------------------------------------------------------------
    pub fn get_job(&self) -> JobView {
        JobView {
            buyer: self.buyer.clone(),
            arbiter: self.arbiter.clone(),
            worker: self.worker.clone(),
            state: self.state.clone(),
            budget_yocto: self.budget_yocto,
            price_yocto: self.price_yocto,
            terms_hash: self.terms_hash.clone(),
            proof_hash: self.proof_hash.clone(),
            deadline_ns: self.deadline_ns,
            fee_bps: self.fee_bps,
            settlement: self.settlement.clone(),
        }
    }

    pub fn allowed(&self, event: String) -> bool {
        next_state(&self.state, &event).is_some()
    }

    // -- internals --------------------------------------------------------
    fn fee_on(&self, amount: u128) -> u128 {
        amount * (self.fee_bps as u128) / 10_000
    }

    fn require_legal(&self, event: &str) {
        require!(
            next_state(&self.state, event).is_some(),
            format!("{event} is not legal in {}", self.state)
        );
    }

    fn only(&self, who: AccountId, event: &str) {
        require!(
            env::predecessor_account_id() == who,
            format!("{event}: not your call")
        );
    }

    fn go(&mut self, event: &str) {
        let next = next_state(&self.state, event).unwrap_or_else(|| {
            env::panic_str(&format!("{event} is not legal in {}", self.state))
        });
        env::log_str(&format!("{} --{}--> {}", self.state, event, next));
        self.state = next.to_string();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::testing_env;

    fn buyer() -> AccountId {
        "buyer.testnet".parse().unwrap()
    }
    fn worker() -> AccountId {
        "scribe.testnet".parse().unwrap()
    }
    fn arbiter() -> AccountId {
        "arbiter.testnet".parse().unwrap()
    }
    const BUDGET: u128 = 10_000_000_000_000_000_000_000_000; // 10 NEAR

    fn ctx(who: &AccountId, deposit: u128, now: u64) -> VMContextBuilder {
        let mut b = VMContextBuilder::new();
        b.predecessor_account_id(who.clone())
            .attached_deposit(NearToken::from_yoctonear(deposit))
            .block_timestamp(now);
        b
    }

    fn deployed() -> Contract {
        testing_env!(ctx(&buyer(), 0, 1_000).build());
        Contract::new(buyer(), arbiter(), BUDGET, 50)
    }

    fn funded() -> Contract {
        let mut c = deployed();
        testing_env!(ctx(&buyer(), BUDGET, 1_000).build());
        c.fund("terms-hash".to_string(), 10_000);
        c
    }

    fn assigned() -> Contract {
        let mut c = funded();
        testing_env!(ctx(&buyer(), 0, 2_000).build());
        c.assign(worker(), BUDGET * 6 / 10);
        c
    }

    #[test]
    fn table_matches_python_contract() {
        assert_eq!(next_state("OPEN", "fund"), Some("FUNDED"));
        assert_eq!(next_state("RELEASED", "refund"), None);
        assert_eq!(TRANSITIONS.len(), 11);
    }

    #[test]
    fn happy_path_pays_worker_net_of_fee() {
        let mut c = assigned();
        testing_env!(ctx(&worker(), 0, 3_000).build());
        c.submit("evidence".to_string());
        assert_eq!(c.get_job().state, "DELIVERED");

        testing_env!(ctx(&buyer(), 0, 4_000).build());
        c.release();
        let job = c.get_job();
        assert_eq!(job.state, "RELEASED");
        let s = job.settlement.unwrap();
        assert_eq!(s.amount_yocto + s.fee_yocto, job.price_yocto);
        assert_eq!(s.fee_yocto, job.price_yocto * 50 / 10_000);
    }

    #[test]
    #[should_panic(expected = "not your call")]
    fn worker_cannot_release() {
        let mut c = assigned();
        testing_env!(ctx(&worker(), 0, 3_000).build());
        c.submit("evidence".to_string());
        c.release();
    }

    #[test]
    #[should_panic(expected = "not legal in FUNDED")]
    fn cannot_submit_before_assignment() {
        let mut c = funded();
        testing_env!(ctx(&worker(), 0, 2_000).build());
        c.submit("evidence".to_string());
    }

    #[test]
    #[should_panic(expected = "attach exactly the budget")]
    fn fund_requires_exact_deposit() {
        let mut c = deployed();
        testing_env!(ctx(&buyer(), BUDGET / 2, 1_000).build());
        c.fund("terms".to_string(), 10_000);
    }

    #[test]
    fn arbiter_split_is_proportional() {
        let mut c = assigned();
        testing_env!(ctx(&worker(), 0, 3_000).build());
        c.submit("evidence".to_string());
        testing_env!(ctx(&buyer(), 0, 4_000).build());
        c.dispute();

        testing_env!(ctx(&arbiter(), 0, 5_000).build());
        c.resolve(7_500);
        let job = c.get_job();
        assert_eq!(job.state, "RESOLVED");
        let s = job.settlement.unwrap();
        assert_eq!(s.amount_yocto + s.fee_yocto, job.price_yocto * 7_500 / 10_000);
        assert_eq!(s.refund_yocto, job.price_yocto - job.price_yocto * 7_500 / 10_000);
    }

    #[test]
    fn expire_only_after_deadline() {
        let mut c = funded();
        testing_env!(ctx(&buyer(), 0, 2_000).build());
        c.assign(worker(), BUDGET);
        testing_env!(ctx(&arbiter(), 0, 9_999).build());
        let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| c.expire()));
        assert!(r.is_err(), "expire must fail before the deadline");
    }
}
