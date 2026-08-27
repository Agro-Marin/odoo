import js_shadow_root as jsr
import pytest

RAW = """/** @odoo-module native */

export function makeShadow(root) {
    const shadow = root.attachShadow({ mode: "open" });
    return shadow;
}
"""

THROUGH_HELPER = """/** @odoo-module native */

import { attachShadowRoot } from "@web/core/utils/dom/ui";

export function makeShadow(root) {
    return attachShadowRoot(root);
}
"""

HELPER_ITSELF = """/** @odoo-module native */

export function attachShadowRoot(host, init = { mode: "open" }) {
    host.setAttribute("data-shadow-host", "");
    return host.shadowRoot ?? host.attachShadow(init);
}
"""


@pytest.fixture
def tree(tmp_path):
    def write(rel, text, addon="web"):
        path = tmp_path / addon / "static" / "src" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    write.statics = lambda addon="web": {addon: tmp_path / addon / "static"}
    write.root = tmp_path
    return write


def _find(tree, addon="web", helper=jsr.HELPER):
    return jsr.find_raw_attachments(tree.statics(addon), root=tree.root, helper=helper)


def test_catches_a_raw_attach_shadow(tree):
    tree("embed/boot_helpers.js", RAW)
    findings, scanned = _find(tree)
    assert scanned == 1
    assert [f.file for f in findings] == ["web/static/src/embed/boot_helpers.js"]
    assert findings[0].line == 4


def test_a_call_through_the_helper_is_clean(tree):
    tree("embed/boot_helpers.js", THROUGH_HELPER)
    findings, _scanned = _find(tree)
    assert findings == []


def test_the_helper_itself_is_where_the_one_real_call_lives(tree):
    tree("core/utils/dom/ui.js", HELPER_ITSELF)
    findings, _scanned = _find(tree, helper="web/static/src/core/utils/dom/ui.js")
    assert findings == []
    # ...and it is only exempt under that exact path
    findings, _scanned = _find(tree, helper="somewhere/else.js")
    assert len(findings) == 1


def test_every_call_in_a_file_is_reported_not_just_the_first(tree):
    tree("a.js", RAW + "\n" + RAW.replace("makeShadow", "makeOther"))
    findings, _scanned = _find(tree)
    assert len(findings) == 2
    assert findings[0].line < findings[1].line


def test_optional_chaining_and_whitespace_do_not_hide_it(tree):
    tree("a.js", "const s = root . attachShadow ({ mode: 'open' });\n")
    findings, _scanned = _find(tree)
    assert len(findings) == 1


def test_the_word_alone_is_not_a_call(tree):
    tree("a.js", '// mention attachShadow in prose\nconst x = "attachShadow";\n')
    findings, _scanned = _find(tree)
    assert findings == []


def test_tests_are_not_scanned(tmp_path):
    # A test that attaches a raw shadow root to prove the traversal ignores it
    # is asserting this rule, not breaking it.
    path = tmp_path / "web" / "static" / "tests" / "a.test.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RAW, encoding="utf-8")
    findings, scanned = jsr.find_raw_attachments(
        {"web": tmp_path / "web" / "static"}, root=tmp_path
    )
    assert scanned == 0
    assert findings == []


def test_the_live_tree_is_clean():
    findings, scanned = jsr.find_raw_attachments()
    assert scanned > 1000, "the scan found no tree — the assertion would be vacuous"
    assert findings == [], "\n".join(str(f) for f in findings)
