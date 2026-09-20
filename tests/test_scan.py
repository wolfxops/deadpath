from __future__ import annotations

from pathlib import Path

from deadpath.mcp_server import Session, handle_request
from deadpath.scan import Finding, redact_text, scan_path

ROOT = Path(__file__).resolve().parents[1]
DEADAPP = ROOT / "fixtures" / "deadapp"


def test_mock_scan_orphan_and_unused_export() -> None:
    findings = scan_path(DEADAPP, mock=True, lang="py")
    orphan = [f for f in findings if f.kind == "orphan_file" and f.path.endswith("pkg/orphan.py")]
    unused = [f for f in findings if f.kind == "unused_export" and f.symbol == "dead_symbol"]
    assert orphan, findings
    assert orphan[0].severity == "block"
    assert unused, findings
    assert unused[0].severity == "block"
    assert unused[0].path.replace("\\", "/").endswith("pkg/exports.py")


def test_live_symbol_not_reported() -> None:
    findings = scan_path(DEADAPP, mock=False, lang="py")
    assert not any(f.symbol == "live_symbol" for f in findings)
    assert not any(f.symbol == "helper" for f in findings)
    assert not any(f.path.endswith("pkg/used.py") and f.kind == "orphan_file" for f in findings)
    assert not any(f.path.endswith("pkg/app.py") and f.kind == "orphan_file" for f in findings)


def test_real_scan_matches_fixture_without_mock() -> None:
    findings = scan_path(DEADAPP, mock=False, lang="py")
    assert any(f.kind == "orphan_file" and f.path.endswith("pkg/orphan.py") for f in findings)
    assert any(f.kind == "unused_export" and f.symbol == "dead_symbol" for f in findings)


def test_secret_redaction() -> None:
    sample = "token = 'sk-" + ("a" * 24) + "' and AKIAIOSFODNN7EXAMPLE"
    redacted = redact_text(sample)
    assert "sk-" not in redacted
    assert "AKIA" not in redacted
    assert "[REDACTED]" in redacted


def test_finding_json_shape() -> None:
    finding = Finding(
        id="orphan:pkg/orphan.py",
        kind="orphan_file",
        severity="block",
        path="pkg/orphan.py",
        symbol=None,
        why="never imported",
        evidence=["no importers"],
    )
    payload = finding.to_dict()
    assert set(payload) == {
        "id", "kind", "severity", "path", "symbol", "why", "evidence", "confidence", "signals", "critique",
    }


def test_mcp_scan_tool() -> None:
    session = Session()
    init = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        session,
    )
    assert init and init["result"]["serverInfo"]["name"] == "deadpath"
    listed = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, session)
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {
        "deadpath.scan",
        "deadpath.judge",
        "deadpath.explain",
        "deadpath.plan",
        "deadpath.workflow",
        "deadpath.triage",
        "deadpath.remember",
        "deadpath.memory",
        "deadpath.languages",
    }
    called = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "deadpath.scan",
                "arguments": {"path": str(DEADAPP), "mock": True, "memory": False},
            },
        },
        session,
    )
    text = called["result"]["content"][0]["text"]
    assert "dead_symbol" in text
    assert "pkg/orphan.py" in text


def test_pyproject_metadata_is_not_reported_as_dependencies(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("import requests\n")
    (tmp_path / "pyproject.toml").write_text(
        """[project]
name = "sample"
authors = [{ name = "Example Author", email = "author@example.com" }]
keywords = ["static-analysis", "agents"]
classifiers = [
  "Programming Language :: Python :: 3",
]
dependencies = [
  "requests>=2",
  "unused-runtime>=1",
]

[project.optional-dependencies]
dev = ["pytest>=7", "ruff>=0.1"]
"""
    )

    findings = scan_path(tmp_path, lang="py")
    dependencies = {f.symbol for f in findings if f.kind == "unused_dep"}

    assert dependencies == {"unused-runtime", "pytest", "ruff"}
