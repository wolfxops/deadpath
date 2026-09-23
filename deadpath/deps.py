"""Declared-dependency vs import matching for every package ecosystem.

Python keeps its own AST-based unused_dep path in ``scan._scan_python_deps``.
This module covers the other 15 languages' manifests so unused_dep is not a
Python-only finding.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from deadpath.graph import TS_IMPORT_RE
from deadpath.polyglot import LANGS, lang_for_suffix

NODE_BUILTINS = {
    "assert", "async_hooks", "buffer", "child_process", "cluster", "console",
    "constants", "crypto", "dgram", "diagnostics_channel", "dns", "domain",
    "events", "fs", "http", "http2", "https", "inspector", "module", "net",
    "os", "path", "perf_hooks", "process", "punycode", "querystring", "readline",
    "repl", "stream", "string_decoder", "timers", "tls", "trace_events", "tty",
    "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib",
}
SKIP_DEPS = {
    "setuptools", "wheel", "pip", "flutter", "dart", "kotlin-stdlib",
    "microsoft.net.sdk", "microsoft.net.sdk.web",
}


def declared_manifest_deps(root: Path) -> list[tuple[str, str]]:
    """Return (package_name, manifest_rel) for non-Python ecosystems."""
    found: list[tuple[str, str]] = []
    found.extend(_package_json(root))
    found.extend(_go_mod(root))
    found.extend(_cargo(root))
    found.extend(_gemfile(root))
    found.extend(_composer(root))
    found.extend(_maven(root))
    found.extend(_gradle(root))
    found.extend(_sbt(root))
    found.extend(_csproj(root))
    found.extend(_pubspec(root))
    found.extend(_mix(root))
    found.extend(_swift_package(root))
    found.extend(_cpanfile(root))
    found.extend(_rockspec(root))
    found.extend(_vcpkg(root))
    return _dedupe(found)


def imported_names(root: Path, ts_files: list[Path], other_files: list[Path]) -> set[str]:
    names: set[str] = set()
    for path in ts_files:
        text = _read(path)
        for spec in TS_IMPORT_RE.findall(text):
            if spec.startswith((".", "/", "node:")):
                continue
            names.update(_spec_variants(spec))
    ctx_by_lang: dict[str, dict] = {}
    for path in other_files:
        key = lang_for_suffix(path.suffix)
        if key is None:
            continue
        spec = LANGS[key]
        if key not in ctx_by_lang:
            ctx_by_lang[key] = spec.context(root) if spec.context else {}
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = path.as_posix()
        text = _read(path)
        refs = spec.refs(rel, text, ctx_by_lang[key])
        names.update(refs)
        for item in refs:
            names.update(_spec_variants(item))
        if key == "rust":
            names.update(re.findall(r"^\s*use\s+([a-z][\w]*)::", text, re.MULTILINE))
            names.update(re.findall(r"^\s*extern\s+crate\s+(\w+)", text, re.MULTILINE))
        elif key in {"java", "kotlin", "scala"}:
            names.update(re.findall(r"^\s*import\s+(?:static\s+)?([\w.]+)", text, re.MULTILINE))
        elif key == "php":
            names.update(re.findall(r"^\s*use\s+([\w\\]+)", text, re.MULTILINE))
        elif key in {"swift", "elixir"}:
            names.update(re.findall(r"^\s*(?:import|use|alias|require)\s+([A-Z][\w.]*)", text, re.MULTILINE))
        elif key == "dart":
            names.update(re.findall(r"""(?:import|export)\s+['"](package:[\w/]+)""", text))
        elif key == "csharp":
            names.update(re.findall(r"^\s*(?:global\s+)?using\s+(?:static\s+)?([\w.]+)", text, re.MULTILINE))
        elif key == "ruby":
            names.update(re.findall(r"""^\s*require(?:_relative)?\s+['"]([^'"]+)""", text, re.MULTILINE))
    expanded: set[str] = set()
    for name in names:
        expanded.update(_spec_variants(name))
    return expanded


def dep_is_used(dep: str, imported: set[str]) -> bool:
    if dep.lower() in SKIP_DEPS:
        return True
    candidates = _dep_names(dep)
    imported_l = {i.lower().replace("\\", "/") for i in imported if i}
    for cand in candidates:
        cl = cand.lower().replace("\\", "/")
        if not cl or cl in NODE_BUILTINS:
            continue
        for imp in imported_l:
            if imp == cl or imp.startswith(cl + "/") or imp.startswith(cl + ".") or imp.startswith(cl + ":"):
                return True
            if cl.startswith(imp + "/") or cl.startswith(imp + "."):
                if imp.count("/") + imp.count(".") >= 1 and len(imp) >= 4:
                    return True
    return False


def _dep_names(dep: str) -> set[str]:
    names = {dep, dep.replace("-", "_"), dep.replace("_", "-")}
    if "/" in dep:
        names.add(dep.rsplit("/", 1)[-1])
        names.add(dep.rsplit("/", 1)[-1].replace("-", "_"))
    if ":" in dep:
        group, artifact = dep.split(":", 1)
        names.add(group)
        names.add(artifact)
        names.add(artifact.replace("-", "."))
    # Elixir/Swift/Ruby often import a capitalized form of the hex/gem name.
    parts = re.split(r"[-_/]", dep)
    if parts:
        names.add("".join(p.capitalize() for p in parts if p))
        names.add(parts[-1].capitalize())
    low = dep.lower()
    aliases = {
        "laravel/framework": ["illuminate"],
        "symfony/framework-bundle": ["symfony"],
        "symfony/symfony": ["symfony"],
        "spring-boot-starter-web": ["org.springframework"],
        "spring-boot-starter": ["org.springframework"],
        "org.springframework.boot": ["org.springframework"],
        "microsoft.aspnetcore.openapi": ["microsoft.aspnetcore"],
        "github.com/gin-gonic/gin": ["github.com/gin-gonic/gin"],
    }
    names.update(aliases.get(low, []))
    return {n for n in names if n}


def _spec_variants(spec: str) -> set[str]:
    if not spec:
        return set()
    out = {spec, spec.replace("\\", "/")}
    if spec.startswith("@"):
        segs = spec.split("/")
        out.add("/".join(segs[:2]) if len(segs) >= 2 else spec)
    elif spec.startswith("package:"):
        out.add(spec)
        out.add(spec.split("/")[0].split(":", 1)[-1])
        rest = spec[len("package:") :]
        out.add(rest.split("/")[0])
    else:
        out.add(spec.split("/")[0].split(".")[0])
        out.add(spec.split(".")[0])
    return {s for s in out if s}


def _package_json(root: Path) -> list[tuple[str, str]]:
    path = root / "package.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(_read(path) or "{}")
    except json.JSONDecodeError:
        return []
    deps = {
        **data.get("dependencies", {}),
        **data.get("optionalDependencies", {}),
        **data.get("peerDependencies", {}),
        **data.get("devDependencies", {}),
    }
    return [(name, "package.json") for name in deps]


def _go_mod(root: Path) -> list[tuple[str, str]]:
    path = root / "go.mod"
    if not path.is_file():
        return []
    out: list[tuple[str, str]] = []
    for raw in _read(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("//") or "// indirect" in raw:
            continue
        match = re.match(r"^(?:require\s+)?([\w./-]+)\s+v[\w.-]+", line)
        if match and match.group(1) not in {"require", "module", "go", "exclude", "replace"}:
            out.append((match.group(1), "go.mod"))
    return out


def _cargo(root: Path) -> list[tuple[str, str]]:
    path = root / "Cargo.toml"
    if not path.is_file():
        return []
    out: list[tuple[str, str]] = []
    section = ""
    for raw in _read(path).splitlines():
        stripped = raw.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.strip("[]")
            continue
        if section not in {"dependencies", "dev-dependencies", "build-dependencies"} and not section.endswith(".dependencies"):
            continue
        match = re.match(r"^([A-Za-z0-9_-]+)\s*=", stripped)
        if match:
            out.append((match.group(1), "Cargo.toml"))
    return out


def _gemfile(root: Path) -> list[tuple[str, str]]:
    path = root / "Gemfile"
    if not path.is_file():
        return []
    return [(m, "Gemfile") for m in re.findall(r"""^\s*gem\s+['"]([\w-]+)""", _read(path), re.MULTILINE)]


def _composer(root: Path) -> list[tuple[str, str]]:
    path = root / "composer.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(_read(path) or "{}")
    except json.JSONDecodeError:
        return []
    deps = {**data.get("require", {}), **data.get("require-dev", {})}
    return [(name, "composer.json") for name in deps if name != "php" and not name.startswith("ext-")]


def _maven(root: Path) -> list[tuple[str, str]]:
    path = root / "pom.xml"
    if not path.is_file():
        return []
    text = _read(path)
    out: list[tuple[str, str]] = []
    for block in re.findall(r"<dependency>(.*?)</dependency>", text, re.DOTALL):
        artifact = re.search(r"<artifactId>([\w.-]+)</artifactId>", block)
        if artifact:
            out.append((artifact.group(1), "pom.xml"))
    return _dedupe(out)


def _gradle(root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for gradle in list(root.glob("build.gradle*"))[:8]:
        text = _read(gradle)
        rel = gradle.name
        for coord in re.findall(r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*\(?['"]([\w.-]+:[\w.-]+)""", text):
            out.append((coord.split(":")[-1], rel))
        for coord in re.findall(r"""['"]([\w.-]+:[\w.-]+):[\w.-]+['"]""", text):
            out.append((coord.split(":")[-1], rel))
    return _dedupe(out)


def _sbt(root: Path) -> list[tuple[str, str]]:
    path = root / "build.sbt"
    if not path.is_file():
        return []
    out: list[tuple[str, str]] = []
    for _group, artifact in re.findall(r'"([\w.-]+)"\s*%%?\s*"([\w.-]+)"', _read(path)):
        out.append((artifact, "build.sbt"))
    return _dedupe(out)


def _csproj(root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for proj in list(root.glob("*.csproj")) + list(root.glob("*/*.csproj"))[:20]:
        rel = proj.name
        try:
            rel = proj.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = proj.name
        for name in re.findall(r'PackageReference\s+Include="([\w.]+)"', _read(proj)):
            out.append((name, rel))
    return out


def _pubspec(root: Path) -> list[tuple[str, str]]:
    path = root / "pubspec.yaml"
    if not path.is_file():
        return []
    out: list[tuple[str, str]] = []
    section = ""
    for raw in _read(path).splitlines():
        if raw.startswith("dependencies:") or raw.startswith("dev_dependencies:"):
            section = raw.split(":", 1)[0]
            continue
        if section and raw[:1] not in {" ", "\t"} and raw.strip():
            section = ""
            continue
        if section != "dependencies" and section != "dev_dependencies":
            continue
        match = re.match(r"^\s{2}([\w_]+)\s*:", raw)
        if match and match.group(1) not in {"sdk", "path", "git", "hosted"}:
            out.append((match.group(1), "pubspec.yaml"))
    return out


def _mix(root: Path) -> list[tuple[str, str]]:
    path = root / "mix.exs"
    if not path.is_file():
        return []
    return [(m, "mix.exs") for m in re.findall(r"\{:(\w+),", _read(path))]


def _swift_package(root: Path) -> list[tuple[str, str]]:
    path = root / "Package.swift"
    if not path.is_file():
        return []
    text = _read(path)
    names = re.findall(r"""\.package\([^)]*?(?:url:\s*)?["'][^"']+/([\w.-]+?)(?:\.git)?["']""", text)
    names += [m for m in re.findall(r"""name:\s*["'](\w+)["']""", text) if m.lower() not in {"app", "target"}]
    return [(n.rstrip(".git"), "Package.swift") for n in names]


def _cpanfile(root: Path) -> list[tuple[str, str]]:
    path = root / "cpanfile"
    if not path.is_file():
        return []
    return [(m.replace("::", "-"), "cpanfile") for m in re.findall(r"""requires\s+['"]([\w:]+)""", _read(path))]


def _rockspec(root: Path) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for path in list(root.glob("*.rockspec"))[:8]:
        for name in re.findall(r"""["']([\w-]+)["']\s*,\s*["'][\d.>=<~]+["']""", _read(path)):
            out.append((name, path.name))
    return out


def _vcpkg(root: Path) -> list[tuple[str, str]]:
    path = root / "vcpkg.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(_read(path) or "{}")
    except json.JSONDecodeError:
        return []
    deps = data.get("dependencies", [])
    names: list[str] = []
    for item in deps:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and "name" in item:
            names.append(str(item["name"]))
    return [(n, "vcpkg.json") for n in names]


def _dedupe(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for item in items:
        if item in seen or not item[0]:
            continue
        seen.add(item)
        out.append(item)
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
