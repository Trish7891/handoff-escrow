#!/usr/bin/env python3
"""File the NEAR HACKATHON submission, or just print what would be sent.

    python3 tools/submit_near.py --email you@example.com --wallet you.near \
        --demo-url https://x.com/totem1zn/status/...

Prints the exact JSON payload; sends nothing without --confirm. The same
requestId is reused across retries, so a retried send cannot create a second
submission. One repository can be submitted exactly once.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENDPOINT = "https://nearhackathon.com/api/applications"
ID_FILE = ROOT / ".submit_request_id"

PROJECT = "Handoff"
LEAD = "Trishan Rajkumar"
SIZE = "1"
REPO = "https://github.com/Trish7891/handoff-escrow"
TRACKS = ["agents"]  # 07 Agent Economy; add "swarms" for AI Swarms too

WALLET_RE = re.compile(r"^(([a-z\d]+[-_])*[a-z\d]+\.)*([a-z\d]+[-_])*[a-z\d]+$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def request_id() -> str:
    import uuid

    if ID_FILE.exists():
        return ID_FILE.read_text().strip()
    rid = str(uuid.uuid4())
    ID_FILE.write_text(rid + "\n")
    return rid


def payload(email: str, wallet: str, demo_url: str) -> dict:
    idea = (ROOT / "docs" / "idea.txt").read_text().strip()
    return {
        "requestId": request_id(),
        "projectName": PROJECT,
        "leadName": LEAD,
        "email": email,
        "size": SIZE,
        "tracks": TRACKS,
        "nearAddress": wallet,
        "projectUrl": REPO,
        "demoUrl": demo_url,
        "idea": idea,
        "consent": True,
        # no "website" key: a non-empty website is treated as spam
    }


def check(p: dict) -> list[str]:
    bad = []
    if not 2 <= len(p["projectName"]) <= 80:
        bad.append("projectName length")
    if not 2 <= len(p["leadName"]) <= 80:
        bad.append("leadName length")
    if not EMAIL_RE.match(p["email"]) or len(p["email"]) > 160:
        bad.append("email")
    if p["size"] not in {"1", "2 - 4", "4 - 6", "6 - 8", "8+"}:
        bad.append("size")
    known = {"defi", "thesis", "privacy", "business", "swarms", "security",
             "agents", "realworld", "games", "nfts", "memecoins", "social", "open"}
    if not p["tracks"] or not set(p["tracks"]) <= known:
        bad.append("tracks")
    if not WALLET_RE.match(p["nearAddress"]) or not 2 <= len(p["nearAddress"]) <= 64:
        bad.append("nearAddress (mainnet account id, lowercase)")
    if not p["projectUrl"].startswith(("http://", "https://")) or len(p["projectUrl"]) > 300:
        bad.append("projectUrl")
    if not p["demoUrl"].startswith(("http://", "https://")) or len(p["demoUrl"]) > 300:
        bad.append("demoUrl")
    if not 20 <= len(p["idea"]) <= 2000:
        bad.append(f"idea length ({len(p['idea'])}, needs 20-2000)")
    body = len(json.dumps(p).encode())
    if body > 12000:
        bad.append(f"body {body} bytes > 12000")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--wallet")
    ap.add_argument("--demo-url")
    ap.add_argument("--confirm", action="store_true", help="actually POST")
    ap.add_argument("--tracks", default=",".join(TRACKS),
                    help="comma separated track ids (default: agents)")
    a = ap.parse_args(argv)
    if a.tracks != ",".join(TRACKS):
        TRACKS[:] = [t.strip() for t in a.tracks.split(",") if t.strip()]
    if not (a.email and a.wallet and a.demo_url):
        ap.error("--email, --wallet and --demo-url are required")

    p = payload(a.email, a.wallet, a.demo_url)
    text = json.dumps(p, indent=2, ensure_ascii=False)
    problems = check(p)
    print(text)
    print(f"\nbody {len(json.dumps(p).encode())} bytes · idea {len(p['idea'])} chars")
    if problems:
        print("FAILS: " + ", ".join(problems), file=sys.stderr)
        return 2
    if not a.confirm:
        print("\ndry run — nothing sent. Re-run with --confirm to submit.")
        return 0

    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(p).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "handoff-escrow/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"\nHTTP {r.status}: {r.read(400).decode(errors='replace')}")
            return 0 if r.status == 201 else 1
    except urllib.error.HTTPError as e:
        body = e.read(600).decode(errors="replace")
        print(f"\nHTTP {e.code}: {body}", file=sys.stderr)
        if e.code == 400:
            print("fix the fields listed in `fields`, resend with the same requestId", file=sys.stderr)
        if e.code in (403, 409):
            print("do not retry and do not change the repo link or email", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
