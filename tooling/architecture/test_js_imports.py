import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import js_imports
import js_imports as ji
from _repo_root import find_odoo_root
from js_imports import collect_imports


def _specs(src: str) -> list[str]:
    return [s for s, _ in ji.collect_imports(src)]


def _by_line(src: str) -> dict[str, int]:
    return dict(ji.collect_imports(src))


def test_jsdoc_import_tag_is_not_a_runtime_import():
    src = (
        '/** @import { RPCCache } from "@web/views/foo" */\n'
        'import { registry } from "@web/core/registry";\n'
    )
    specs = _specs(src)
    assert "@web/core/registry" in specs
    assert "@web/views/foo" not in specs


def test_inline_jsdoc_type_import_is_ignored():
    src = (
        "/**\n"
        ' * @param {import("@web/views/list/list_renderer").Foo} x\n'
        ' * @returns {import("@web/webclient/x").Bar}\n'
        " */\n"
        "export function f(x) { return x; }\n"
    )
    assert _specs(src) == []


def test_line_comment_import_is_ignored():
    src = 'import { a } from "@web/core/a";\n// import { b } from "@web/views/b";\n'
    specs = _specs(src)
    assert specs == ["@web/core/a"]


def test_string_with_double_slash_is_not_treated_as_comment():
    src = 'const u = "https://example.com/x";\nimport { a } from "@web/fields/a";\n'
    assert _specs(src) == ["@web/fields/a"]


def test_regex_literal_containing_slash_star_does_not_open_a_comment():
    src = (
        'import { a } from "@web/core/a";\n'
        "const re = /^\\/*/;\n"
        'import { b } from "@web/webclient/b";\n'
    )
    assert _specs(src) == ["@web/core/a", "@web/webclient/b"]


def test_regex_literal_containing_quote_does_not_open_a_string():
    src = (
        'const s = x.replace(/["\\\\]/g, "");\n'
        "/**\n"
        ' * @returns {Promise<import("@web/views/gone").T>}\n'
        " */\n"
        'import { a } from "@web/core/a";\n'
    )
    assert _specs(src) == ["@web/core/a"]


def test_division_is_not_mistaken_for_a_regex():
    src = (
        "const half = total / 2;\n"
        "const q = (a + b) / c / d;\n"
        "const r = arr[0] / 2;\n"
        'import { a } from "@web/core/a";\n'
    )
    assert _specs(src) == ["@web/core/a"]


def test_regex_after_keyword_is_a_regex_not_division():
    src = (
        'function f(s) { return /a\\/*b/.test(s); }\nimport { a } from "@web/core/a";\n'
    )
    assert _specs(src) == ["@web/core/a"]


def test_unterminated_slash_does_not_swallow_the_rest_of_the_file():
    src = 'const x = a / b;\nimport { a } from "@web/core/a";\n'
    assert _specs(src) == ["@web/core/a"]


def test_long_comment_before_a_division_does_not_eat_a_same_line_import():
    long_comment = "/* explain the units carefully here */"
    short_comment = "/* units */"
    for comment in (short_comment, long_comment):
        src = f"let r = a {comment} / b; import('@web/webclient/x');\n"
        assert _specs(src) == ["@web/webclient/x"], f"lost the import after {comment!r}"
        src = f"let r = a {comment} / b; export {{ A }} from '@web/webclient/x';\n"
        assert _specs(src) == ["@web/webclient/x"], (
            f"lost the re-export after {comment!r}"
        )


def test_long_comment_before_a_real_regex_still_reads_a_regex():
    src = (
        "const m = s.replace(/* explain the pattern here ok */ /a\\/b/, '');\n"
        'import { a } from "@web/core/a";\n'
    )
    assert _specs(src) == ["@web/core/a"]


def test_regex_decision_is_independent_of_leading_whitespace_run():
    src = "const b = a" + " " * 40 + "/ 2; import('@web/core/a');\n"
    assert _specs(src) == ["@web/core/a"]


def test_division_after_a_string_or_regex_value_is_division():
    for value in ('"txt"', "/re/"):
        src = f"const r = {value} / 2; import('@web/core/a');\n"
        assert _specs(src) == ["@web/core/a"], f"after {value}"


def test_strip_comments_preserves_length_and_newlines():
    src = (
        'import { a } from "@web/core/a";\n'
        "const re = /^\\/*/; // trailing\n"
        "/* block\n   comment */\n"
        'const s = "str";\n'
    )
    out = ji.strip_comments(src)
    assert len(out) == len(src)
    assert [i for i, c in enumerate(out) if c == "\n"] == [
        i for i, c in enumerate(src) if c == "\n"
    ]


