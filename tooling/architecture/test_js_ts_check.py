from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import js_ts_check as gate


def _tree(tmp_path: Path, addon: str = "thing", **files: str) -> Path:
    for key, text in files.items():
        stem, _, ext = key.rpartition("__")
        path = tmp_path / addon / "static" / "src" / f"{stem.replace('___', '/')}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _found(tmp_path: Path, addon: str = "thing", **files: str) -> list[str]:
    return [item.path for item in gate.measure([_tree(tmp_path, addon, **files)])]


CHECKED = "// @ts-check\n/** @odoo-module */\nexport const a = 1;\n"
UNCHECKED = "/** @odoo-module */\nexport const a = 1;\n"


def test_a_file_carrying_the_directive_is_not_reported(tmp_path):
    assert _found(tmp_path, a__js=CHECKED) == []


def test_a_file_without_it_is_reported(tmp_path):
    assert _found(tmp_path, a__js=UNCHECKED) == ["thing/static/src/a.js"]


def test_the_directive_may_follow_the_odoo_module_header(tmp_path):
    assert _found(tmp_path, a__js="/** @odoo-module */\n// @ts-check\nlet a;\n") == []


def test_the_directive_may_follow_a_licence_block(tmp_path):
    text = "/*\n * Part of Odoo. See LICENSE file.\n */\n// @ts-check\nlet a;\n"
    assert _found(tmp_path, a__js=text) == []


def test_the_directive_may_sit_inside_the_licence_block(tmp_path):
    text = "/**\n * Part of Odoo.\n * @ts-check\n */\nlet a;\n"
    assert _found(tmp_path, a__js=text) == []


def test_a_directive_after_the_first_statement_does_not_count(tmp_path):
    # tsc honours the pragma only in the file's leading comment run, so a gate
    # that grepped the whole file would call an inert comment adoption.
    text = "let a = 1;\n// @ts-check\nlet b = 2;\n"
    assert _found(tmp_path, a__js=text) == ["thing/static/src/a.js"]


def test_a_directive_after_a_trailing_statement_on_the_header_line(tmp_path):
    text = "/* header */ let a = 1;\n// @ts-check\n"
    assert _found(tmp_path, a__js=text) == ["thing/static/src/a.js"]


def test_ts_nocheck_is_not_the_directive(tmp_path):
    assert _found(tmp_path, a__js="// @ts-nocheck\nlet a;\n") == [
        "thing/static/src/a.js"
    ]


def test_mjs_is_scanned_too(tmp_path):
    assert _found(tmp_path, a__mjs=UNCHECKED) == ["thing/static/src/a.mjs"]


@pytest.mark.parametrize("where", ["tests", "lib"])
def test_only_static_src_is_scanned(tmp_path, where):
    outside = tmp_path / "thing" / "static" / where / "b.js"
    outside.parent.mkdir(parents=True)
    outside.write_text(UNCHECKED, encoding="utf-8")
    assert _found(tmp_path, a__js=CHECKED) == []


def test_a_nested_static_src_still_counts(tmp_path):
    assert _found(tmp_path, deep___a__js=UNCHECKED) == ["thing/static/src/deep/a.js"]


def test_an_empty_tree_is_refused(tmp_path):
    (tmp_path / "thing" / "static" / "src").mkdir(parents=True)
    (tmp_path / "thing" / "static" / "src" / "styles.scss").write_text("a{}\n")
    with pytest.raises(RuntimeError):
        gate.measure([tmp_path])


def test_addon_narrows_every_root(tmp_path):
    _tree(tmp_path, "web", a__js=UNCHECKED)
    _tree(tmp_path, "mail", b__js=UNCHECKED)
    assert [item.path for item in gate.measure([tmp_path], "web")] == [
        "web/static/src/a.js"
    ]


def test_an_addon_scope_with_no_source_is_refused(tmp_path):
    _tree(tmp_path, "web", a__js=UNCHECKED)
    with pytest.raises(RuntimeError):
        gate.measure([tmp_path], "mail")


def test_an_ungoverned_addon_is_refused_by_the_cli(tmp_path, capsys):
    assert gate.main(["--addon", "hr", "--count", str(tmp_path)]) == 2
    assert "not a governed scope" in capsys.readouterr().err


def test_every_governed_addon_exists_in_this_tree():
    missing = [
        addon
        for addon in gate.GOVERNED_ADDONS
        if not (gate.ROOT / "addons" / addon / "static" / "src").is_dir()
    ]
    assert missing == []


CONFIG_INLINE = """
export default makeConfig({
    modules: ["thing"],
    ignores: [
        // a comment naming a path that is NOT a pattern
        "thing/static/src/vendored/**",
    ],
});
"""

CONFIG_NAMED = """
const LOCAL_IGNORES = [
    "thing/static/src/vendored/**",
];

export default makeConfig({
    modules: ["thing"],
    ignores: LOCAL_IGNORES,
});
"""


@pytest.mark.parametrize("config", [CONFIG_INLINE, CONFIG_NAMED])
def test_the_eslint_ignore_list_is_obeyed(tmp_path, config):
    (tmp_path / "eslint.config.mjs").write_text(config, encoding="utf-8")
    assert _found(tmp_path, vendored___big__js=UNCHECKED, own__js=UNCHECKED) == [
        "thing/static/src/own.js"
    ]


def test_a_negation_re_includes_what_an_earlier_pattern_ignored(tmp_path):
    (tmp_path / "eslint.config.mjs").write_text(
        CONFIG_INLINE.replace(
            '"thing/static/src/vendored/**",',
            '"thing/static/src/vendored/**",\n        '
            '"!thing/static/src/vendored/ours.js",',
        ),
        encoding="utf-8",
    )
    assert _found(tmp_path, vendored___ours__js=UNCHECKED) == [
        "thing/static/src/vendored/ours.js"
    ]


def test_a_config_whose_shape_changed_is_refused_rather_than_read_as_empty(tmp_path):
    (tmp_path / "eslint.config.mjs").write_text(
        "export default [{ ignores: [] }];\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError):
        gate.measure([_tree(tmp_path, a__js=UNCHECKED)])


def test_the_shared_ignores_come_from_the_repo_config():
    assert "**/static/lib/**/*" in gate.eslint_ignores(gate.ROOT)


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("a/b/**", "a/b/c/d.js", True),
        ("a/b/**", "a/bx/c.js", False),
        ("a/*.js", "a/b.js", True),
        ("a/*.js", "a/b/c.js", False),
        ("**/static/lib/**/*", "x/y/static/lib/z/a.js", True),
        ("**/static/lib/**/*", "static/lib/a.js", True),
        ("**/static/lib/**/*", "x/static/src/a.js", False),
    ],
)
def test_glob_translation(pattern, path, expected):
    assert bool(gate.glob_to_regex(pattern).match(path)) is expected
