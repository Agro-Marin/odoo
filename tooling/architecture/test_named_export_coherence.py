from __future__ import annotations

from pathlib import Path

import pytest
from named_export_coherence import (
    Resolver,
    destructured_names,
    discover_addons_roots,
    exported_names,
    find_unsatisfied,
    imported_names,
    main,
)


def make_module(root: Path, addon: str, subpath: str, source: str) -> Path:
    path = root / addon / "static" / "src" / f"{subpath}.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


@pytest.fixture
def addons(tmp_path: Path) -> Path:
    return tmp_path / "addons"


def test_detects_a_missing_named_export(addons: Path) -> None:
    make_module(
        addons, "web", "views/view_compiler", "export function useViewCompiler() {}\n"
    )
    make_module(
        addons,
        "web_gantt",
        "gantt_popover",
        'import { compileViewTemplates } from "@web/views/view_compiler";\n',
    )
    found = find_unsatisfied([addons], [addons])
    assert [f.name for f in found] == ["compileViewTemplates"]


def test_accepts_a_present_named_export(addons: Path) -> None:
    make_module(
        addons, "web", "views/view_compiler", "export function useViewCompiler() {}\n"
    )
    make_module(
        addons,
        "web_gantt",
        "gantt_popover",
        'import { useViewCompiler } from "@web/views/view_compiler";\n',
    )
    assert find_unsatisfied([addons], [addons]) == []


def test_a_mime_type_string_does_not_open_a_phantom_comment(addons: Path) -> None:
    make_module(
        addons,
        "web",
        "fields/image_field",
        'const ACCEPT = "image/*";\nexport const imageField = { ACCEPT };\n',
    )
    make_module(
        addons, "other", "x", 'import { imageField } from "@web/fields/image_field";\n'
    )
    assert find_unsatisfied([addons], [addons]) == []


def test_module_specifiers_survive_comment_stripping(addons: Path) -> None:
    make_module(addons, "mail", "model/record", "export class Record {}\n")
    make_module(addons, "mail", "model/export", 'export * from "./record.js";\n')
    make_module(
        addons, "mail", "core/common/record", 'export * from "@mail/model/export";\n'
    )
    make_module(
        addons, "other", "x", 'import { Record } from "@mail/core/common/record";\n'
    )
    assert find_unsatisfied([addons], [addons]) == []


def test_destructured_export_is_recognised(addons: Path) -> None:
    make_module(
        addons,
        "web",
        "libs/bootstrap",
        "const Bootstrap = {};\nexport const {\n    Modal,\n    Tooltip: Tip,\n} = Bootstrap;\n",
    )
    make_module(
        addons, "other", "x", 'import { Modal, Tip } from "@web/libs/bootstrap";\n'
    )
    assert find_unsatisfied([addons], [addons]) == []
    make_module(
        addons, "other", "y", 'import { Popover } from "@web/libs/bootstrap";\n'
    )
    assert [f.name for f in find_unsatisfied([addons], [addons])] == ["Popover"]


def test_indented_export_is_recognised(addons: Path) -> None:
    make_module(addons, "hr_gantt", "renderer", " export class Renderer {}\n")
    make_module(
        addons, "other", "x", 'import { Renderer } from "@hr_gantt/renderer";\n'
    )
    assert find_unsatisfied([addons], [addons]) == []


def test_commented_out_import_is_ignored(addons: Path) -> None:
    make_module(addons, "web", "core/x", "export const a = 1;\n")
    make_module(addons, "other", "x", '// import { gone } from "@web/core/x";\n')
    assert find_unsatisfied([addons], [addons]) == []


def test_renaming_import_checks_the_original_name(addons: Path) -> None:
    make_module(
        addons, "web", "fields/selection", "export const selectionField = {};\n"
    )
    make_module(
        addons,
        "other",
        "x",
        'import { selection_field as selectionField } from "@web/fields/selection";\n',
    )
    assert [f.name for f in find_unsatisfied([addons], [addons])] == ["selection_field"]


def test_export_from_republishes_the_alias(addons: Path) -> None:
    make_module(addons, "web", "core/inner", "export const a = 1;\n")
    make_module(addons, "web", "core/outer", 'export { a as b } from "./inner.js";\n')
    make_module(addons, "other", "x", 'import { b } from "@web/core/outer";\n')
    assert find_unsatisfied([addons], [addons]) == []


def test_unresolvable_reexport_withholds_judgement(addons: Path) -> None:
    make_module(addons, "web", "core/barrel", 'export * from "@nowhere/missing";\n')
    make_module(addons, "other", "x", 'import { anything } from "@web/core/barrel";\n')
    assert find_unsatisfied([addons], [addons]) == []


def test_import_cycle_terminates(addons: Path) -> None:
    make_module(
        addons, "web", "core/a", 'export * from "./b.js";\nexport const x = 1;\n'
    )
    make_module(
        addons, "web", "core/b", 'export * from "./a.js";\nexport const y = 2;\n'
    )
    make_module(addons, "other", "x", 'import { x, y } from "@web/core/a";\n')
    assert find_unsatisfied([addons], [addons]) == []


def test_non_addon_scopes_are_skipped(addons: Path) -> None:
    make_module(addons, "other", "x", 'import { Component } from "@odoo/owl";\n')
    assert find_unsatisfied([addons], [addons]) == []


def test_helpers() -> None:
    assert imported_names("a, b as c") == ["a", "b"]
    assert imported_names("default, a") == ["a"]
    assert exported_names("a, b as c") == {"a", "c"}
    assert destructured_names("{ a, b: c, d = 1, ...rest }") == {"a", "c", "d", "rest"}
    assert destructured_names("[ a, b ]") == {"a", "b"}


def test_exported_names_ignores_a_template_built_export_statement() -> None:
    assert exported_names(' ${aliases.join(", ")} ') == set()
    assert exported_names("a, b as c") == {"a", "c"}


def test_exported_names_keeps_dollar_and_underscore_identifiers() -> None:
    assert exported_names("$el, _private, a1") == {"$el", "_private", "a1"}


def test_discovery_finds_this_repo() -> None:
    roots = discover_addons_roots()
    assert roots, "no addons root discovered from the checked-out repo"
    assert any(r.name == "addons" for r in roots)


def test_check_flag_controls_exit_code(addons: Path, capsys) -> None:
    make_module(addons, "web", "core/x", "export const a = 1;\n")
    make_module(addons, "other", "x", 'import { gone } from "@web/core/x";\n')
    assert main([str(addons)]) == 0
    assert main([str(addons), "--check"]) == 1
    assert "gone" in capsys.readouterr().out


def test_resolver_prefers_a_file_over_a_directory(addons: Path) -> None:
    make_module(addons, "web", "core/utils", "export const a = 1;\n")
    make_module(addons, "web", "core/utils/inner", "export const b = 2;\n")
    resolver = Resolver([addons])
    resolved = resolver.resolve("@web/core/utils")
    assert resolved is not None and resolved.name == "utils.js"


def test_the_gate_refuses_a_root_that_holds_no_sources(tmp_path):
    import named_export_coherence as nec
    import pytest

    (tmp_path / "empty").mkdir()
    with pytest.raises(SystemExit) as exc:
        nec.main(["--check", str(tmp_path / "empty")])
    assert exc.value.code == 2
