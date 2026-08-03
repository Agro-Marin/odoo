"""Tests for the JS function-length budget.

Stdlib + pytest only — no Odoo imports — so this runs in the same
database-free way as the checker itself. Run with:

    pytest tooling/architecture/test_js_function_length.py

``measure()`` shells out to ESLint, so most tests drive it against a synthetic
source tree with a known answer rather than asserting numbers about the real
one. The real tree gets one test, and what it asserts is that the measurement
is non-trivial — a budget reporting "0 over the limit" because it linted
nothing looks exactly like a clean tree.
"""

from pathlib import Path

import js_function_length as jfl  # sys.path set by conftest.py
import pytest


def _src(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "src"
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return src


def _fn(name: str, body_lines: int) -> str:
    body = "\n".join(f"    const v{i} = {i};" for i in range(body_lines))
    return f"export function {name}() {{\n{body}\n}}\n"


# --- measurement ---


def test_function_over_the_limit_is_reported(tmp_path):
    src = _src(tmp_path, {"a.js": _fn("longOne", jfl.MAX_LINES + 20)})
    found = jfl.measure(src)
    assert len(found) == 1
    assert found[0].lines > jfl.MAX_LINES
    assert "longOne" in found[0].what
    assert found[0].file.endswith("a.js")


def test_function_under_the_limit_is_not_reported(tmp_path):
    src = _src(tmp_path, {"a.js": _fn("shortOne", 5)})
    assert jfl.measure(src) == []


def test_a_function_exactly_at_the_limit_is_allowed(tmp_path):
    # `max` is inclusive in ESLint: a function of exactly MAX_LINES passes.
    # Pinned because an off-by-one here silently shifts the whole baseline.
    src = _src(tmp_path, {"a.js": _fn("edge", jfl.MAX_LINES - 2)})
    found = jfl.measure(src)
    assert found == [], f"expected the boundary case to pass, got {found}"


def test_findings_are_sorted_longest_first(tmp_path):
    src = _src(
        tmp_path,
        {
            "a.js": _fn("medium", jfl.MAX_LINES + 20),
            "b.js": _fn("longest", jfl.MAX_LINES + 200),
        },
    )
    found = jfl.measure(src)
    assert [f.lines for f in found] == sorted((f.lines for f in found), reverse=True)
    assert "longest" in found[0].what


def test_nested_functions_are_counted_separately(tmp_path):
    # makeDraggableHook is 738 lines and the hook it returns is 692. Both are
    # too long to read, so both count; splitting the outer drops both.
    inner = "\n".join(f"        const v{i} = {i};" for i in range(jfl.MAX_LINES + 20))
    src = _src(
        tmp_path,
        {
            "a.js": f"export function outer() {{\n    return function inner() {{\n{inner}\n    }};\n}}\n"
        },
    )
    assert len(jfl.measure(src)) == 2


def test_generated_sources_are_excluded(tmp_path):
    # emoji_data.js is a 36k-line data table; its eight entries would dominate
    # every report and say nothing about anyone's design.
    name = next(iter(jfl.GENERATED))
    src = _src(
        tmp_path,
        {name: _fn("generated", jfl.MAX_LINES + 500), "real.js": _fn("mine", 5)},
    )
    assert jfl.measure(src) == []


def test_comments_and_blank_lines_count_toward_the_budget(tmp_path):
    # skipComments/skipBlankLines are off deliberately: the budget is about how
    # much a reader holds at once, and a long function must not hide behind its
    # own documentation.
    filler = "\n".join("    // padding" for _ in range(jfl.MAX_LINES + 20))
    src = _src(tmp_path, {"a.js": f"export function commented() {{\n{filler}\n}}\n"})
    assert len(jfl.measure(src)) == 1


# --- failing closed ---


def test_missing_eslint_raises_rather_than_reporting_clean(tmp_path):
    src = _src(tmp_path, {"a.js": _fn("longOne", jfl.MAX_LINES + 20)})
    with pytest.raises(RuntimeError, match="eslint not found"):
        jfl.measure(src, eslint=tmp_path / "no" / "such" / "eslint")


def test_empty_tree_raises_rather_than_reporting_clean(tmp_path):
    # "0 over the limit" and "linted nothing" are the same output otherwise.
    empty = tmp_path / "src"
    empty.mkdir()
    with pytest.raises(RuntimeError):
        jfl.measure(empty)


# --- the real tree ---


def test_real_tree_measurement_is_non_trivial():
    found = jfl.measure()
    assert len(found) > 50, f"expected the real budget, measured {len(found)}"
    assert found[0].lines > 400, "expected the known 738-line outlier at the top"
    assert all(f.lines > jfl.MAX_LINES for f in found)
    assert not any(Path(f.file).name in jfl.GENERATED for f in found)


# --- mixin class bodies (label only, never the count) ---


def _mixin(name: str, body_lines: int) -> str:
    """A mixin factory: an arrow function whose entire body is a class."""
    methods = "\n".join(f"        m{i}() {{ return {i}; }}" for i in range(body_lines))
    return f"export const {name} = (Base) =>\n    class extends Base {{\n{methods}\n    }};\n"


def test_mixin_factory_is_relabelled_not_called_an_arrow_function(tmp_path):
    """A `(Base) => class extends Base` body reads as a god function otherwise.

    That mislabel is what led an audit to propose splitting three `search/`
    mixins that are class bodies, not functions.
    """
    src = _src(tmp_path, {"m.js": _mixin("QueryMixin", jfl.MAX_LINES + 40)})
    found = jfl.measure(src)
    assert len(found) == 1
    assert found[0].what == "Mixin class body"


def test_relabelling_does_not_change_the_count(tmp_path):
    """The ratchet pins the count in `exact` mode; a label must not move it."""
    src = _src(
        tmp_path,
        {
            "m.js": _mixin("QueryMixin", jfl.MAX_LINES + 40),
            "a.js": _fn("longOne", jfl.MAX_LINES + 20),
        },
    )
    found = jfl.measure(src)
    assert len(found) == 2
    assert {f.what for f in found} == {"Mixin class body", "Function 'longOne'"}


def test_a_plain_long_arrow_function_keeps_its_label(tmp_path):
    body = "\n".join(f"    const x{i} = {i};" for i in range(jfl.MAX_LINES + 10))
    src = _src(tmp_path, {"a.js": f"export const run = () => {{\n{body}\n}};\n"})
    found = jfl.measure(src)
    assert len(found) == 1
    assert "Arrow function" in found[0].what


def test_real_tree_labels_the_search_mixins_as_class_bodies():
    found = jfl.measure()
    mixins = [f for f in found if f.file.endswith("search_query_mixin.js")]
    assert mixins, "expected search_query_mixin.js over the budget"
    assert all(f.what == "Mixin class body" for f in mixins)
