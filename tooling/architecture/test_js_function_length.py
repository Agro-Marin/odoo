from pathlib import Path

import js_function_length as jfl
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
    inner = "\n".join(f"        const v{i} = {i};" for i in range(jfl.MAX_LINES + 20))
    src = _src(
        tmp_path,
        {
            "a.js": f"export function outer() {{\n    return function inner() {{\n{inner}\n    }};\n}}\n"
        },
    )
    assert len(jfl.measure(src)) == 2


def test_generated_sources_are_excluded(tmp_path):
    name = next(iter(jfl.GENERATED))
    src = _src(
        tmp_path,
        {name: _fn("generated", jfl.MAX_LINES + 500), "real.js": _fn("mine", 5)},
    )
    assert jfl.measure(src) == []


def test_comments_do_not_count_toward_the_budget(tmp_path):
    # The gate is a complexity proxy. Counting JSDoc as complexity would make
    # documenting a function cost ratchet budget and deleting documentation bank
    # credit, which is what skipComments: true exists to prevent.
    filler = "\n".join("    // padding" for _ in range(jfl.MAX_LINES + 20))
    src = _src(tmp_path, {"a.js": f"export function commented() {{\n{filler}\n}}\n"})
    assert jfl.measure(src) == []


def test_a_documented_function_is_judged_on_its_code(tmp_path):
    # Same body, once bare and once with more JSDoc than the limit allows: the
    # verdict must not depend on the documentation.
    body = "\n".join(f"    const v{i} = {i};" for i in range(jfl.MAX_LINES + 20))
    doc = "\n".join(f"    // line {i}" for i in range(jfl.MAX_LINES))
    bare = _src(tmp_path / "bare", {"a.js": f"export function f() {{\n{body}\n}}\n"})
    documented = _src(
        tmp_path / "doc", {"a.js": f"export function f() {{\n{doc}\n{body}\n}}\n"}
    )
    assert [f.lines for f in jfl.measure(bare)] == [
        f.lines for f in jfl.measure(documented)
    ]


def test_blank_lines_still_count_toward_the_budget(tmp_path):
    # Deliberately NOT skipped: a blank line is a formatting choice, not
    # documentation, so it carries no incentive worth removing.
    filler = "\n".join("" for _ in range(jfl.MAX_LINES + 20))
    body = "\n".join(f"    const v{i} = {i};" for i in range(10))
    src = _src(
        tmp_path, {"a.js": f"export function spaced() {{\n{body}\n{filler}\n}}\n"}
    )
    assert len(jfl.measure(src)) == 1


def test_missing_eslint_raises_rather_than_reporting_clean(tmp_path):
    src = _src(tmp_path, {"a.js": _fn("longOne", jfl.MAX_LINES + 20)})
    with pytest.raises(RuntimeError, match="eslint not found"):
        jfl.measure(src, eslint=tmp_path / "no" / "such" / "eslint")


def test_empty_tree_raises_rather_than_reporting_clean(tmp_path):
    empty = tmp_path / "src"
    empty.mkdir()
    with pytest.raises(RuntimeError):
        jfl.measure(empty)


def test_real_tree_measurement_is_non_trivial():
    """The measurement reaches the tree and the offenders it finds are real.

    The top-offender bound is a canary on the measurement, not a fact about the
    tree, so it has to be a floor the tree can cross downwards. It read
    `> 400` against "the known 738-line outlier" until 2026-08-17, when
    `useListKeyboardNavigation` was split 473 -> 385 and the assertion failed on
    an improvement -- the outlier it named had already been gone for a while and
    nothing noticed, because a stale upper landmark only fails when the tree
    gets *better*. Stated as a bound the measurement must clear rather than as a
    remembered maximum: anything materially above `MAX_LINES` proves the scan is
    finding whole functions, not fragments.
    """
    found = jfl.measure()
    assert len(found) > 50, f"expected the real budget, measured {len(found)}"
    assert found[0].lines > 2 * jfl.MAX_LINES, (
        f"the longest function measured {found[0].lines} lines, under "
        f"{2 * jfl.MAX_LINES} -- either the tree improved dramatically or the "
        f"scan is truncating functions"
    )
    assert all(f.lines > jfl.MAX_LINES for f in found)
    assert not any(Path(f.file).name in jfl.GENERATED for f in found)


def _mixin(name: str, body_lines: int) -> str:
    methods = "\n".join(f"        m{i}() {{ return {i}; }}" for i in range(body_lines))
    return f"export const {name} = (Base) =>\n    class extends Base {{\n{methods}\n    }};\n"


def test_mixin_factory_wrapper_is_not_an_offender(tmp_path):
    """A `(Base) => class extends Base {}` wrapper is a function only
    grammatically; its body is a class and the complexity is in the methods.
    The wrapper used to be relabelled "Mixin class body" and still counted,
    which charged the floor twice for one piece of code -- ADR-0025, amended.
    Here every method is short, so nothing is over the budget at all."""
    src = _src(tmp_path, {"m.js": _mixin("QueryMixin", jfl.MAX_LINES + 40)})
    assert jfl.measure(src) == []


def test_dropping_the_wrapper_leaves_every_real_offender(tmp_path):
    """Dropping the wrapper must not take anything else with it."""
    src = _src(
        tmp_path,
        {
            "m.js": _mixin("QueryMixin", jfl.MAX_LINES + 40),
            "a.js": _fn("longOne", jfl.MAX_LINES + 20),
        },
    )
    found = jfl.measure(src)
    assert len(found) == 1
    assert found[0].what == "Function 'longOne'"


def test_a_long_method_inside_a_mixin_is_still_counted(tmp_path):
    """The unit is the METHOD. Dropping the wrapper must not hide what it
    wrapped -- otherwise a long function would escape the budget by moving
    into a mixin."""
    body = "\n".join(f"            const x{i} = {i};" for i in range(jfl.MAX_LINES + 10))
    src = _src(
        tmp_path,
        {
            "m.js": (
                "export const QueryMixin = (Base) =>\n"
                "    class extends Base {\n"
                "        longMethod() {\n"
                f"{body}\n"
                "        }\n"
                "    };\n"
            )
        },
    )
    found = jfl.measure(src)
    assert len(found) == 1
    assert "longMethod" in found[0].what


def test_a_plain_long_arrow_function_keeps_its_label(tmp_path):
    body = "\n".join(f"    const x{i} = {i};" for i in range(jfl.MAX_LINES + 10))
    src = _src(tmp_path, {"a.js": f"export const run = () => {{\n{body}\n}};\n"})
    found = jfl.measure(src)
    assert len(found) == 1
    assert "Arrow function" in found[0].what


def test_real_tree_does_not_count_the_search_mixin_wrappers():
    """The five SearchModel mixins were five of the six wrappers in `web` when
    ADR-0025 was amended. None of their factory bodies is an offender now;
    whatever methods inside them exceed the budget still are."""
    found = jfl.measure()
    assert not any(f.what == "Mixin class body" for f in found)
    wrappers = [
        f
        for f in found
        if f.file.endswith("_mixin.js") and f.what.startswith("Arrow function")
    ]
    assert wrappers == []
