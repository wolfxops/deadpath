"""Ordered cleanup plan. Never writes or deletes files.

Judge ``keep`` findings are omitted: a live path already has ``file:line``
evidence, and listing them as delete steps is how agents undo the judge.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from deadpath.scan import Finding

KIND_ORDER = {
    "unused_export": 0,
    "unused_dep": 1,
    "unreachable": 2,
    "orphan_file": 3,
}

ACTION_FOR_KIND = {
    "unused_export": "remove_export",
    "unused_dep": "drop_dep",
    "unreachable": "review_symbol",
    "orphan_file": "delete_file_manual",
}


@dataclass
class PlanStep:
    order: int
    action: str
    path: str
    symbol: str | None
    reason: str
    finding_id: str
    severity: str
    confidence: float = 0.0
    judge: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _rank_key(finding: Finding) -> tuple:
    verdict = finding.verdict
    band = 0 if verdict == "remove" or finding.severity == "block" else 1 if verdict == "verify" or finding.severity == "warn" else 2
    return (band, KIND_ORDER.get(finding.kind, 9), -finding.confidence, finding.path, finding.symbol or "")


def build_plan(findings: list[Finding]) -> list[PlanStep]:
    ranked = sorted((f for f in findings if f.verdict != "keep"), key=_rank_key)
    steps: list[PlanStep] = []
    for index, finding in enumerate(ranked, start=1):
        action = ACTION_FOR_KIND.get(finding.kind, "review")
        if finding.kind == "orphan_file":
            reason = (
                f"Manually delete `{finding.path}` only after confirming it is not an "
                f"entry point. {finding.why}"
            )
        elif finding.kind == "unused_export":
            reason = (
                f"Remove export `{finding.symbol}` from `{finding.path}` "
                f"(or stop exporting it). {finding.why}"
            )
        elif finding.kind == "unused_dep":
            reason = f"Consider dropping `{finding.symbol}` from `{finding.path}`. {finding.why}"
        else:
            reason = finding.why
        if finding.verdict == "verify" or finding.severity != "block":
            reason += f" Confidence {finding.confidence:.2f}: verify before acting."
        steps.append(
            PlanStep(
                order=index,
                action=action,
                path=finding.path,
                symbol=finding.symbol,
                reason=reason,
                finding_id=finding.id,
                severity=finding.severity,
                confidence=finding.confidence,
                judge=finding.verdict,
            )
        )
    return steps


def plan_payload(findings: list[Finding], *, path: str) -> dict:
    skipped = [f for f in findings if f.verdict == "keep"]
    steps = build_plan(findings)
    summary = "Ordered suggestions only. Deadpath does not delete files or apply patches."
    if skipped:
        summary += f" {len(skipped)} finding(s) omitted: the judge found a live path (keep)."
    return {
        "tool": "deadpath",
        "auto_delete": False,
        "path": path,
        "summary": summary,
        "skipped_keep": [
            {
                "id": f.id,
                "path": f.path,
                "symbol": f.symbol,
                "next_check": (f.critique or {}).get("next_check"),
            }
            for f in skipped
        ],
        "steps": [step.to_dict() for step in steps],
    }
