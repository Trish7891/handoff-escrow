"""Command line: run the demo, verify a chain, and show tampering being caught."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .ledger import Ledger, LedgerError, _hash_entry
from .report import write, write_json
from .scenarios import run_all

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"


def cmd_demo(args) -> int:
    out = Path(args.out) if args.out else ART
    result = run_all(out / "workspaces")
    led = Ledger()
    for s in result["scenarios"]:
        for e in s["events"]:
            led.entries.append(_entry(e))
    led.save(out / "ledger.json")
    write_json(result, out / "results.json")
    page = write(result, out / "report.html")

    print(f"{'scenario':<10} {'winner':<16} {'outcome':<10} {'verdict':<8} conserved")
    for s in result["scenarios"]:
        passed = "pass" if s["verdict"]["passed"] else "fail"
        print(f"{s['id']:<10} {s['winner']:<16} {s['outcome']:<10} {passed:<8} {s['conserved']}")
    l = result["ledger"]
    print(f"\n{ l['entries'] } entries · head {l['head'][:16]}… · chain {'verified' if l['verified'] else 'BROKEN'}")
    print(f"volume {l['total_volume']} NEAR · report {page.relative_to(ROOT)}")
    return 0


def _entry(d: dict):
    from .ledger import Entry

    return Entry.from_dict(d)


def cmd_verify(args) -> int:
    try:
        led = Ledger.load(args.path)
    except LedgerError as exc:
        print(f"BROKEN: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {len(led.entries)} entries, head {led.head}")
    return 0


def cmd_tamper(args) -> int:
    """Rewrite one settled amount, then show the chain refusing to validate."""
    src = Path(args.path) if args.path else ART / "ledger.json"
    dst = Path(args.out) if args.out else ART / "ledger.tampered.json"
    shutil.copyfile(src, dst)
    doc = json.loads(dst.read_text())
    victim = next(e for e in doc["entries"] if e["kind"] == "settlement")
    before = victim["payload"]["settlement"]["amount_yocto"]
    victim["payload"]["settlement"]["amount_yocto"] = before * 2
    dst.write_text(json.dumps(doc, indent=2) + "\n")

    led = Ledger()
    led.entries = [_entry(e) for e in doc["entries"]]
    ok, bad = led.verify()
    print(f"edited entry {victim['seq']}: {before / 10**24:.6f} → {before * 2 / 10**24:.6f} NEAR")
    print(f"verify → {'ok (unexpected)' if ok else f'BROKEN at entry {bad}'}")
    return 0 if not ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="handoff", description="Proof-of-work escrow for agent labour.")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="run the three scenarios and write the report")
    d.add_argument("--out", help="artifact directory (default artifacts/)")
    d.set_defaults(fn=cmd_demo)

    v = sub.add_parser("verify", help="recompute a saved ledger's hash chain")
    v.add_argument("path", nargs="?", default=str(ART / "ledger.json"))
    v.set_defaults(fn=cmd_verify)

    t = sub.add_parser("tamper", help="edit one settlement and show verification fail")
    t.add_argument("path", nargs="?", default=str(ART / "ledger.json"))
    t.add_argument("--out", default=str(ART / "ledger.tampered.json"))
    t.set_defaults(fn=cmd_tamper)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
