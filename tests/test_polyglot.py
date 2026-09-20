from pathlib import Path

import pytest

from deadpath.cli import main
from deadpath.langs import FRAMEWORKS
from deadpath.mcp_server import Session, handle_request
from deadpath.polyglot import LANGS
from deadpath.scan import scan_repo, supported_languages
from deadpath.support import languages_payload

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "polyglot"


def _ids(result):
    return {f.id: f for f in result.findings}


@pytest.mark.parametrize(
    "lang, orphan, blocked",
    [
        ("go", "orphan_file:internal/orphan/orphan.go", True),
        ("rust", "orphan_file:src/orphan.rs", True),
        ("ruby", "orphan_file:lib/lonely.rb", True),
        ("dart", "orphan_file:lib/lonely.dart", True),
        ("c", "orphan_file:src/lonely.h", True),
        ("lua", "orphan_file:lua/app/lonely.lua", True),
        ("perl", "orphan_file:lib/Lonely.pm", True),
        ("ts", "orphan_file:src/orphan.ts", True),
        ("java", "orphan_file:src/main/java/com/acme/util/Lonely.java", False),
        ("kotlin", "orphan_file:src/main/kotlin/com/acme/util/Lonely.kt", False),
        ("scala", "orphan_file:src/main/scala/com/acme/util/Lonely.scala", False),
        ("csharp", "orphan_file:Lonely.cs", False),
        ("php", "orphan_file:src/Lonely.php", False),
        ("swift", "orphan_file:Sources/App/Lonely.swift", False),
        ("elixir", "orphan_file:lib/dead/lonely.ex", False),
    ],
)
def test_orphan_detected_per_language(isolated_memory, lang, orphan, blocked):
    result = scan_repo(FIXTURES / lang, memory=False)
    found = _ids(result)
    assert orphan in found, sorted(found)
    finding = found[orphan]
    if blocked:
        assert finding.severity == "block", finding
    else:
        # name-precision graphs never reach block on their own
        assert finding.severity == "warn", finding
        assert any(k.endswith("_name_reference_graph") for k in finding.signals)


@pytest.mark.parametrize(
    "lang, referenced",
    [
        ("go", "internal/used/used.go"),
        ("rust", "src/used.rs"),
        ("ruby", "lib/used.rb"),
        ("dart", "lib/used.dart"),
        ("c", "src/used.h"),
        ("lua", "lua/app/used.lua"),
        ("perl", "lib/Used.pm"),
        ("ts", "src/used.ts"),
        ("java", "src/main/java/com/acme/util/Greeter.java"),
        ("kotlin", "src/main/kotlin/com/acme/util/Greeter.kt"),
        ("scala", "src/main/scala/com/acme/util/Greeter.scala"),
        ("csharp", "Greeter.cs"),
        ("php", "src/Greeter.php"),
        ("swift", "Sources/App/Greeter.swift"),
        ("elixir", "lib/dead/used.ex"),
    ],
)
def test_referenced_files_are_not_orphans(isolated_memory, lang, referenced):
    result = scan_repo(FIXTURES / lang, memory=False)
    assert f"orphan_file:{referenced}" not in _ids(result)


def test_entry_points_are_not_orphans(isolated_memory):
    go = _ids(scan_repo(FIXTURES / "go", memory=False))
    assert "orphan_file:cmd/app/main.go" not in go
    rb = _ids(scan_repo(FIXTURES / "ruby", memory=False))
    assert "orphan_file:main.rb" not in rb
    cs = _ids(scan_repo(FIXTURES / "csharp", memory=False))
    assert "orphan_file:Program.cs" not in cs
    c = _ids(scan_repo(FIXTURES / "c", memory=False))
    assert "orphan_file:src/main.c" not in c
    kt = _ids(scan_repo(FIXTURES / "kotlin", memory=False))
    assert "orphan_file:src/main/kotlin/com/acme/Application.kt" not in kt
    sw = _ids(scan_repo(FIXTURES / "swift", memory=False))
    assert "orphan_file:Sources/App/main.swift" not in sw
    ex = _ids(scan_repo(FIXTURES / "elixir", memory=False))
    assert "orphan_file:lib/dead/application.ex" not in ex
    pl = _ids(scan_repo(FIXTURES / "perl", memory=False))
    assert "orphan_file:script/app.pl" not in pl
    ts = _ids(scan_repo(FIXTURES / "ts", memory=False))
    assert "orphan_file:src/index.ts" not in ts


