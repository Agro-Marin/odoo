from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import js_vacuous_assertions as gate


def _tree(tmp_path: Path, *, test: str = "", **decls: str) -> Path:
    static = tmp_path / "addons" / "thing" / "static"
    (static / "tests").mkdir(parents=True, exist_ok=True)
    (static / "tests" / "thing.test.js").write_text(test, encoding="utf-8")
    for key, text in decls.items():
        stem, _, ext = key.rpartition("__")
        path = static / "src" / f"{stem}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _classes(tmp_path: Path, *, test: str, **decls: str) -> list[str]:
    return sorted(
        f.css_class for f in gate.measure([_tree(tmp_path, test=test, **decls)])
    )


def test_a_zero_count_on_an_undeclared_class_is_reported(tmp_path):
    assert _classes(tmp_path, test='expect(".o_never_existed").toHaveCount(0);\n') == [
        "o_never_existed"
    ]


def test_a_class_the_markup_declares_is_not_reported(tmp_path):
    assert (
        _classes(
            tmp_path,
            test='expect(".o_real").toHaveCount(0);\n',
            thing__xml='<div class="o_real"/>\n',
        )
        == []
    )


@pytest.mark.parametrize("ext", ["xml", "scss", "css", "js"])
def test_a_declaration_counts_from_any_scanned_kind(tmp_path, ext):
    assert (
        _classes(
            tmp_path,
            test='expect(".o_here").toHaveCount(0);\n',
            **{f"decl__{ext}": "o_here\n"},
        )
        == []
    )


def test_a_positive_count_needs_no_gate(tmp_path):
    assert _classes(tmp_path, test='expect(".o_gone").toHaveCount(1);\n') == []


def test_a_class_outside_the_owned_namespaces_is_not_reported(tmp_path):
    assert _classes(tmp_path, test='expect(".btn-primary").toHaveCount(0);\n') == []


def test_every_owned_namespace_is_actually_policed(tmp_path):
    for namespace in gate.OWNED_PREFIXES:
        found = _classes(
            tmp_path, test=f'expect(".{namespace}undeclared_x").toHaveCount(0);\n'
        )
        assert found == [f"{namespace}undeclared_x"], namespace


def test_a_runtime_composed_class_is_exempt(tmp_path):
    assert (
        _classes(
            tmp_path,
            test='expect(".o_field_daterange").toHaveCount(0);\n',
            builder__js="const cls = `o_field_${widget}`;\n",
        )
        == []
    )


def test_the_bare_namespace_does_not_exempt_everything(tmp_path):
    assert _classes(
        tmp_path,
        test='expect(".o_undeclared").toHaveCount(0);\n',
        builder__js="const cls = `o_${x}`;\n",
    ) == ["o_undeclared"]


def test_a_prefix_not_ending_in_a_separator_does_not_exempt(tmp_path):
    assert _classes(
        tmp_path,
        test='expect(".o_fieldxyz").toHaveCount(0);\n',
        builder__js="const token = 'o_field';\n",
    ) == ["o_fieldxyz"]


def test_the_composed_prefix_must_be_specific_past_the_namespace():
    namespace = "o_"
    span = gate.MIN_COMPOSED_SEGMENT
    just_under = namespace + "a" * (span - 2) + "_"
    exactly_at = namespace + "a" * (span - 1) + "_"
    assert len(just_under) - len(namespace) == span - 1
    assert len(exactly_at) - len(namespace) == span
    assert not gate.is_composed(f"{just_under}tail", {just_under})
    assert gate.is_composed(f"{exactly_at}tail", {exactly_at})


def test_only_test_files_are_searched_for_assertions(tmp_path):
    assert (
        _classes(
            tmp_path,
            test='expect(".o_real").toHaveCount(0);\n',
            thing__xml='<div class="o_real"/>\n',
            source__js='expect(".o_undeclared").toHaveCount(0);\n',
        )
        == []
    )


def test_a_scan_that_reaches_no_test_refuses_instead_of_reporting_zero(tmp_path):
    with pytest.raises(RuntimeError, match="reached nothing"):
        gate.measure([tmp_path / "absent"])


def test_findings_are_sorted_by_location_so_a_diff_is_readable(tmp_path):
    found = gate.measure(
        [
            _tree(
                tmp_path,
                test=(
                    'expect(".o_zeta").toHaveCount(0);\n'
                    'expect(".o_alpha").toHaveCount(0);\n'
                ),
            )
        ]
    )
    assert [f.css_class for f in found] == ["o_zeta", "o_alpha"]
    assert [f.line for f in found] == [1, 2]
