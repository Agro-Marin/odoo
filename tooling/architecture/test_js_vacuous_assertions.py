"""The gate that catches assertions which cannot fail, tested so it cannot itself.

`expect(".o_thing").toHaveCount(0)` is a test only while `.o_thing` is something
the tree can render. Once the class is renamed away the selector matches nothing
for a reason unrelated to the behaviour, and the assertion passes forever —
including when what it guarded regresses. ADR-0044, and three shipped incidents
behind it.

A gate of that shape has an asymmetric failure mode. Report too much and it is
turned off; report too little and it reads 0 over a tree with real findings,
which is exactly what happened once already — accepting `o_` as a composing
prefix exempted every `o_*` class there is. Both edges are below, and the
`MIN_COMPOSED_SEGMENT` rule that fixed it has a case of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import js_vacuous_assertions as gate


def _tree(tmp_path: Path, *, test: str = "", **decls: str) -> Path:
    """A minimal addon: one `*.test.js`, plus any declaring files.

    The suffix is load-bearing and was the first thing this harness got wrong:
    `collect` treats anything under `static/tests/` as a test for the purpose of
    NOT counting its words as declarations, but only a `*.test.js` is collected
    as a file to search. A fixture named `thing_test.js` therefore contributed
    nothing and `measure` refused the whole scan.

    `decls` is `name__ext` -> content, written under `static/src/`.
    """
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
    assert _classes(
        tmp_path, test='expect(".o_never_existed").toHaveCount(0);\n'
    ) == ["o_never_existed"]


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
    """A template, a stylesheet or a component all count as declaring it.

    The point is not to prove the selector matches at runtime — a static scan
    cannot — but to catch the class the tree has no idea about.
    """
    assert (
        _classes(
            tmp_path,
            test='expect(".o_here").toHaveCount(0);\n',
            **{f"decl__{ext}": "o_here\n"},
        )
        == []
    )


def test_a_positive_count_needs_no_gate(tmp_path):
    """`toHaveCount(1)` fails loudly the day the class disappears."""
    assert (
        _classes(tmp_path, test='expect(".o_gone").toHaveCount(1);\n') == []
    )


def test_a_class_outside_the_owned_namespaces_is_not_reported(tmp_path):
    """Bootstrap and FontAwesome ship classes this tree never spells out.

    Demanding a local declaration for them would report noise rather than drift,
    and noise is how a gate gets switched off.
    """
    assert (
        _classes(tmp_path, test='expect(".btn-primary").toHaveCount(0);\n') == []
    )


def test_every_owned_namespace_is_actually_policed(tmp_path):
    """Otherwise a namespace could be dropped from the tuple and nothing notice."""
    for namespace in gate.OWNED_PREFIXES:
        found = _classes(
            tmp_path, test=f'expect(".{namespace}undeclared_x").toHaveCount(0);\n'
        )
        assert found == [f"{namespace}undeclared_x"], namespace


# --------------------------------------------------------------------------
# The composed-class rule, and the regression that produced it
# --------------------------------------------------------------------------


def test_a_runtime_composed_class_is_exempt(tmp_path):
    """`o_field_daterange` is never written down; `o_field_` is.

    A declared token the class starts with, ending in a separator, exempts it.
    """
    assert (
        _classes(
            tmp_path,
            test='expect(".o_field_daterange").toHaveCount(0);\n',
            builder__js="const cls = `o_field_${widget}`;\n",
        )
        == []
    )


def test_the_bare_namespace_does_not_exempt_everything(tmp_path):
    """The regression `MIN_COMPOSED_SEGMENT` exists for.

    `o_` falls out of any `` `o_${x}` `` template literal, so it is a declared
    token in this tree. Accepting it as a composing prefix exempted every `o_*`
    class there is, and the gate read 0 against a tree with real findings.
    """
    assert _classes(
        tmp_path,
        test='expect(".o_undeclared").toHaveCount(0);\n',
        builder__js="const cls = `o_${x}`;\n",
    ) == ["o_undeclared"]


def test_a_prefix_not_ending_in_a_separator_does_not_exempt(tmp_path):
    """`o_fieldx` is not built from a declared `o_field`; it is its own name."""
    assert _classes(
        tmp_path,
        test='expect(".o_fieldxyz").toHaveCount(0);\n',
        builder__js="const token = 'o_field';\n",
    ) == ["o_fieldxyz"]


def test_the_composed_prefix_must_be_specific_past_the_namespace():
    """The threshold is on the prefix MINUS the namespace, and it is inclusive.

    Derived from the constant rather than written out, because the arithmetic is
    the easy thing to get wrong: the rule compares `len(prefix) - len(namespace)`
    against `MIN_COMPOSED_SEGMENT`, so `o_aaa_` is already 4 past `o_` and
    qualifies. The first version of this test asserted it did not.
    """
    namespace = "o_"
    span = gate.MIN_COMPOSED_SEGMENT
    just_under = namespace + "a" * (span - 2) + "_"
    exactly_at = namespace + "a" * (span - 1) + "_"
    assert len(just_under) - len(namespace) == span - 1
    assert len(exactly_at) - len(namespace) == span
    assert not gate.is_composed(f"{just_under}tail", {just_under})
    assert gate.is_composed(f"{exactly_at}tail", {exactly_at})


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------


def test_only_test_files_are_searched_for_assertions(tmp_path):
    """A `toHaveCount(0)` in source is not an assertion anyone runs.

    STRUCTURAL, NOT OBSERVABLE, and mutation testing is how that was established:
    a mutation collecting source `.js` as tests survives this suite, and no
    fixture can catch it. A file that writes `".o_x"` thereby contributes `o_x`
    to `declared` — `WORD.findall` reads it straight out of the selector — so a
    source file asserting on a class always declares the class it asserts on, and
    the finding is suppressed either way.

    Kept because the scope is worth stating, not because it is enforced. The
    assertion below is that the source-side one is absent from the output; the
    reason is the declaration rule, not the test/source split.
    """
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
    """0 is what a clean tree looks like, so a scan that reached nothing must refuse.

    Banking that 0 as a floor is the decorative-gate failure the module's own
    comment argues against — and it happened to this gate during its development,
    for a different reason.
    """
    with pytest.raises(RuntimeError, match="reached nothing"):
        gate.measure([tmp_path / "absent"])


def test_findings_are_sorted_by_location_so_a_diff_is_readable(tmp_path):
    """By file and line, not by class name.

    `Finding` is `order=True` with `file` and `line` first, so two findings in
    one file come back in source order — which is what a reviewer reading a diff
    wants, and the opposite of what this test first asserted.
    """
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