def test_specifier_never_spans_a_newline():
    src = 'const py = `from "a\nb" tail`;\nimport { a } from "@web/core/a";\n'
    assert _specs(src) == ["@web/core/a"]


def test_block_comment_preserves_line_numbers():
    src = '/* line1\n   line2 */\nimport { a } from "@web/core/a";\n'
    assert _by_line(src)["@web/core/a"] == 3


def test_static_side_effect_and_dynamic_imports_all_collected():
    src = (
        'import Default from "@web/core/d";\n'
        'import { a, b } from "@web/core/ab";\n'
        'import * as ns from "@web/core/ns";\n'
        'import "@web/core/sidefx";\n'
        'export { x } from "@web/core/reexport";\n'
        'const p = import("@web/core/dynamic");\n'
    )
    specs = set(_specs(src))
    assert specs == {
        "@web/core/d",
        "@web/core/ab",
        "@web/core/ns",
        "@web/core/sidefx",
        "@web/core/reexport",
        "@web/core/dynamic",
    }


def test_multiline_import_specifier_collected():
    src = 'import {\n  a,\n  b,\n} from "@web/views/list/x";\n'
    assert _specs(src) == ["@web/views/list/x"]


def test_a_dynamic_import_of_a_bare_package_is_collected():
    src = 'async function f() { const { x } = await import("zxing-library"); }\n'
    assert _specs(src) == ["zxing-library"]


def test_a_string_that_merely_looks_like_a_specifier_is_not_an_import():
    src = 'bus.trigger("@web/core/l10n/translationLoaded");\n'
    assert _specs(src) == []


def _web_src() -> Path:
    root = find_odoo_root(Path(__file__).resolve(), tool="test_js_imports")
    return root / "addons" / "web" / "static" / "src"


def test_every_dynamic_import_in_web_is_found():
    src_root = _web_src()
    if not src_root.is_dir():  # pragma: no cover - sibling-less checkout
        return
    missed = []
    for path in sorted(src_root.rglob("*.js")):
        source = path.read_text(encoding="utf8", errors="replace")
        cleaned = js_imports.strip_comments(source)
        found = set(_specs(source))
        missed.extend(
            f"{path.relative_to(src_root)}: {match.group(1)}"
            for match in js_imports._DYNAMIC_RE.finditer(cleaned)
            if match.group(1) not in found
        )
    assert missed == [], f"dynamic imports not collected: {missed[:5]}"


def test_the_web_tree_parses_to_a_populated_graph():
    src_root = _web_src()
    if not src_root.is_dir():  # pragma: no cover - sibling-less checkout
        return
    files = sorted(src_root.rglob("*.js"))
    edges = sum(
        len(collect_imports(f.read_text(encoding="utf8", errors="replace")))
        for f in files
    )
    assert len(files) > 500, f"only {len(files)} source files found"
    assert edges > 2500, f"only {edges} import edges over {len(files)} files"


def test_a_jsdoc_type_import_is_collected_as_a_type_import():
    src = '/** @param {import("@web/core/tree/condition_tree").Tree} t */\n'
    assert ji.collect_type_imports(src) == [("@web/core/tree/condition_tree", 1)]
    assert collect_imports(src) == []


def test_a_real_dynamic_import_is_not_a_type_import():
    src = 'const m = await import("@web/core/domain");\n'
    assert ji.collect_type_imports(src) == []
    assert collect_imports(src) == [("@web/core/domain", 1)]


def test_the_two_collectors_partition_a_mixed_file():
    src = (
        'import { a } from "@web/one";\n'
        '/** @type {import("@web/two").T} */\n'
        'const lazy = () => import("@web/three");\n'
        '// see import("@web/four") for the rationale\n'
    )
    assert sorted(ji.collect_type_imports(src)) == [("@web/four", 4), ("@web/two", 2)]
    assert sorted(collect_imports(src)) == [("@web/one", 1), ("@web/three", 3)]


def test_type_import_line_numbers_survive_a_block_comment():
    src = '\n\n/*\n * @param {import("@web/late").T}\n */\n'
    assert ji.collect_type_imports(src) == [("@web/late", 4)]


def test_a_type_import_inside_a_string_is_not_collected():
    src = 'const s = "import(\\"@web/nope\\")";\n'
    assert ji.collect_type_imports(src) == []
