"""Grounded LLM counsel (stage four).

Detection — graph, confidence, judge — never calls a model. CI, air-gapped
installs, and code review must see the same verdict without a key.

The model is used only where it can add a *veto*, not a guess:

* Judge ``remove`` findings go first. Skipping ``block`` was the wrong safety
  story: those are the deletions that hurt if a regex judge missed a live path
  (Temporal workflow, custom scheduler, house-style entry).
* Judge ``verify`` / scan ``warn`` findings go next (ambiguous evidence).
* ``keep`` is never sent (already settled with ``file:line`` evidence).
* ``note`` is never sent (too weak; a model would confabulate).
* The model cannot *strengthen*: it may confirm ``remove``, escalate to
  ``verify``, or overturn to ``keep``. It cannot turn ``verify`` into
  ``likely_dead``.
* Packets never include file bodies. Verdicts are cached by evidence digest.
* Without a key the same interface returns deterministic heuristic verdicts.

Verdicts: ``likely_dead`` | ``verify`` | ``keep``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from deadpath.llm import LLMUnavailable, available, chat
from deadpath.memory import Memory, estimate_tokens
from deadpath.scan import Finding

VERDICTS = ("likely_dead", "verify", "keep")
DEFAULT_MAX_ITEMS = 8
STRONG_NEGATIVE = {
    "framework_registration_decorator",
    "framework_base_class",
    "module_getattr_lazy_export",
    "main_guard",
    "framework_entry_role",
}
SOFT_NEGATIVE = {
    "module_named_in_string_literal",
    "symbol_named_in_string_literal",
    "module_named_in_config",
    "symbol_named_in_config",
    "decorated_unknown",
    "module_imported_whole_attribute_access_possible",
}
POLICY = (
    "model is a veto-only counsel on judge remove (first) and verify/warn packets; "
    "cannot strengthen verify to likely_dead; keep and note are never sent; "
    "verdicts cached by evidence digest; never file bodies"
)


def evidence_digest(finding: Finding) -> str:
    raw = json.dumps(
        {
            "id": finding.id,
            "path": finding.path,
            "symbol": finding.symbol,
            "signals": finding.signals,
            "confidence": finding.confidence,
            "verdict": finding.verdict,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def counsel_role(finding: Finding) -> str | None:
    """``remove`` | ``verify`` if the model/heuristic should see this finding, else None."""
    verdict = finding.verdict
    if verdict == "keep":
        return None
    if finding.severity == "note" and verdict != "remove":
        return None
    if verdict == "remove" or (verdict is None and finding.severity == "block"):
        return "remove"
    if verdict == "verify" or finding.severity == "warn":
        return "verify"
    return None


def clamp_llm_verdict(finding: Finding, llm_verdict: str) -> str:
    """The model may only confirm, escalate, or overturn — never upgrade risk."""
    if llm_verdict not in VERDICTS:
        llm_verdict, _ = heuristic_verdict(finding)
    if llm_verdict == "keep":
        return "keep"
    if llm_verdict == "verify":
        return "verify"
    if counsel_role(finding) == "verify" or finding.verdict == "verify":
        return "verify"
    return "likely_dead"


def judge_brief(finding: Finding) -> dict[str, Any] | None:
    """Compact judge summary: verdict, next check, what held, what was already ruled out."""
    critique = finding.critique
    if not critique:
        return None
    objections = [
        f"{o['hypothesis']}@{o['evidence'][0]['where']}" if o.get("evidence") and not o["evidence"][0]["where"].endswith(":0") else o["hypothesis"]
        for o in critique.get("objections", [])
        if o.get("penalty", 0) > 0
    ][:4]
    caveats = [o["hypothesis"] for o in critique.get("identification", []) if o.get("penalty", 0) > 0][:3]
    brief: dict[str, Any] = {
        "verdict": critique["verdict"],
        "checked": critique.get("hypotheses_checked", 0),
        "next_check": critique.get("next_check"),
    }
    if objections:
        brief["objections"] = objections
    if caveats:
        brief["caveats"] = caveats
    ruled_out = _ruled_out(finding)
    if ruled_out:
        brief["ruled_out"] = ruled_out
    if critique.get("security", {}).get("markers"):
        brief["security"] = [m["marker"] for m in critique["security"]["markers"][:3]]
    return brief


def _ruled_out(finding: Finding) -> list[str]:
    critique = finding.critique or {}
    held = {o["hypothesis"] for o in critique.get("objections", []) if o.get("penalty", 0) > 0}
    try:
        from deadpath.critic import HYPOTHESES
    except ImportError:
        return []
    names = [h.name for h in HYPOTHESES if finding.kind in h.kinds and h.name not in held]
    return names[:16]


def packet(finding: Finding) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": finding.id,
        "kind": finding.kind,
        "path": finding.path,
        "symbol": finding.symbol,
        "confidence": finding.confidence,
        "signals": finding.signals,
        "why": finding.why,
        "role": counsel_role(finding),
    }
    brief = judge_brief(finding)
    if brief:
        data["judge"] = brief
    return data


def heuristic_verdict(finding: Finding) -> tuple[str, str]:
    critique = finding.critique
    if critique:
        sustained = [o for o in critique.get("objections", []) if o.get("penalty", 0) > 0]
        top = sustained[0]["hypothesis"] if sustained else None
        if critique["verdict"] == "keep":
            return "keep", f"judge: {top or 'defense'} sustained; treat as reachable until the named artifact says otherwise"
        if critique["verdict"] == "remove":
            return "likely_dead", f"judge: none of {critique.get('hypotheses_checked', 0)} counter-hypotheses held; validate, then propose removal"
        return "verify", f"judge: {critique.get('next_check') or 'one targeted check settles it'}"
    names = {k for k, v in finding.signals.items() if v < 0}
    if names & STRONG_NEGATIVE:
        return "keep", "framework or entry-point signal present; treat as intentionally reachable until proven otherwise"
    if names & SOFT_NEGATIVE:
        return "verify", "dynamic or string reference signal present; grep the named reference before acting"
    if finding.confidence >= 0.7:
        return "likely_dead", "no reachability signals; import graph alone supports removal after validation"
    return "verify", "moderate confidence without decisive signals"


def triage(
    findings: list[Finding],
    memory: Memory,
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    """Return {"verdicts": {id: {...}}, "llm": {...stats}} and persist verdicts."""
    llm_ok = available() if use_llm is None else (use_llm and available())
    store = memory.data.setdefault("llm", {})
    verdicts: dict[str, dict[str, Any]] = {}
    stats = {
        "enabled": bool(llm_ok),
        "called": False,
        "asked": 0,
        "cached": 0,
        "heuristic": 0,
        "skipped_keep": 0,
        "skipped_note": 0,
        "reviewed_remove": 0,
        "reviewed_verify": 0,
        "deferred": 0,
        "prompt_tokens_estimate": 0,
        "model": None,
        "policy": POLICY,
    }

    to_ask: list[Finding] = []
    for finding in findings:
        role = counsel_role(finding)
        if role is None:
            if finding.verdict == "keep":
                stats["skipped_keep"] += 1
            else:
                stats["skipped_note"] += 1
            continue
        if role == "remove":
            stats["reviewed_remove"] += 1
        else:
            stats["reviewed_verify"] += 1
        digest = evidence_digest(finding)
        cached = store.get(finding.id)
        if cached and cached.get("digest") == digest and (cached.get("model") != "heuristic" or not llm_ok):
            verdicts[finding.id] = cached
            stats["cached"] += 1
            continue
        to_ask.append(finding)

    to_ask.sort(key=lambda f: (0 if counsel_role(f) == "remove" else 1, -f.confidence, f.id))

    if llm_ok and to_ask:
        batch = to_ask[:max_items]
        stats["deferred"] = max(0, len(to_ask) - len(batch))
        try:
            answers, usage = _ask(batch)
            stats["called"] = True
            stats["asked"] = len(batch)
            stats["model"] = usage.get("model")
            stats["prompt_tokens_estimate"] = usage.get("prompt_tokens") or estimate_tokens(json.dumps([packet(f) for f in batch]))
            for finding in batch:
                answer = answers.get(finding.id) or {}
                raw = answer.get("verdict") if answer.get("verdict") in VERDICTS else None
                if raw is None:
                    verdict, reason = heuristic_verdict(finding)
                    model = "heuristic"
                else:
                    verdict = clamp_llm_verdict(finding, raw)
                    reason = str(answer.get("reason", ""))[:300]
                    model = str(usage.get("model") or "llm")
                entry = _entry(finding, verdict, reason, model)
                if answer.get("counter"):
                    entry["counter"] = str(answer["counter"])[:200]
                if verdict != raw and raw in VERDICTS:
                    entry["clamped_from"] = raw
                store[finding.id] = entry
                verdicts[finding.id] = entry
            to_ask = to_ask[len(batch):]
        except LLMUnavailable:
            stats["enabled"] = False

    for finding in to_ask:
        verdict, reason = heuristic_verdict(finding)
        entry = _entry(finding, verdict, reason, "heuristic")
        store[finding.id] = entry
        verdicts[finding.id] = entry
        stats["heuristic"] += 1

    memory.dirty = True
    memory.save()
    return {"verdicts": verdicts, "llm": stats}


def _entry(finding: Finding, verdict: str, reason: str, model: str) -> dict[str, Any]:
    from deadpath.memory import _now

    return {"digest": evidence_digest(finding), "verdict": verdict, "reason": reason, "model": model, "at": _now()}


def _ask(batch: list[Finding]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    system = (
        "You are counsel for the defense — a second devil's advocate — on static dead-code findings. A deterministic judge already "
        "checked named counter-hypotheses (schedulers, CLI/container/serverless entries, CI, reflection, "
        "templates, plugin registries, feature flags, platform guards, generated code, orchestration, "
        "public library surface) and reports verdict, next_check, sustained objections, and ruled_out "
        "under `judge`. You cannot see source. You may not invent files. "
        "Your job is to SAVE live code the judge might have missed, not to rubber-stamp deletions. "
        "For each item: name the single strongest remaining live-path (mechanism + where to look), then "
        "decide likely_dead (confirm removal after tests), verify (one check first), or keep (probably live). "
        "Items with role=remove are about to be proposed for deletion — bias toward verify/keep if any "
        "plausible live path remains. Never upgrade a verify item to likely_dead. Never recommend automatic "
        "deletion. Respond with JSON: "
        '{"verdicts": {"<id>": {"counter": "<= 15 words", "verdict": "...", "reason": "<= 20 words"}}}'
    )
    text, usage = chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"items": [packet(f) for f in batch]})},
        ],
        max_tokens=90 * len(batch) + 80,
        json_mode=True,
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMUnavailable("non-JSON triage response") from exc
    verdicts = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(verdicts, dict):
        raise LLMUnavailable("triage response missing verdicts")
    return verdicts, usage
