"""Generic file-level reference graph for languages beyond Python and TS.

Each language declares, with regexes, how a file is *identified* by other
files (import path, module name, declared type names) and which identifiers a
file *references*. A file with no references from any other file, and no entry
role, is an orphan candidate.

Precision is declared per language and lowers confidence accordingly:

* ``path`` — imports resolve to concrete files (Go, Rust, Dart, Ruby require,
  C headers, Lua, Perl). Findings can reach ``block``.
* ``name`` — references are type/module names matched as tokens (Java, Kotlin,
  Scala, C#, Swift, PHP, Elixir). Findings stay ``warn`` or lower.

Facts per file are JSON-serializable and cached in memory by content hash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from deadpath.graph import FactsCache, sha256_text
from deadpath.syntax import decorations_and_bases, unused_privates

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
MAX_TOKENS = 4000


@dataclass
class LangSpec:
    key: str
    name: str
    suffixes: tuple[str, ...]
    precision: str  # path | name
    ids: Callable[[str, str, dict[str, Any]], set[str]]
    refs: Callable[[str, str, dict[str, Any]], set[str]]
    entry: Callable[[str, str], bool]
    is_test: Callable[[str], bool]
    exports: Callable[[str], list[str]] | None = None
    validate: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    context: Callable[[Path], dict[str, Any]] | None = None
    frameworks_hint: list[str] = field(default_factory=list)


@dataclass
class PolyFile:
    rel: str
    lang: str
    ids: set[str]
    refs: set[str]
    tokens: set[str]
    exports: list[str]
    entry: bool
    test: bool
    digest: str
    decorated: dict[str, list[str]] = field(default_factory=dict)
    bases: dict[str, list[str]] = field(default_factory=dict)
    privates: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _stem(rel: str) -> str:
    return Path(rel).stem


def _noext(rel: str) -> str:
    p = Path(rel)
    return (p.parent / p.stem).as_posix() if p.parent.as_posix() != "." else p.stem


def _norm(path: str) -> str:
    parts: list[str] = []
    for part in path.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def _join(rel_dir: str, spec: str) -> str:
    return _norm(f"{rel_dir}/{spec}" if rel_dir else spec)


def _in_dirs(rel: str, names: set[str]) -> bool:
    return bool({p.lower() for p in Path(rel).parts[:-1]} & names)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(x for x in items if x))


# --------------------------------------------------------------------------- #
# Go
# --------------------------------------------------------------------------- #

GO_IMPORT_RE = re.compile(r'^\s*(?:import\s+)?(?:\w+\s+)?"([^"]+)"', re.MULTILINE)
GO_PKG_RE = re.compile(r"^\s*package\s+(\w+)", re.MULTILINE)
GO_EXPORT_RE = re.compile(r"^(?:func(?:\s*\([^)]*\))?|type|var|const)\s+([A-Z]\w*)", re.MULTILINE)


def _go_ctx(root: Path) -> dict[str, Any]:
    text = _read(root / "go.mod")
    m = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
    return {"module": m.group(1) if m else ""}


def _go_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    d = Path(rel).parent.as_posix()
    mod = ctx.get("module", "")
    pkg_path = mod if d == "." else (f"{mod}/{d}" if mod else d)
    return {pkg_path, d if d != "." else ""} - {""}


def _go_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    in_block = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("import ("):
            in_block = True
            continue
        if in_block and s.startswith(")"):
            in_block = False
            continue
        if in_block or s.startswith("import "):
            m = re.search(r'"([^"]+)"', s)
            if m:
                refs.add(m.group(1))
    return refs


def _go_entry(rel: str, text: str) -> bool:
    m = GO_PKG_RE.search(text)
    return bool(m and m.group(1) == "main") or Path(rel).name in {"doc.go", "embed.go"}


# --------------------------------------------------------------------------- #
# Rust
# --------------------------------------------------------------------------- #

RUST_MOD_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;", re.MULTILINE)
RUST_USE_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+(crate|super|self)((?:::\w+)+)", re.MULTILINE)
RUST_EXTERN_RE = re.compile(r"^\s*(?:use|extern\s+crate)\s+([a-z][\w]*)", re.MULTILINE)
RUST_EXPORT_RE = re.compile(r"^\s*pub\s+(?:async\s+)?(?:fn|struct|enum|trait|type|const|static)\s+(\w+)", re.MULTILINE)


def _rust_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    p = Path(rel)
    if p.name == "mod.rs":
        return {p.parent.as_posix()}
    return {_noext(rel)}


def _rust_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    p = Path(rel)
    here = p.parent.as_posix()
    if p.name in {"mod.rs", "main.rs", "lib.rs"}:
        base = here
    else:
        base = _noext(rel)
    refs: set[str] = set()
    for name in RUST_MOD_RE.findall(text):
        refs.add(_join(base, name))
        refs.add(_join(here, name))
    src_root = ctx.get("src_root", "src")
    for kind, tail in RUST_USE_RE.findall(text):
        segs = [s for s in tail.split("::") if s]
        if kind == "crate":
            start = src_root
        elif kind == "super":
            start = Path(here).parent.as_posix()
        else:
            start = base
        acc = start
        for seg in segs:
            acc = _join(acc, seg)
            refs.add(acc)
    for crate in RUST_EXTERN_RE.findall(text):
        if crate not in {"crate", "super", "self"}:
            refs.add(crate)
    return refs


def _rust_entry(rel: str, text: str) -> bool:
    p = Path(rel)
    return p.name in {"main.rs", "lib.rs", "build.rs"} or _in_dirs(rel, {"bin", "examples", "benches", "tests"})


# --------------------------------------------------------------------------- #
# JVM family: Java, Kotlin, Scala
# --------------------------------------------------------------------------- #

JVM_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)", re.MULTILINE)
JVM_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)", re.MULTILINE)
JVM_TYPE_RE = re.compile(r"\b(?:class|interface|enum|record|object|trait)\s+([A-Z]\w*)")
JVM_PUBLIC_METHOD_RE = re.compile(
    r"^\s*public\s+(?:static\s+)?(?:final\s+)?[\w.<>\[\],\s?]+\s+(\w+)\s*\(",
    re.MULTILINE,
)
JVM_FUN_RE = re.compile(r"^\s*(?:override\s+|open\s+|public\s+|internal\s+)*fun\s+(\w+)", re.MULTILINE)
SCALA_DEF_RE = re.compile(r"^\s*(?:override\s+|protected\s+)?def\s+(\w+)", re.MULTILINE)
JVM_MAIN_RE = re.compile(
    r"static\s+void\s+main\s*\(|fun\s+main\s*\(|def\s+main\s*\(|extends\s+App\b|"
    r"@SpringBootApplication|@MicronautTest|@QuarkusMain|@main\b"
)


def _jvm_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    pkg = JVM_PACKAGE_RE.search(text)
    types = set(JVM_TYPE_RE.findall(text)) | {_stem(rel)}
    ids = set(types)
    if pkg:
        for t in types:
            ids.add(f"{pkg.group(1)}.{t}")
        ids.add(f"{pkg.group(1)}.*")
    return ids


def _jvm_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs = set(JVM_IMPORT_RE.findall(text))
    for item in list(refs):
        tail = item.rsplit(".", 1)[-1]
        if tail != "*":
            refs.add(tail)
    return refs


def _jvm_exports(text: str) -> list[str]:
    names = list(JVM_TYPE_RE.findall(text))
    names.extend(JVM_PUBLIC_METHOD_RE.findall(text))
    names.extend(JVM_FUN_RE.findall(text))
    names.extend(SCALA_DEF_RE.findall(text))
    skip = {"main", "toString", "hashCode", "equals", "compareTo", "invoke", "apply", "unapply"}
    return [n for n in _unique(names) if n not in skip]


def _jvm_entry(rel: str, text: str) -> bool:
    return bool(JVM_MAIN_RE.search(text)) or Path(rel).name in {
        "Application.java", "Application.kt", "Application.scala",
        "MainActivity.kt", "MainActivity.java",
    }


# --------------------------------------------------------------------------- #
# C#
# --------------------------------------------------------------------------- #

CS_TYPE_RE = re.compile(r"\b(?:class|interface|struct|enum|record)\s+([A-Z]\w*)")
CS_NS_RE = re.compile(r"^\s*namespace\s+([\w.]+)\s*[;{]", re.MULTILINE)
CS_USING_RE = re.compile(r"^\s*(?:global\s+)?using\s+(?:static\s+)?([\w.]+)\s*;", re.MULTILINE)
CS_PUBLIC_MEMBER_RE = re.compile(
    r"\bpublic\s+(?:static\s+|async\s+|virtual\s+|override\s+|readonly\s+)*(?:[\w.<>?]+\s+)?(\w+)\s*\(",
    re.MULTILINE,
)
CS_MAIN_RE = re.compile(r"static\s+(?:async\s+)?(?:void|int|Task(?:<int>)?)\s+Main\s*\(|WebApplication\.CreateBuilder|Host\.CreateDefaultBuilder")


def _cs_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    types = set(CS_TYPE_RE.findall(text)) | {_stem(rel)}
    ids = set(types)
    for ns in CS_NS_RE.findall(text):
        ids.add(ns)
        ids.add(f"{ns}.*")
        for t in types:
            ids.add(f"{ns}.{t}")
    return ids


def _cs_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs = set(CS_USING_RE.findall(text))
    for item in list(refs):
        refs.add(item.rsplit(".", 1)[-1])
    return refs


def _cs_exports(text: str) -> list[str]:
    names = list(CS_TYPE_RE.findall(text))
    names.extend(CS_PUBLIC_MEMBER_RE.findall(text))
    skip = {"Main", "Equals", "GetHashCode", "ToString", "Dispose", "Configure", "ConfigureServices"}
    return [n for n in _unique(names) if n not in skip]


def _cs_entry(rel: str, text: str) -> bool:
    return bool(CS_MAIN_RE.search(text)) or Path(rel).name in {"Program.cs", "Startup.cs", "GlobalUsings.cs", "AssemblyInfo.cs"} or rel.endswith(".Designer.cs") or _in_dirs(rel, {"migrations", "controllers", "pages", "views"})


# --------------------------------------------------------------------------- #
# Ruby
# --------------------------------------------------------------------------- #

RB_REQUIRE_RE = re.compile(r"""^\s*require\s+['"]([^'"]+)['"]""", re.MULTILINE)
RB_REQUIRE_REL_RE = re.compile(r"""^\s*require_relative\s+['"]([^'"]+)['"]""", re.MULTILINE)
RB_CONST_RE = re.compile(r"^\s*(?:class|module)\s+([A-Z]\w*(?:::[A-Z]\w*)*)", re.MULTILINE)
RB_EXPORT_RE = re.compile(r"^\s*def\s+(?:self\.)?([a-z_]\w*[?!=]?)", re.MULTILINE)


def _rb_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    noext = _noext(rel)
    ids = {noext}
    for prefix in ("lib/", "app/models/", "app/services/", "app/lib/", "src/"):
        if noext.startswith(prefix):
            ids.add(noext[len(prefix):])
    for const in RB_CONST_RE.findall(text):
        ids.add(const)
        ids.add(const.split("::")[-1])
    return ids


def _rb_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs = set(RB_REQUIRE_RE.findall(text))
    here = Path(rel).parent.as_posix()
    for spec in RB_REQUIRE_REL_RE.findall(text):
        refs.add(_join(here if here != "." else "", spec))
    return refs


def _rb_entry(rel: str, text: str) -> bool:
    name = Path(rel).name
    if name in {"Rakefile", "Gemfile", "config.ru", "Guardfile"} or name.endswith(".rake"):
        return True
    if _in_dirs(rel, {"app", "config", "db", "bin", "exe", "script", "tasks"}):
        return True
    # Root-level scripts and files with no class/module are run, not required.
    return Path(rel).parent.as_posix() == "." or (not RB_CONST_RE.search(text) and "__FILE__" in text)


# --------------------------------------------------------------------------- #
# PHP
# --------------------------------------------------------------------------- #

PHP_NS_RE = re.compile(r"^\s*namespace\s+([\w\\]+)\s*;", re.MULTILINE)
PHP_TYPE_RE = re.compile(r"\b(?:class|interface|trait|enum)\s+([A-Z]\w*)")
PHP_USE_RE = re.compile(r"^\s*use\s+([\w\\]+)(?:\s+as\s+\w+)?\s*;", re.MULTILINE)
PHP_INCLUDE_RE = re.compile(r"""(?:require|include)(?:_once)?\s*\(?\s*(?:__DIR__\s*\.\s*)?['"]([^'"]+)['"]""")
PHP_EXPORT_RE = re.compile(r"^\s*public\s+(?:static\s+)?function\s+(\w+)", re.MULTILINE)


def _php_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    ids = {_noext(rel), _stem(rel)}
    ns = PHP_NS_RE.search(text)
    for t in PHP_TYPE_RE.findall(text):
        ids.add(t)
        if ns:
            ids.add(f"{ns.group(1)}\\{t}")
    return ids


def _php_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs = set(PHP_USE_RE.findall(text))
    here = Path(rel).parent.as_posix()
    for spec in PHP_INCLUDE_RE.findall(text):
        refs.add(_noext(_join(here if here != "." else "", spec.lstrip("/"))))
    return refs


def _php_entry(rel: str, text: str) -> bool:
    name = Path(rel).name
    return name in {"index.php", "artisan", "bootstrap.php", "autoload.php", "console"} or _in_dirs(rel, {"public", "routes", "config", "database", "migrations", "bootstrap", "resources"})


# --------------------------------------------------------------------------- #
# Swift
# --------------------------------------------------------------------------- #

SWIFT_TYPE_RE = re.compile(r"\b(?:class|struct|enum|protocol|actor)\s+([A-Z]\w*)")
SWIFT_IMPORT_RE = re.compile(
    r"^\s*import\s+(?:(?:class|struct|enum|protocol|func|var|let|typealias)\s+)?(\w+)",
    re.MULTILINE,
)
SWIFT_EXPORT_RE = re.compile(r"^\s*(?:public|open)\s+(?:static\s+)?(?:func|var|let)\s+(\w+)", re.MULTILINE)


def _swift_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    return set(SWIFT_TYPE_RE.findall(text)) | {_stem(rel)}


def _swift_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    return set(SWIFT_IMPORT_RE.findall(text))


def _swift_exports(text: str) -> list[str]:
    return _unique(list(SWIFT_TYPE_RE.findall(text)) + list(SWIFT_EXPORT_RE.findall(text)))


def _swift_entry(rel: str, text: str) -> bool:
    return Path(rel).name in {"main.swift", "Package.swift", "AppDelegate.swift", "SceneDelegate.swift"} or "@main" in text or "@UIApplicationMain" in text or "PreviewProvider" in text


# --------------------------------------------------------------------------- #
# Dart
# --------------------------------------------------------------------------- #

DART_IMPORT_RE = re.compile(r"""^\s*(?:import|export|part)\s+['"]([^'"]+)['"]""", re.MULTILINE)
DART_TYPE_RE = re.compile(r"^(?:class|enum|mixin|typedef|extension(?:\s+\w+\s+on)?)\s+([A-Z]\w*)", re.MULTILINE)
DART_FN_RE = re.compile(r"^(?:[\w<>?,\s]+)?\b([a-z]\w*)\s*\(", re.MULTILINE)


def _dart_ctx(root: Path) -> dict[str, Any]:
    text = _read(root / "pubspec.yaml")
    m = re.search(r"^name:\s*(\S+)", text, re.MULTILINE)
    return {"package": m.group(1) if m else ""}


def _dart_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    ids = {rel}
    if rel.startswith("lib/") and ctx.get("package"):
        ids.add(f"package:{ctx['package']}/{rel[4:]}")
    return ids


def _dart_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    here = Path(rel).parent.as_posix()
    for spec in DART_IMPORT_RE.findall(text):
        if spec.startswith("package:") or spec.startswith("dart:"):
            refs.add(spec)
        else:
            refs.add(_join(here if here != "." else "", spec))
    return refs


def _dart_exports(text: str) -> list[str]:
    names = list(DART_TYPE_RE.findall(text))
    names.extend(n for n in DART_FN_RE.findall(text) if not n.startswith("_") and n not in {"if", "for", "while", "switch", "return"})
    return _unique(names)


def _dart_entry(rel: str, text: str) -> bool:
    return Path(rel).name == "main.dart" or _in_dirs(rel, {"bin", "test", "integration_test", "tool"}) or "void main(" in text


# --------------------------------------------------------------------------- #
# Elixir
# --------------------------------------------------------------------------- #

EX_MODULE_RE = re.compile(r"^\s*defmodule\s+([A-Z][\w.]*)", re.MULTILINE)
EX_EXPORT_RE = re.compile(r"^\s*def\s+(\w+[?!]?)", re.MULTILINE)
EX_REF_RE = re.compile(r"^\s*(?:alias|import|require|use)\s+([A-Z][\w.]*)", re.MULTILINE)


def _ex_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    mods = set(EX_MODULE_RE.findall(text))
    ids = set(mods) | {_stem(rel)}
    for mod in mods:
        ids.add(mod.split(".")[-1])
    return ids


def _ex_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs = set(EX_REF_RE.findall(text))
    for item in list(refs):
        refs.add(item.split(".")[-1])
    return refs


def _ex_entry(rel: str, text: str) -> bool:
    return Path(rel).name in {"mix.exs", "application.ex", "endpoint.ex", "router.ex", "repo.ex"} or _in_dirs(rel, {"config", "priv", "test", "rel"}) or "use Application" in text


# --------------------------------------------------------------------------- #
# C / C++ headers
# --------------------------------------------------------------------------- #

C_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*"([^"]+)"', re.MULTILINE)
C_DECL_RE = re.compile(r"^(?:extern\s+)?[\w\s\*]+\s+(\w+)\s*\([^;]*\)\s*;", re.MULTILINE)
C_HEADER_SUFFIXES = (".h", ".hpp", ".hh", ".hxx", ".inl")


def _c_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    return {rel, Path(rel).name}


def _c_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    here = Path(rel).parent.as_posix()
    for spec in C_INCLUDE_RE.findall(text):
        refs.add(Path(spec).name)
        refs.add(_join(here if here != "." else "", spec))
        refs.add(_norm(spec))
    return refs


def _c_exports(text: str) -> list[str]:
    skip = {"if", "for", "while", "switch", "return", "sizeof"}
    return [n for n in _unique(C_DECL_RE.findall(text)) if n not in skip]


def _c_entry(rel: str, text: str) -> bool:
    # Translation units are entries; only headers are orphan candidates.
    return not rel.endswith(C_HEADER_SUFFIXES) or Path(rel).name in {"config.h", "pch.h", "stdafx.h"}


# --------------------------------------------------------------------------- #
# Lua
# --------------------------------------------------------------------------- #

LUA_REQUIRE_RE = re.compile(r"""require\s*\(?\s*['"]([\w./-]+)['"]""")
LUA_EXPORT_RE = re.compile(r"^\s*function\s+M\.(\w+)|^\s*M\.(\w+)\s*=", re.MULTILINE)


def _lua_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    noext = _noext(rel)
    ids = {noext, noext.replace("/", ".")}
    if noext.endswith("/init"):
        base = noext[: -len("/init")]
        ids |= {base, base.replace("/", ".")}
    for prefix in ("lua/", "src/", "lib/"):
        if noext.startswith(prefix):
            tail = noext[len(prefix):]
            ids |= {tail, tail.replace("/", ".")}
    return ids


def _lua_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for spec in LUA_REQUIRE_RE.findall(text):
        refs.add(spec)
        refs.add(spec.replace(".", "/"))
    return refs


def _lua_entry(rel: str, text: str) -> bool:
    return Path(rel).name in {"main.lua", "init.lua", "conf.lua", "plugin.lua"} or _in_dirs(rel, {"plugin", "ftplugin", "spec", "tests"})


# --------------------------------------------------------------------------- #
# Perl
# --------------------------------------------------------------------------- #

PL_PACKAGE_RE = re.compile(r"^\s*package\s+([\w:]+)\s*;", re.MULTILINE)
PL_USE_RE = re.compile(r"^\s*(?:use|require)\s+([A-Z][\w:]*)", re.MULTILINE)
PL_EXPORT_RE = re.compile(r"^\s*sub\s+(\w+)", re.MULTILINE)


def _pl_ids(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    noext = _noext(rel)
    ids = {noext, _stem(rel)}
    for prefix in ("lib/", "lib64/", "blib/lib/"):
        if noext.startswith(prefix):
            tail = noext[len(prefix):]
            ids.add(tail)
            ids.add(tail.replace("/", "::"))
    for pkg in PL_PACKAGE_RE.findall(text):
        ids.add(pkg)
        ids.add(pkg.replace("::", "/"))
    return ids


def _pl_refs(rel: str, text: str, ctx: dict[str, Any]) -> set[str]:
    refs = set(PL_USE_RE.findall(text))
    extra = {item.replace("::", "/") for item in refs}
    return refs | extra


def _pl_entry(rel: str, text: str) -> bool:
    return rel.endswith(".pl") or _in_dirs(rel, {"bin", "script", "scripts", "t"})


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


def _test_by_dir_or_suffix(*suffixes: str, dirs: set[str] | None = None) -> Callable[[str], bool]:
    dirset = dirs or {"test", "tests", "spec", "specs", "__tests__", "testing"}

    def check(rel: str) -> bool:
        return rel.endswith(tuple(suffixes)) if suffixes and rel.endswith(tuple(suffixes)) else _in_dirs(rel, dirset)

    return check


LANGS: dict[str, LangSpec] = {
    "go": LangSpec(
        key="go", name="Go", suffixes=(".go",), precision="path",
        ids=_go_ids, refs=_go_refs, entry=_go_entry,
        is_test=lambda rel: rel.endswith("_test.go"),
        exports=lambda text: list(dict.fromkeys(GO_EXPORT_RE.findall(text))),
        validate=["go build ./...", "go vet ./...", "go test ./..."],
        manifests=["go.mod"], context=_go_ctx,
    ),
    "rust": LangSpec(
        key="rust", name="Rust", suffixes=(".rs",), precision="path",
        ids=_rust_ids, refs=_rust_refs, entry=_rust_entry,
        is_test=_test_by_dir_or_suffix(dirs={"tests", "benches"}),
        exports=lambda text: list(dict.fromkeys(RUST_EXPORT_RE.findall(text))),
        validate=["cargo check --all-targets", "cargo test"],
        manifests=["Cargo.toml"], context=lambda root: {"src_root": "src"},
    ),
    "java": LangSpec(
        key="java", name="Java", suffixes=(".java",), precision="name",
        ids=_jvm_ids, refs=_jvm_refs, entry=_jvm_entry,
        is_test=lambda rel: "/test/" in f"/{rel}" or rel.endswith(("Test.java", "Tests.java", "IT.java")),
        exports=_jvm_exports,
        validate=["mvn -q -DskipTests compile && mvn -q test", "./gradlew test"],
        manifests=["pom.xml", "build.gradle", "build.gradle.kts"],
    ),
    "kotlin": LangSpec(
        key="kotlin", name="Kotlin", suffixes=(".kt", ".kts"), precision="name",
        ids=_jvm_ids, refs=_jvm_refs, entry=_jvm_entry,
        is_test=lambda rel: "/test/" in f"/{rel}" or rel.endswith(("Test.kt", "Tests.kt")),
        exports=_jvm_exports,
        validate=["./gradlew build", "./gradlew test"],
        manifests=["build.gradle.kts", "settings.gradle.kts"],
    ),
    "scala": LangSpec(
        key="scala", name="Scala", suffixes=(".scala",), precision="name",
        ids=_jvm_ids, refs=_jvm_refs, entry=_jvm_entry,
        is_test=lambda rel: "/test/" in f"/{rel}" or rel.endswith(("Spec.scala", "Test.scala", "Suite.scala")),
        exports=_jvm_exports,
        validate=["sbt compile", "sbt test"],
        manifests=["build.sbt"],
    ),
    "csharp": LangSpec(
        key="csharp", name="C#", suffixes=(".cs",), precision="name",
        ids=_cs_ids, refs=_cs_refs, entry=_cs_entry,
        is_test=lambda rel: ".Tests/" in rel or ".Test/" in rel or rel.endswith(("Tests.cs", "Test.cs")),
        exports=_cs_exports,
        validate=["dotnet build", "dotnet test"],
        manifests=["*.csproj", "*.sln"],
    ),
    "ruby": LangSpec(
        key="ruby", name="Ruby", suffixes=(".rb", ".rake"), precision="path",
        ids=_rb_ids, refs=_rb_refs, entry=_rb_entry,
        is_test=lambda rel: _in_dirs(rel, {"spec", "test", "features"}) or rel.endswith(("_spec.rb", "_test.rb")),
        exports=lambda text: list(dict.fromkeys(RB_EXPORT_RE.findall(text))),
        validate=["bundle exec rubocop --fail-level E", "bundle exec rspec || bundle exec rake test"],
        manifests=["Gemfile"],
    ),
    "php": LangSpec(
        key="php", name="PHP", suffixes=(".php",), precision="name",
        ids=_php_ids, refs=_php_refs, entry=_php_entry,
        is_test=lambda rel: _in_dirs(rel, {"tests", "test"}) or rel.endswith("Test.php"),
        exports=lambda text: list(dict.fromkeys(PHP_EXPORT_RE.findall(text))),
        validate=["composer validate", "vendor/bin/phpunit"],
        manifests=["composer.json"],
    ),
    "swift": LangSpec(
        key="swift", name="Swift", suffixes=(".swift",), precision="name",
        ids=_swift_ids, refs=_swift_refs, entry=_swift_entry,
        is_test=lambda rel: _in_dirs(rel, {"tests", "uitests"}) or rel.endswith("Tests.swift"),
        exports=_swift_exports,
        validate=["swift build", "swift test"],
        manifests=["Package.swift"],
    ),
    "dart": LangSpec(
        key="dart", name="Dart", suffixes=(".dart",), precision="path",
        ids=_dart_ids, refs=_dart_refs, entry=_dart_entry,
        is_test=lambda rel: _in_dirs(rel, {"test", "integration_test"}) or rel.endswith("_test.dart"),
        exports=_dart_exports,
        validate=["dart analyze", "flutter test || dart test"],
        manifests=["pubspec.yaml"], context=_dart_ctx,
    ),
    "elixir": LangSpec(
        key="elixir", name="Elixir", suffixes=(".ex", ".exs"), precision="name",
        ids=_ex_ids, refs=_ex_refs, entry=_ex_entry,
        is_test=lambda rel: _in_dirs(rel, {"test"}) or rel.endswith("_test.exs"),
        exports=lambda text: list(dict.fromkeys(EX_EXPORT_RE.findall(text))),
        validate=["mix compile --warnings-as-errors", "mix test"],
        manifests=["mix.exs"],
    ),
    "c": LangSpec(
        key="c", name="C/C++", suffixes=(".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh", ".hxx", ".inl"), precision="path",
        ids=_c_ids, refs=_c_refs, entry=_c_entry,
        is_test=lambda rel: _in_dirs(rel, {"test", "tests"}) or rel.endswith(("_test.c", "_test.cc", "_test.cpp")),
        exports=_c_exports,
        validate=["cmake --build build", "ctest --test-dir build"],
        manifests=["CMakeLists.txt", "Makefile", "meson.build"],
    ),
    "lua": LangSpec(
        key="lua", name="Lua", suffixes=(".lua",), precision="path",
        ids=_lua_ids, refs=_lua_refs, entry=_lua_entry,
        is_test=lambda rel: _in_dirs(rel, {"spec", "tests", "test"}) or rel.endswith("_spec.lua"),
        exports=lambda text: [a or b for a, b in LUA_EXPORT_RE.findall(text)],
        validate=["luacheck .", "busted"],
        manifests=["*.rockspec", ".luarc.json"],
    ),
    "perl": LangSpec(
        key="perl", name="Perl", suffixes=(".pm", ".pl"), precision="path",
        ids=_pl_ids, refs=_pl_refs, entry=_pl_entry,
        is_test=lambda rel: _in_dirs(rel, {"t"}) or rel.endswith(".t"),
        exports=lambda text: list(dict.fromkeys(PL_EXPORT_RE.findall(text))),
        validate=["perl -c", "prove -l t"],
        manifests=["cpanfile", "Makefile.PL"],
    ),
}

SUFFIX_TO_LANG: dict[str, str] = {}
for _spec in LANGS.values():
    for _suffix in _spec.suffixes:
        SUFFIX_TO_LANG.setdefault(_suffix, _spec.key)


def lang_for_suffix(suffix: str) -> str | None:
    return SUFFIX_TO_LANG.get(suffix)


def all_suffixes() -> tuple[str, ...]:
    return tuple(SUFFIX_TO_LANG)


# --------------------------------------------------------------------------- #
# Facts + graph
# --------------------------------------------------------------------------- #

FACTS_VERSION = 2


def extract_facts(spec: LangSpec, rel: str, text: str, ctx: dict[str, Any]) -> dict[str, Any]:
    tokens = set(TOKEN_RE.findall(text))
    if len(tokens) > MAX_TOKENS:
        tokens = set(sorted(tokens)[:MAX_TOKENS])
    decorated, bases = decorations_and_bases(text)
    return {
        "v": FACTS_VERSION,
        "lang": spec.key,
        "ids": sorted(spec.ids(rel, text, ctx)),
        "refs": sorted(spec.refs(rel, text, ctx)),
        "tokens": sorted(tokens),
        "exports": list(spec.exports(text))[:200] if spec.exports else [],
        "entry": bool(spec.entry(rel, text)),
        "test": bool(spec.is_test(rel)),
        "decorated": {k: list(v) for k, v in decorated.items()},
        "bases": {k: list(v) for k, v in bases.items()},
        "privates": unused_privates(spec.key, text),
    }


def build_poly_graph(
    root: Path, files: list[Path], cache: FactsCache | None = None
) -> dict[str, PolyFile]:
    ctx_by_lang: dict[str, dict[str, Any]] = {}
    out: dict[str, PolyFile] = {}
    for path in files:
        spec_key = lang_for_suffix(path.suffix)
        if spec_key is None:
            continue
        spec = LANGS[spec_key]
        if spec_key not in ctx_by_lang:
            ctx_by_lang[spec_key] = spec.context(root) if spec.context else {}
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        text = _read(path)
        digest = sha256_text(text)
        facts = cache.get(rel, digest) if cache is not None else None
        if facts is None or facts.get("v") != FACTS_VERSION or facts.get("lang") != spec_key:
            facts = extract_facts(spec, rel, text, ctx_by_lang[spec_key])
            if cache is not None:
                cache.put(rel, digest, facts)
        out[rel] = PolyFile(
            rel=rel,
            lang=spec_key,
            ids=set(facts["ids"]),
            refs=set(facts["refs"]),
            tokens=set(facts["tokens"]),
            exports=list(facts["exports"]),
            entry=bool(facts["entry"]),
            test=bool(facts["test"]),
            digest=digest,
            decorated={k: list(v) for k, v in facts.get("decorated", {}).items()},
            bases={k: list(v) for k, v in facts.get("bases", {}).items()},
            privates={k: int(v) for k, v in facts.get("privates", {}).items()},
        )
    return out


def referenced_files(files: dict[str, PolyFile]) -> dict[str, list[str]]:
    """Map rel → list of referrers (other files) using ids/refs and, for
    name-precision languages, token matches on declared identifiers."""
    id_index: dict[str, list[str]] = {}
    for f in files.values():
        for ident in f.ids:
            id_index.setdefault(ident, []).append(f.rel)
    referrers: dict[str, list[str]] = {rel: [] for rel in files}
    for f in files.values():
        for ref in f.refs:
            targets = list(id_index.get(ref, []))
            if ref.endswith(".*"):
                prefix = ref[:-1]
                for ident, rels in id_index.items():
                    if ident.startswith(prefix) and not ident.endswith(".*"):
                        targets.extend(rels)
            for candidate in (ref + "/index", ref + "/init", ref + "/mod"):
                targets.extend(id_index.get(candidate, []))
            for target in targets:
                if target != f.rel:
                    referrers[target].append(f.rel)
    # Name precision: declared type/module names appearing as tokens elsewhere.
    name_langs = {f.lang for f in files.values() if LANGS[f.lang].precision == "name"}
    if name_langs:
        token_index = _token_index(files, name_langs)
        for f in files.values():
            if f.lang not in name_langs:
                continue
            names = {i for i in f.ids if len(i) >= 3 and not any(c in i for c in "/.\\")}
            hits: set[str] = set()
            for name in names:
                hits.update(token_index.get((f.lang, name), ()))
            hits.discard(f.rel)
            referrers[f.rel].extend(sorted(hits))
    return referrers


def _token_index(files: dict[str, PolyFile], langs: set[str]) -> dict[tuple[str, str], set[str]]:
    index: dict[tuple[str, str], set[str]] = {}
    for f in files.values():
        if f.lang not in langs:
            continue
        for token in f.tokens:
            index.setdefault((f.lang, token), set()).add(f.rel)
    return index


def export_used_elsewhere(files: dict[str, PolyFile], rel: str, symbol: str) -> bool:
    for other in files.values():
        if other.rel != rel and symbol in other.tokens:
            return True
    return False


class ExportIndex:
    """token → files containing it; answers export_used_elsewhere in O(1)."""

    def __init__(self, files: dict[str, PolyFile]) -> None:
        self._index: dict[str, set[str]] = {}
        for f in files.values():
            for token in f.tokens:
                self._index.setdefault(token, set()).add(f.rel)

    def used_elsewhere(self, rel: str, symbol: str) -> bool:
        owners = self._index.get(symbol)
        return bool(owners) and any(o != rel for o in owners)
