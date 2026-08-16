from pathlib import Path

import js_import_resolution as jir


def _addon(root: Path, name: str, files: dict[str, str]) -> Path:
    static = root / name / "static"
    for rel, body in files.items():
        p = static / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    static.mkdir(parents=True, exist_ok=True)
    return static


def test_unresolvable_relative_specifier_is_reported(tmp_path):
    statics = {
        "web": _addon(
            tmp_path,
            "web",
            {
                "src/core/a.js": 'import { x } from "./missing.js";\n',
                "src/core/b.js": "export const x = 1;\n",
            },
        )
    }
    found, files, checked = jir.find_unresolved(statics, tmp_path)
    assert files == 2 and checked == 1
    assert len(found) == 1
    assert found[0].specifier == "./missing.js"
    assert found[0].file.endswith("src/core/a.js")


def test_resolvable_relative_specifier_is_clean(tmp_path):
    statics = {
        "web": _addon(
            tmp_path,
            "web",
            {
                "src/core/a.js": 'import { x } from "./b.js";\n',
                "src/core/b.js": "export const x = 1;\n",
            },
        )
    }
    found, _, checked = jir.find_unresolved(statics, tmp_path)
    assert found == [] and checked == 1


def test_extensionless_and_index_forms_resolve(tmp_path):
    statics = {
        "web": _addon(
            tmp_path,
            "web",
            {
                "src/a.js": 'import "./b";\nimport "./dir";\n',
                "src/b.js": "export const x = 1;\n",
                "src/dir/index.js": "export const y = 2;\n",
            },
        )
    }
    found, _, checked = jir.find_unresolved(statics, tmp_path)
    assert found == [] and checked == 2


def test_the_fields_move_shape_is_caught(tmp_path):
    statics = {
        "web": _addon(
            tmp_path,
            "web",
            {
                "tests/web_test_helpers.js": "export const mountView = 1;\n",
                "tests/fields/basic/email/email_field.test.js": 'import { mountView } from "../../web_test_helpers.js";\n',
                "tests/fields/basic/url/url_field.test.js": 'import { mountView } from "../../../web_test_helpers.js";\n',
            },
        )
    }
    found, _, _ = jir.find_unresolved(statics, tmp_path)
    assert len(found) == 1
    assert found[0].file.endswith("email_field.test.js")
    assert found[0].specifier == "../../web_test_helpers.js"


def test_tests_subtree_is_scanned_not_only_src(tmp_path):
    statics = {
        "web": _addon(tmp_path, "web", {"tests/a.test.js": 'import "./nope.js";\n'})
    }
    found, files, _ = jir.find_unresolved(statics, tmp_path)
    assert files == 1 and len(found) == 1


def test_addon_specifier_resolves_into_static_src(tmp_path):
    statics = {
        "web": _addon(
            tmp_path,
            "web",
            {
                "src/core/registry.js": "export const registry = 1;\n",
                "src/a.js": 'import { registry } from "@web/core/registry";\n',
            },
        )
    }
    found, _, checked = jir.find_unresolved(statics, tmp_path)
    assert found == [] and checked == 1


def test_addon_dotdot_specifier_resolves_into_static(tmp_path):
    statics = {
        "web": _addon(
            tmp_path,
            "web",
            {
                "tests/web_test_helpers.js": "export const m = 1;\n",
                "tests/a.test.js": 'import { m } from "@web/../tests/web_test_helpers";\n',
            },
        )
    }
    found, _, checked = jir.find_unresolved(statics, tmp_path)
    assert found == [] and checked == 1


def test_missing_addon_specifier_is_reported(tmp_path):
    statics = {
        "web": _addon(tmp_path, "web", {"src/a.js": 'import "@web/core/gone";\n'})
    }
    found, _, _ = jir.find_unresolved(statics, tmp_path)
    assert len(found) == 1 and found[0].specifier == "@web/core/gone"


def test_cross_addon_specifier_is_checked(tmp_path):
    statics = {
        "web": _addon(
            tmp_path, "web", {"src/core/registry.js": "export const r = 1;\n"}
        ),
        "mail": _addon(
            tmp_path,
            "mail",
            {
                "src/ok.js": 'import "@web/core/registry";\n',
                "src/bad.js": 'import "@web/core/nope";\n',
            },
        ),
    }
    found, _, checked = jir.find_unresolved(statics, tmp_path)
    assert checked == 2
    assert [f.specifier for f in found] == ["@web/core/nope"]


def test_bare_specifiers_are_ignored(tmp_path):
    statics = {
        "web": _addon(
            tmp_path,
            "web",
            {"src/a.js": 'import { Component } from "@odoo/owl";\nimport "luxon";\n'},
        )
    }
    found, _, checked = jir.find_unresolved(statics, tmp_path)
    assert found == [] and checked == 0


def test_absent_addon_is_skipped_not_failed(tmp_path):
    statics = {
        "web": _addon(
            tmp_path, "web", {"src/a.js": 'import "@web_studio/client_action/x";\n'}
        )
    }
    found, _, checked = jir.find_unresolved(statics, tmp_path)
    assert found == [] and checked == 0


def test_type_only_and_commented_imports_are_ignored(tmp_path):
    statics = {
        "web": _addon(
            tmp_path,
            "web",
            {
                "src/a.js": (
                    '/** @import { X } from "./gone_type" */\n'
                    '/** @param {import("./also_gone").Y} y */\n'
                    '// import "./commented_out.js";\n'
                    "export const f = (y) => y;\n"
                )
            },
        )
    }
    found, _, checked = jir.find_unresolved(statics, tmp_path)
    assert found == [] and checked == 0


def test_vendored_lib_trees_are_not_governed(tmp_path):
    statics = {
        "web": _addon(
            tmp_path, "web", {"src/lib/vendor/thing.js": 'import "./nope.js";\n'}
        )
    }
    found, files, _ = jir.find_unresolved(statics, tmp_path)
    assert files == 0 and found == []


def test_real_tree_is_scanned_and_is_clean():
    found, files, checked = jir.find_unresolved()
    assert files > 5000, f"expected the whole addons tree, walked {files} files"
    assert checked > 20000, f"expected ~22k first-party specifiers, checked {checked}"
    assert found == [], f"unresolvable specifiers on HEAD: {found}"
