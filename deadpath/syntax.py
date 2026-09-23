"""Shared annotation / base-class / private-def extractors.

Used by the TypeScript graph and the polyglot reference graph so framework
registration attributes (``@Component``, ``[HttpGet]``, ``@Injectable``) and
base classes actually move confidence, instead of living only in the Python AST.
"""

from __future__ import annotations

import re

ANN_LINE_RE = re.compile(r"^\s*(?:@|#\[|\[)(\w+)")
CLASS_DEF_RE = re.compile(
    r"\b(?:class|interface|enum|record|object|trait|struct|protocol|actor|module)\s+(\w+)"
)
FUNC_KIND_RE = re.compile(
    r"\b(?:fun|def|func|function|fn|sub)\s+(?:self\.)?(\w+)"
)
TYPED_METHOD_RE = re.compile(
    r"^(?:(?:public|private|protected|internal|open|override|async|static|export|"
    r"pub|virtual|final|abstract|partial|sealed)\s+)+\s*(?:[\w.<>\[\]?,:\s]+\s+)?"
    r"(\w+)\s*\("
)
SKIP_SYMBOLS = {
    "main", "init", "new", "run", "setup", "index", "call", "self", "this",
    "super", "move", "copy", "drop", "if", "for", "while", "switch", "return",
    "class", "struct", "enum", "func", "function", "def", "fun", "fn",
}

EXTENDS_RE = re.compile(
    r"\b(?:class|interface|object|trait|enum|record|struct)\s+(\w+)\s+extends\s+([\w.\\]+)"
)
IMPLEMENTS_RE = re.compile(
    r"\b(?:class|interface|object|enum|record|struct)\s+(\w+)\s+implements\s+([\w.,\s\\]+)"
)
COLON_BASE_RE = re.compile(
    r"\b(?:class|interface|struct|record|enum|protocol|actor|object)\s+(\w+)\s*:\s*"
    r"([\w.<>,\s()?\\]+)(?:\s*\{|\s*$)"
)
RUBY_BASE_RE = re.compile(r"^\s*class\s+(\w+(?:::\w+)*)\s*<\s*([\w:]+)", re.MULTILINE)
PHP_BASE_RE = re.compile(r"\bclass\s+(\w+)\s+extends\s+([\w\\]+)")
ELIXIR_USE_RE = re.compile(r"^\s*use\s+([A-Z][\w.]+)", re.MULTILINE)

PRIVATE_RES: dict[str, list[re.Pattern[str]]] = {
    "go": [re.compile(r"^func(?:\s*\([^)]*\))?\s+([a-z_]\w*)", re.MULTILINE)],
    "rust": [re.compile(r"^\s*(?:async\s+)?fn\s+(\w+)", re.MULTILINE)],
    "java": [re.compile(r"\b(?:private|protected)\s+(?:static\s+)?(?:[\w.<>\[\],\s?]+\s+)?(\w+)\s*\(", re.MULTILINE)],
    "kotlin": [
        re.compile(r"\b(?:private|protected|internal)\s+fun\s+(\w+)", re.MULTILINE),
        re.compile(r"^\s*fun\s+(_\w+)", re.MULTILINE),
    ],
    "scala": [re.compile(r"\bprivate(?:\[[^\]]+\])?\s+def\s+(\w+)", re.MULTILINE)],
    "csharp": [re.compile(r"\b(?:private|protected|internal)\s+(?:static\s+|async\s+|virtual\s+|override\s+)*[\w.<>?]+\s+(\w+)\s*\(", re.MULTILINE)],
    "ruby": [re.compile(r"^\s*def\s+(?:self\.)?(_\w+)", re.MULTILINE)],
    "php": [re.compile(r"\b(?:private|protected)\s+function\s+(\w+)", re.MULTILINE)],
    "swift": [re.compile(r"\b(?:private|fileprivate)\s+(?:static\s+)?func\s+(\w+)", re.MULTILINE)],
    "dart": [re.compile(r"^\s*(?:[\w<>?,\s]+)?(_\w+)\s*\(", re.MULTILINE)],
    "elixir": [re.compile(r"^\s*defp\s+(\w+[?!]?)", re.MULTILINE)],
    "c": [re.compile(r"^\s*static\s+[\w\s\*]+\b(\w+)\s*\(", re.MULTILINE)],
    "lua": [re.compile(r"^\s*local\s+function\s+(\w+)", re.MULTILINE)],
    "perl": [re.compile(r"^\s*sub\s+(_\w+)", re.MULTILINE)],
    "ts": [
        re.compile(r"^(?!export\b)(?:async\s+)?function\s+(_\w+)", re.MULTILINE),
        re.compile(r"^(?!export\b)(?:const|let|var)\s+(_\w+)\s*=", re.MULTILINE),
    ],
}


def decorations_and_bases(text: str) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Map symbol → annotation names and symbol → base-class names."""
    decorated: dict[str, list[str]] = {}
    pending: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        ann = ANN_LINE_RE.match(stripped)
        if ann:
            pending.append(ann.group(1))
            continue
        if stripped.startswith(("//", "/*", "*", "#")) and not stripped.startswith("#["):
            continue
        name = _def_name(stripped)
        if name and pending:
            decorated.setdefault(name, []).extend(pending)
            pending = []
        elif name:
            pending = []
        elif stripped.endswith(("{", ";", ")")):
            pending = []
    return decorated, _bases(text)


def _def_name(stripped: str) -> str | None:
    for regex in (CLASS_DEF_RE, FUNC_KIND_RE, TYPED_METHOD_RE):
        match = regex.search(stripped)
        if match:
            name = match.group(1)
            if name not in SKIP_SYMBOLS:
                return name
    return None


def _bases(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}

    def add(name: str, raw: str) -> None:
        parts = [p.strip() for p in re.split(r"[,\s]+", raw) if p.strip()]
        cleaned: list[str] = []
        for part in parts:
            part = re.sub(r"\(.*\)$", "", part).strip("<>")
            if part and part not in SKIP_SYMBOLS:
                cleaned.append(part)
        if cleaned:
            out.setdefault(name, [])
            for item in cleaned:
                if item not in out[name]:
                    out[name].append(item)

    for name, base in EXTENDS_RE.findall(text):
        add(name, base)
    for name, bases in IMPLEMENTS_RE.findall(text):
        add(name, bases)
    for name, bases in COLON_BASE_RE.findall(text):
        add(name, bases)
    for name, base in RUBY_BASE_RE.findall(text):
        add(name, base)
    for name, base in PHP_BASE_RE.findall(text):
        add(name, base)
    for base in ELIXIR_USE_RE.findall(text):
        # `use Phoenix.Controller` is a framework role, not a type def.
        add(base.split(".")[-1], base)
    return out


def unused_privates(lang: str, text: str) -> dict[str, int]:
    """Private / unexported defs whose identifier occurs only at the definition."""
    found: dict[str, int] = {}
    for regex in PRIVATE_RES.get(lang, []):
        for match in regex.finditer(text):
            name = match.group(1)
            if not name or name in SKIP_SYMBOLS or len(name) < 3:
                continue
            full_line = _line_at(text, match.start())
            if lang == "rust" and re.search(r"\bpub\b", full_line):
                continue
            found[name] = text[: match.start()].count("\n") + 1
    out: dict[str, int] = {}
    for name, lineno in found.items():
        if len(re.findall(rf"\b{re.escape(name)}\b", text)) <= 1:
            out[name] = lineno
    return out


def _line_at(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start:] if end < 0 else text[start:end]
