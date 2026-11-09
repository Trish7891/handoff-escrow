"""Acceptance criteria, evaluated against what the worker actually produced.

Every criterion is machine-checkable on purpose. If a condition needs taste, it
does not belong in the criteria list — it belongs in a dispute, which is a
different (and much more expensive) path.

A criterion is a dict ``{"kind": ..., "params": {...}}`` and the verifier runs in
the job workspace. Unknown kinds fail closed: a buyer who invents a criterion
gets no payment, never a silent pass.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .model import Delivery, sha256_file


@dataclass
class Check:
    kind: str
    ok: bool
    detail: str
    note: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "ok": self.ok, "detail": self.detail, "note": self.note}


@dataclass
class Verdict:
    passed: bool
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def to_dict(self) -> dict:
        return {"passed": self.passed, "checks": [c.to_dict() for c in self.checks]}

    def summary(self) -> str:
        if self.passed:
            return f"{len(self.checks)}/{len(self.checks)} checks passed"
        return "; ".join(f"{c.kind}: {c.detail}" for c in self.failures)


def _safe(workspace: Path, rel: str) -> Path:
    """Refuse paths that escape the job workspace — a criterion is not a root shell."""
    p = (workspace / rel).resolve()
    if workspace.resolve() not in p.parents and p != workspace.resolve():
        raise ValueError(f"path escapes workspace: {rel}")
    return p


def _check(kind: str, params: dict, workspace: Path, delivery: Delivery) -> Check:
    if kind == "artifact_sha256":
        want = (params.get("sha256") or "").lower()
        got = sha256_file(_safe(workspace, delivery.artifact))
        return Check(kind, got == want, f"{got[:16]}… vs expected {want[:16]}…")

    if kind == "file_exists":
        p = _safe(workspace, params["path"])
        if not p.exists():
            return Check(kind, False, f"missing {params['path']}")
        floor = int(params.get("min_bytes", 1))
        size = p.stat().st_size
        return Check(kind, size >= floor, f"{params['path']} is {size} bytes (min {floor})")

    if kind == "command_exit_zero":
        cmd = params["cmd"]
        assert isinstance(cmd, list), "cmd must be a list — no shell strings"
        try:
            proc = subprocess.run(
                cmd,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=int(params.get("timeout", 120)),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return Check(kind, False, f"could not run {cmd}: {exc}")
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
        return Check(kind, proc.returncode == 0, f"exit {proc.returncode}: {tail[0][:120]}")

    if kind == "json_keys":
        p = _safe(workspace, params["path"])
        if not p.exists():
            return Check(kind, False, f"missing {params['path']}")
        try:
            doc = json.loads(p.read_text())
        except json.JSONDecodeError as exc:
            return Check(kind, False, f"invalid json: {exc}")
        missing = [k for k in params.get("keys", []) if k not in doc]
        return Check(kind, not missing, "all keys present" if not missing else f"missing {missing}")

    if kind == "words_at_most":
        p = _safe(workspace, params["path"])
        if not p.exists():
            return Check(kind, False, f"missing {params['path']}")
        words = len(re.findall(r"\S+", p.read_text(errors="replace")))
        cap = int(params["max"])
        return Check(kind, words <= cap, f"{words} words (cap {cap})")

    if kind == "matches":
        p = _safe(workspace, params["path"])
        if not p.exists():
            return Check(kind, False, f"missing {params['path']}")
        hit = re.search(params["pattern"], p.read_text(errors="replace"), re.MULTILINE)
        return Check(kind, bool(hit), f"pattern {params['pattern']!r} {'found' if hit else 'absent'}")

    if kind == "no_path":
        p = _safe(workspace, params["path"])
        return Check(kind, not p.exists(), f"{params['path']} {'absent' if not p.exists() else 'still present'}")

    return Check(kind, False, f"unknown criterion {kind!r} — failing closed")


def verify(delivery: Delivery, criteria, workspace) -> Verdict:
    """Run every criterion. All must pass; the first failure does not short-circuit."""
    ws = Path(workspace)
    checks: list[Check] = []
    for c in criteria:
        params = c["params"] if isinstance(c, dict) else c.params
        kind = c["kind"] if isinstance(c, dict) else c.kind
        note = c.get("note", "") if isinstance(c, dict) else getattr(c, "note", "")
        try:
            chk = _check(kind, params, ws, delivery)
        except Exception as exc:  # a broken criterion must not pay out
            chk = Check(kind, False, f"verifier error: {exc}")
        chk.note = note
        checks.append(chk)
    return Verdict(passed=all(c.ok for c in checks), checks=checks)