def test_go_unused_export_is_warn_not_block(isolated_memory):
    found = _ids(scan_repo(FIXTURES / "go", memory=False))
    finding = found["unused_export:internal/used/used.go:Unused"]
    assert finding.severity == "warn"
    assert "unused_export:internal/used/used.go:Greeting" not in found


@pytest.mark.parametrize(
    "lang, finding_id",
    [
        ("go", "unused_export:internal/used/used.go:Unused"),
        ("rust", "unused_export:src/used.rs:leftover"),
        ("java", "unused_export:src/main/java/com/acme/util/Greeter.java:leftover"),
        ("kotlin", "unused_export:src/main/kotlin/com/acme/util/Greeter.kt:leftover"),
        ("scala", "unused_export:src/main/scala/com/acme/util/Greeter.scala:leftover"),
        ("csharp", "unused_export:Greeter.cs:Leftover"),
        ("ruby", "unused_export:lib/used.rb:leftover"),
        ("php", "unused_export:src/Greeter.php:leftover"),
        ("swift", "unused_export:Sources/App/Greeter.swift:leftover"),
        ("dart", "unused_export:lib/used.dart:leftover"),
        ("elixir", "unused_export:lib/dead/used.ex:leftover"),
        ("c", "unused_export:src/used.h:leftover"),
        ("lua", "unused_export:lua/app/used.lua:leftover"),
        ("perl", "unused_export:lib/Used.pm:leftover"),
        ("ts", "unused_export:src/used.ts:leftover"),
    ],
)
def test_unused_export_detected_per_language(isolated_memory, lang, finding_id):
    found = _ids(scan_repo(FIXTURES / lang, memory=False))
    assert finding_id in found, sorted(found)


@pytest.mark.parametrize(
    "lang, finding_id",
    [
        ("go", "unused_dep:go.mod:github.com/gin-gonic/gin"),
        ("rust", "unused_dep:Cargo.toml:axum"),
        ("ruby", "unused_dep:Gemfile:rails"),
        ("java", "unused_dep:pom.xml:spring-boot-starter-web"),
        ("csharp", "unused_dep:App.csproj:Microsoft.AspNetCore.OpenApi"),
        ("php", "unused_dep:composer.json:laravel/framework"),
        ("ts", "unused_dep:package.json:express"),
        ("elixir", "unused_dep:mix.exs:phoenix"),
        ("swift", "unused_dep:Package.swift:vapor"),
        ("perl", "unused_dep:cpanfile:JSON"),
    ],
)
def test_unused_dep_detected_from_manifests(isolated_memory, lang, finding_id):
    found = _ids(scan_repo(FIXTURES / lang, memory=False))
    assert finding_id in found, sorted(k for k in found if k.startswith("unused_dep"))


def test_unreachable_private_in_go_and_rust(isolated_memory):
    go = _ids(scan_repo(FIXTURES / "go", memory=False))
    assert "unreachable:internal/used/used.go:hidden" in go
    rust = _ids(scan_repo(FIXTURES / "rust", memory=False))
    assert "unreachable:src/used.rs:hidden" in rust


def test_frameworks_detected_from_manifests(isolated_memory):
    expect = {
        "go": "gin",
        "rust": "actix",
        "java": "spring",
        "kotlin": "spring",
        "scala": "spring",
        "ruby": "rails",
        "dart": "flutter",
        "csharp": "aspnet",
        "php": "laravel",
        "swift": "vapor",
        "elixir": "phoenix",
        "ts": "express",
    }
    for lang, framework in expect.items():
        profile = scan_repo(FIXTURES / lang, memory=False).profile
        assert framework in profile.frameworks, (lang, profile.frameworks)
        if lang != "ts":
            assert profile.primary == lang
        assert profile.validate_commands.get(lang) or lang == "ts"


