from __future__ import annotations

from pathlib import Path

from deadpath.graph import build_typescript_graph, ts_imported_set


def test_typescript_orphan_and_unused_export(tmp_path: Path) -> None:
    (tmp_path / "used.ts").write_text("export function live(): number { return 1 }\n", encoding="utf-8")
    (tmp_path / "orphan.ts").write_text("export function leftover(): number { return 0 }\n", encoding="utf-8")
    (tmp_path / "index.ts").write_text("import { live } from './used'\nexport const n = live()\n", encoding="utf-8")
    files = sorted(tmp_path.glob("*.ts"))
    modules = build_typescript_graph(tmp_path, files)
    imported = ts_imported_set(modules)
    assert "used" in imported
    assert "orphan" not in imported
    assert "live" in modules["used"].imported_names


def test_typescript_path_aliases(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}',
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "used.ts").write_text("export function live(): number { return 1 }\n", encoding="utf-8")
    (src / "index.ts").write_text("import { live } from '@/used'\nexport const n = live()\n", encoding="utf-8")
    files = sorted(src.glob("*.ts"))
    modules = build_typescript_graph(tmp_path, files)
    imported = ts_imported_set(modules)
    assert "src/used" in imported
    assert "live" in modules["src/used"].imported_names
