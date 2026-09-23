"""Machine-readable support matrix: languages, precision, frameworks."""

from __future__ import annotations

from typing import Any

from deadpath.langs import FRAMEWORKS, LANGUAGE_NAMES
from deadpath.polyglot import LANGS

TIERS = {
    "py": {"tier": "ast", "precision": "path", "detects": ["orphan_file", "unused_export", "unused_dep", "unreachable"], "suffixes": [".py"]},
    "ts": {"tier": "regex-graph", "precision": "path", "detects": ["orphan_file", "unused_export", "unused_dep", "unreachable"], "suffixes": [".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".vue", ".svelte"]},
}


def languages_payload() -> dict[str, Any]:
    languages: list[dict[str, Any]] = []
    for key in ("py", "ts"):
        languages.append({"key": key, "name": LANGUAGE_NAMES[key], **TIERS[key], "frameworks": _frameworks_for(key), "validate": []})
    for key, spec in LANGS.items():
        languages.append(
            {
                "key": key,
                "name": spec.name,
                "tier": "reference-graph",
                "precision": spec.precision,
                "detects": ["orphan_file", "unused_export", "unused_dep", "unreachable"],
                "suffixes": list(spec.suffixes),
                "frameworks": _frameworks_for(key),
                "validate": list(spec.validate),
                "manifests": list(spec.manifests),
            }
        )
    return {
        "tool": "deadpath",
        "languages": languages,
        "frameworks": sorted(FRAMEWORKS),
        "counts": {"languages": len(languages), "frameworks": len(FRAMEWORKS)},
        "precision_note": (
            "path: imports resolve to files, findings may reach block. "
            "name: references are type/module tokens, findings capped at warn. "
            "unused_dep is guessed from manifests; unreachable is private names with a single token occurrence."
        ),
    }


def _frameworks_for(lang_key: str) -> list[str]:
    out: list[str] = []
    for name, spec in FRAMEWORKS.items():
        langs = {spec["language"], *spec.get("also", [])}
        if lang_key in langs:
            out.append(name)
    return sorted(out)