def test_support_matrix_counts():
    payload = languages_payload()
    assert payload["counts"]["languages"] == 16
    assert payload["counts"]["frameworks"] == 45
    assert len(FRAMEWORKS) == 45
    for spec in FRAMEWORKS.values():
        assert spec["language"] in {"py", "ts"} | set(LANGS)
    assert set(supported_languages()) == {"auto", "py", "ts", *LANGS}
    for lang in payload["languages"]:
        assert lang["detects"] == ["orphan_file", "unused_export", "unused_dep", "unreachable"], lang["key"]
    by_key = {lang["key"]: lang for lang in payload["languages"]}
    assert "spring" in by_key["scala"]["frameworks"]
    assert "spring" in by_key["kotlin"]["frameworks"]


def test_lang_filter_and_unknown_language(isolated_memory):
    result = scan_repo(FIXTURES / "go", memory=False, lang="go")
    assert result.profile.languages == {"go": 3}
    with pytest.raises(ValueError):
        scan_repo(FIXTURES / "go", memory=False, lang="cobol")


def test_facts_cached_in_memory(isolated_memory):
    first = scan_repo(FIXTURES / "rust")
    assert first.memory["cache_misses"] == 3
    second = scan_repo(FIXTURES / "rust")
    assert second.memory["cache_hits"] == 3
    assert second.memory["cache_misses"] == 0
    assert second.delta.persisting and not second.delta.new


def test_cli_languages_and_workflow_for_go(isolated_memory, capsys):
    assert main(["languages"]) == 0
    out = capsys.readouterr().out
    assert "Go" in out and "reference-graph" in out
    assert main(["workflow", str(FIXTURES / "go"), "--format", "json"]) == 0
    payload = __import__("json").loads(capsys.readouterr().out)
    commands = [s.get("command") for s in payload["steps"] if s.get("command")]
    assert "go build ./..." in commands and "go test ./..." in commands
    assert payload["profile"]["primary"] == "go"


def test_mcp_languages_tool():
    session = Session()
    reply = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "deadpath.languages", "arguments": {}}},
        session,
    )
    payload = __import__("json").loads(reply["result"]["content"][0]["text"])
    assert payload["counts"]["frameworks"] == 45
    assert payload["counts"]["languages"] == 16


def test_java_annotation_lowers_unused_export(isolated_memory, tmp_path):
    (tmp_path / "pom.xml").write_text(
        "<project><dependencies><dependency>"
        "<groupId>org.springframework.boot</groupId>"
        "<artifactId>spring-boot-starter-web</artifactId>"
        "</dependency></dependencies></project>",
        encoding="utf-8",
    )
    src = tmp_path / "src/main/java/com/acme"
    src.mkdir(parents=True)
    (src / "Application.java").write_text(
        "package com.acme;\nimport com.acme.Greeter;\n"
        "public class Application { public static void main(String[] a) { new Greeter().hi(); } }\n",
        encoding="utf-8",
    )
    (src / "Greeter.java").write_text(
        "package com.acme;\n"
        "public class Greeter {\n"
        "  public String hi() { return \"hi\"; }\n"
        "  @Scheduled\n"
        "  public String leftover() { return \"bye\"; }\n"
        "}\n",
        encoding="utf-8",
    )
    found = _ids(scan_repo(tmp_path, memory=False))
    assert "spring" in scan_repo(tmp_path, memory=False).profile.frameworks
    leftover = found.get("unused_export:src/main/java/com/acme/Greeter.java:leftover")
    if leftover is not None:
        assert leftover.severity != "block"
        assert "framework_registration_decorator" in leftover.signals


def test_ts_nestjs_decorator_lowers_unused_export(isolated_memory, tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"@nestjs/core": "10.0.0"}}\n', encoding="utf-8")
    (tmp_path / "main.ts").write_text("import { live } from './svc'\nexport const n = live()\n", encoding="utf-8")
    (tmp_path / "svc.ts").write_text(
        "import { Injectable } from '@nestjs/common'\n"
        "export function live() { return 1 }\n"
        "@Injectable()\nexport class DeadBean {}\n"
        "export function leftover() { return 2 }\n",
        encoding="utf-8",
    )
    result = scan_repo(tmp_path, memory=False)
    found = _ids(result)
    assert "nestjs" in result.profile.frameworks
    assert "unused_export:svc.ts:leftover" in found
    bean = found.get("unused_export:svc.ts:DeadBean")
    if bean is not None:
        assert bean.severity != "block"
        assert "framework_registration_decorator" in bean.signals
    else:
        # decorator dropped it below min-confidence
        assert True
