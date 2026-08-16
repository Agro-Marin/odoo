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


def test_comments_and_blank_lines_count_toward_the_budget(tmp_path):
    filler = "\n".join("    // padding" for _ in range(jfl.MAX_LINES + 20))
    src = _src(tmp_path, {"a.js": f"export function commented() {{\n{filler}\n}}\n"})
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
    found = jfl.measure()
    assert len(found) > 50, f"expected the real budget, measured {len(found)}"
    assert found[0].lines > 400, "expected the known 738-line outlier at the top"
    assert all(f.lines > jfl.MAX_LINES for f in found)
    assert not any(Path(f.file).name in jfl.GENERATED for f in found)


def _mixin(name: str, body_lines: int) -> str:
    methods = "\n".join(f"        m{i}() {{ return {i}; }}" for i in range(body_lines))
    return f"export const {name} = (Base) =>\n    class extends Base {{\n{methods}\n    }};\n"


def test_mixin_factory_is_relabelled_not_called_an_arrow_function(tmp_path):

    src = _src(tmp_path, {"m.js": _mixin("QueryMixin", jfl.MAX_LINES + 40)})
    found = jfl.measure(src)
    assert len(found) == 1
    assert found[0].what == "Mixin class body"


def test_relabelling_does_not_change_the_count(tmp_path):
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
