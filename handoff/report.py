"""Renders the run as one standalone HTML file — no CDN, no JS, no fonts to fetch.

The report is the thing a judge or a buyer actually opens, so it has to be
readable offline and it has to show the failures as plainly as the successes.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

CSS = """
:root{--bg:#0b0d10;--panel:#12161c;--line:#232a34;--ink:#e8edf4;--dim:#8b97a8;
--ok:#6ee7a8;--bad:#ff7b72;--warn:#f5c26b;--accent:#8ab4ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:48px 24px 80px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:24px;flex-wrap:wrap;
border-bottom:1px solid var(--line);padding-bottom:28px}
h1{font-size:40px;letter-spacing:-.03em;margin:0;font-weight:650}
h1 span{color:var(--dim);font-weight:400}
.tag{color:var(--dim);margin:8px 0 0;max-width:46ch}
.pill{display:inline-flex;gap:8px;align-items:center;border:1px solid var(--line);
border-radius:999px;padding:7px 14px;font:12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px rgba(110,231,168,.12)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1px;background:var(--line);
border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:28px 0 44px}
.stat{background:var(--panel);padding:16px 18px}
.stat b{display:block;font-size:24px;letter-spacing:-.02em}
.stat small{color:var(--dim);font:11px/1.4 ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--dim);margin:44px 0 14px;font-weight:600}
.loop{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
@media(max-width:820px){.loop{grid-template-columns:1fr 1fr}}
.step{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.step i{font-style:normal;color:var(--accent);font:11px ui-monospace,monospace}
.step b{display:block;margin:6px 0 4px;font-size:14px}
.step p{margin:0;color:var(--dim);font-size:12.5px;line-height:1.45}
.scenario{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px;margin:18px 0}
.sc-head{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.sc-head h3{margin:0;font-size:19px;letter-spacing:-.01em}
.chip{font:11px/1 ui-monospace,monospace;padding:6px 10px;border-radius:6px;border:1px solid var(--line);color:var(--dim)}
.chip.released,.chip.RELEASED{color:var(--ok);border-color:rgba(110,231,168,.35)}
.chip.refunded,.chip.REFUNDED{color:var(--bad);border-color:rgba(255,123,114,.35)}
.chip.resolved,.chip.RESOLVED{color:var(--warn);border-color:rgba(245,194,107,.35)}
.narr{color:#c3ccd9;margin:12px 0 18px;max-width:78ch}
table{width:100%;border-collapse:collapse;font-size:13px;margin:6px 0 14px}
th{text-align:left;color:var(--dim);font:11px ui-monospace,monospace;text-transform:uppercase;
letter-spacing:.07em;padding:6px 10px;border-bottom:1px solid var(--line)}
td{padding:7px 10px;border-bottom:1px solid rgba(35,42,52,.6);vertical-align:top}
td.mono,th.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}
tr:last-child td{border-bottom:0}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.dim{color:var(--dim)}
.checks{display:grid;gap:6px;margin:10px 0 16px}
.check{display:grid;grid-template-columns:18px 150px 1fr;gap:10px;align-items:baseline;
font-size:13px;padding:6px 10px;background:#0e1218;border:1px solid var(--line);border-radius:8px}
@media(max-width:640px){.check{grid-template-columns:18px 1fr}.check .detail{grid-column:2}}
.check .kind{font-family:ui-monospace,monospace;font-size:12px;color:#c3ccd9}
.check .detail{color:var(--dim)}
.tl{max-height:260px;overflow:auto;border:1px solid var(--line);border-radius:10px}
.tl table{margin:0}.tl td{border-bottom:1px solid rgba(35,42,52,.45)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:820px){.two{grid-template-columns:1fr}}
.notes{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:820px){.notes{grid-template-columns:1fr}}
.note{border:1px solid var(--line);border-radius:10px;padding:14px;background:#0e1218}
.note b{display:block;margin-bottom:4px;font-size:13.5px}
.note p{margin:0;color:var(--dim);font-size:13px}
footer{margin-top:52px;padding-top:20px;border-top:1px solid var(--line);color:var(--dim);font-size:12.5px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#0e1218;border:1px solid var(--line);
border-radius:5px;padding:1px 6px;font-size:12px;color:#cfe0ff}
"""

LOOP = [
    ("01", "Terms published", "Buyer hashes the brief and the acceptance criteria. The hash is the contract."),
    ("02", "Escrow funded", "Budget leaves the buyer's balance and is held by the job, not by a person."),
    ("03", "Proof delivered", "Worker submits an artifact plus a hash of the evidence, signed by its key."),
    ("04", "Checked mechanically", "Five criteria run in the job workspace. Unknown checks fail closed."),
    ("05", "Settled or split", "Release, refund, or arbiter split — each an explicit, logged transition."),
]

LIMITS = [
    ("Verification is only as good as the criteria", "A buyer who accepts garbage gets garbage. The format makes the condition explicit; it cannot make it wise."),
    ("The demo's chain is local", "Money movement here is a ledger, not a NEAR account. The Rust contract implements the same table; deploying it is a one-command step once the account exists."),
    ("Reputation is not Sybil-proof", "A worker can farm cheap jobs on new keys. Reputation should be staked — slashed on failed verification — before real value."),
    ("Disputes still need a human or a bonded arbiter", "The arbiter rule here is mechanical, which works for objective criteria and not for taste."),
]


def _t(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def _short(h: str, n: int = 10) -> str:
    return f"{h[:n]}…" if h else "—"


def _checks(verdict: dict) -> str:
    rows = []
    for c in verdict.get("checks", []):
        mark = '<span class="ok">PASS</span>' if c["ok"] else '<span class="bad">FAIL</span>'
        rows.append(
            f'<div class="check"><span>{mark}</span><span class="kind">{html.escape(c["kind"])}</span>'
            f'<span class="detail">{html.escape(c["detail"])}</span></div>'
        )
    return "".join(rows)


def _bids(bids: list[dict], winner: str) -> str:
    rows = []
    for b in bids:
        win = b["worker"] == winner
        rows.append(
            "<tr>"
            f'<td class="mono">{html.escape(b["worker"])}{" ←" if win else ""}</td>'
            f'<td class="mono">{html.escape(b["price"])}</td>'
            f'<td class="mono">{b["reputation"]}</td>'
            f'<td class="dim">{html.escape(b.get("note", ""))}</td>'
            "</tr>"
        )
    return (
        '<table><tr><th>worker</th><th>ask (NEAR)</th><th>rep</th><th></th></tr>'
        + "".join(rows)
        + "</table>"
    )


def _timeline(events: list[dict]) -> str:
    interesting = {"job.posted", "wallet.debit", "escrow.event", "delivery.received", "settlement", "wallet.credit"}
    rows = []
    for e in events:
        if e["kind"] not in interesting:
            continue
        p = e["payload"]
        if e["kind"] == "escrow.event":
            detail = f'{p["from_state"]} → {p["to_state"]} by {p["actor"]}'
        elif e["kind"] == "wallet.debit":
            detail = f'{p["account"]} −{p["amount_yocto"] / 10**24:.6f} NEAR ({p["reason"]})'
        elif e["kind"] == "wallet.credit":
            detail = f'{p["account"]} +{p["amount_yocto"] / 10**24:.6f} NEAR ({p["reason"]})'
        elif e["kind"] == "settlement":
            st = p.get("settlement") or {}
            detail = p["action"] + (f' → {st.get("to")}' if st.get("to") else "")
        elif e["kind"] == "delivery.received":
            detail = f'{_short(p["evidence_hash"], 12)} ({p["artifact"]})'
        else:
            detail = f'{p.get("title", p.get("escrow_id", ""))}'
        rows.append(
            f'<tr><td class="mono dim">{_t(e["ts"])}</td><td class="mono">{e["seq"]:02d}</td>'
            f'<td class="mono">{html.escape(e["kind"])}</td><td class="dim">{html.escape(detail)}</td></tr>'
        )
    return (
        '<div class="tl"><table><tr><th>utc</th><th>#</th><th>event</th><th>detail</th></tr>'
        + "".join(rows)
        + "</table></div>"
    )


def _balances(balances: dict) -> str:
    rows = "".join(
        f'<tr><td class="mono">{html.escape(name)}</td><td class="mono">{v["balance"]}</td>'
        f'<td class="mono">{v["earned"]}</td><td class="mono">{v["spent"]}</td>'
        f'<td class="mono">{v["reputation"]}</td></tr>'
        for name, v in balances.items()
    )
    return (
        '<table><tr><th>account</th><th>balance</th><th>earned</th><th>spent</th><th>rep</th></tr>'
        + rows
        + "</table>"
    )


def render(result: dict) -> str:
    led = result["ledger"]
    scenarios = result["scenarios"]
    jobs = sum(len(s.get("escrow_ids", [])) for s in scenarios)
    chain_ok = led["verified"]
    conserved = all(s["conserved"] for s in scenarios)

    stats = f"""
    <div class="stats">
      <div class="stat"><b>{jobs}</b><small>jobs settled</small></div>
      <div class="stat"><b>{led["entries"]}</b><small>ledger entries</small></div>
      <div class="stat"><b>{led["total_volume"]}</b><small>NEAR moved</small></div>
      <div class="stat"><b class="{'ok' if chain_ok else 'bad'}">{'verified' if chain_ok else 'broken'}</b><small>hash chain</small></div>
      <div class="stat"><b class="{'ok' if conserved else 'bad'}">{'balanced' if conserved else 'mismatch'}</b><small>conservation</small></div>
    </div>"""

    loop = "".join(
        f'<div class="step"><i>{n}</i><b>{html.escape(t)}</b><p>{html.escape(d)}</p></div>' for n, t, d in LOOP
    )

    body = []
    for s in scenarios:
        outcome = s["outcome"].upper()
        extra = ""
        if "arbiter" in s:
            a = s["arbiter"]
            extra = (
                f'<p class="dim">Arbiter rule <code>{html.escape(a["rule"])}</code> → '
                f'<b>{a["to_worker_bps"] / 100:.0f}%</b> to the worker ({html.escape(a["to_worker"])} NEAR).</p>'
            )
        if "second_job" in s:
            j = s["second_job"]
            extra += (
                f'<p class="dim">Second job, funded from the first payout: buyer '
                f'<code>{html.escape(j["buyer"])}</code> hired <code>{html.escape(j["worker"])}</code> '
                f'for {html.escape(j["price"])} NEAR → <span class="ok">{html.escape(j["outcome"].lower())}</span>.</p>'
            )
        body.append(
            f"""
      <section class="scenario">
        <div class="sc-head"><h3>{html.escape(s["label"])}</h3>
          <span class="chip {outcome.lower()}">{outcome}</span></div>
        <p class="narr">{html.escape(s["narrative"])}</p>
        <div class="two">
          <div><h2 style="margin-top:0">Bids</h2>{_bids(s["bids"], s["winner"])}</div>
          <div><h2 style="margin-top:0">Verdict</h2>
            <div class="checks">{_checks(s["verdict"])}</div>{extra}</div>
        </div>
        <h2>Ledger trace</h2>
        {_timeline(s["events"])}
        <h2>Balances after</h2>
        {_balances(s["balances"])}
      </section>"""
        )

    notes = "".join(
        f'<div class="note"><b>{html.escape(t)}</b><p>{html.escape(d)}</p></div>' for t, d in LIMITS
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Handoff — proof-of-work escrow for agent labour</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <div>
    <h1>Handoff <span>/ agent labour market</span></h1>
    <p class="tag">Agents hire agents, deliver an artifact, and get paid when a machine can
    check the work. The payment condition is a hash published before the money moves.</p>
  </div>
  <div>
    <span class="pill"><span class="dot"></span>chain {_short(led["head"], 16)}</span>
    <p class="dim" style="font:11px ui-monospace,monospace;margin:10px 0 0;text-align:right">
    NEAR · track 07 · local run</p>
  </div>
</header>
{stats}
<h2>The loop</h2>
<div class="loop">{loop}</div>
<h2>Runs</h2>
{"".join(body)}
<h2>What this does not solve</h2>
<div class="notes">{notes}</div>
<footer>
Reproduce: <code>make demo</code> · verify the chain: <code>python -m handoff verify artifacts/ledger.json</code><br>
Contract: <code>contracts/handoff</code> (Rust, near-sdk 5) implements the same state table as
<code>handoff/escrow.py</code>; <code>tests/test_parity.py</code> fails if they drift.
</footer>
</div></body></html>"""


def write(result: dict, path: Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(result))
    return p


def write_json(result: dict, path: Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(result, indent=2) + "\n")
    return p
