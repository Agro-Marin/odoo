import js_template_binding as jtb
import pytest

pytestmark = pytest.mark.skipif(
    not jtb.shutil.which("node"), reason="node not on PATH (run `npm ci`)"
)


@pytest.fixture
def tree(tmp_path):
    def write(rel, text):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    write.root = tmp_path
    return write


def _run(tree):
    js = sorted(tree.root.rglob("*.js"))
    xml = sorted(tree.root.rglob("*.xml"))
    return jtb.find_findings(jtb.run_analyzer(js, xml))


def component(name, template, body=""):
    return (
        "import { Component } from '@odoo/owl';\n"
        f"export class {name} extends Component {{\n"
        f'    static template = "{template}";\n'
        f"{body}"
        "}\n"
    )


def test_a_missing_method_on_an_arrow_handler_is_caught(tree):
    tree("a.js", component("Bar", "web.Bar"))
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n'
        '  <button t-on-click="() => this.onClick(action)">x</button>\n'
        "</t>\n</templates>\n",
    )
    findings, counts = _run(tree)
    assert counts["templates_checked"] == 1
    assert [(f.member, f.component) for f in findings] == [("onClick", "Bar")]


def test_a_method_the_class_declares_is_silent(tree):
    tree("a.js", component("Bar", "web.Bar", "    onClick() {}\n"))
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n'
        '  <button t-on-click="() => this.onClick()">x</button>\n'
        "</t>\n</templates>\n",
    )
    assert _run(tree)[0] == []


def test_qweb_boolean_operators_do_not_make_a_template_unparsable(tree):
    tree("a.js", component("Bar", "web.Bar", "    ok() {}\n"))
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n'
        '  <div t-if="ok() and not props.hidden or ok()">x</div>\n'
        "</t>\n</templates>\n",
    )
    findings, counts = _run(tree)
    assert counts["skipped_unparsable"] == 0, "QWeb's and/or/not must be normalised"
    assert findings == []


def test_call_syntax_inside_a_string_is_not_a_call(tree):
    tree("a.js", component("Bar", "web.Bar"))
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n'
        "  <div t-att-style=\"'background: url(' + props.src + ')'\"/>\n"
        "</t>\n</templates>\n",
    )
    assert _run(tree)[0] == []


def test_an_optionally_called_name_is_not_required(tree):
    tree("a.js", component("Bar", "web.Bar"))
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n'
        '  <div t-if="!!showCoverImage?.()"/>\n'
        '  <div t-if="!!this.other?.()"/>\n'
        "</t>\n</templates>\n",
    )
    assert _run(tree)[0] == []


def test_an_inherited_method_counts(tree):
    tree("base.js", "export class Base { helper() {} }\n")
    tree(
        "a.js",
        'import { Base } from "./base";\n'
        'export class Bar extends Base {\n    static template = "web.Bar";\n}\n',
    )
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n  <div t-if="this.helper()"/>\n'
        "</t>\n</templates>\n",
    )
    assert _run(tree)[0] == []


def test_a_mixin_installed_with_object_assign_counts(tree):
    tree(
        "a.js",
        "const mixin = { fromMixin() {} };\n"
        'export class Bar { static template = "web.Bar"; }\n'
        "Object.assign(Bar.prototype, mixin);\n",
    )
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n  <div t-if="fromMixin()"/>\n'
        "</t>\n</templates>\n",
    )
    assert _run(tree)[0] == []


def test_a_mixin_installed_through_a_bespoke_installer_counts(tree):
    tree("m.js", "export const stylingMixin = { getColumnClass() {} };\n")
    tree(
        "a.js",
        'import { stylingMixin } from "./m";\n'
        'export class Bar { static template = "web.Bar"; }\n'
        "function install(mixin, name) {\n"
        "    const descriptors = Object.getOwnPropertyDescriptors(mixin);\n"
        "    Object.defineProperties(Bar.prototype, descriptors);\n"
        "}\n"
        'install(stylingMixin, "stylingMixin");\n',
    )
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n  <div t-if="getColumnClass({})"/>\n'
        "</t>\n</templates>\n",
    )
    assert _run(tree)[0] == []


def test_a_patched_method_counts(tree):
    tree("a.js", component("Bar", "web.Bar"))
    tree(
        "p.js",
        'import { patch } from "@web/core/utils/patch";\n'
        'import { Bar } from "./a";\n'
        "patch(Bar.prototype, { added() {} });\n",
    )
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n  <div t-if="this.added()"/>\n'
        "</t>\n</templates>\n",
    )
    assert _run(tree)[0] == []


def test_a_template_owned_by_two_components_is_skipped_and_counted(tree):
    tree("a.js", component("One", "web.Shared") + component("Two", "web.Shared"))
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Shared">\n  <div t-if="this.nope()"/>\n'
        "</t>\n</templates>\n",
    )
    findings, counts = _run(tree)
    assert findings == []
    assert counts["skipped_unowned"] == 1
    assert counts["templates_checked"] == 0


def test_an_inheriting_template_is_skipped_and_counted(tree):
    tree("a.js", component("Bar", "web.Bar"))
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar" t-inherit="web.Other">\n'
        '  <div t-if="this.nope()"/>\n</t>\n</templates>\n',
    )
    findings, counts = _run(tree)
    assert findings == []
    assert counts["skipped_inherit"] == 1


def test_loop_and_set_bindings_are_in_scope(tree):
    tree("a.js", component("Bar", "web.Bar"))
    tree(
        "a.xml",
        '<templates>\n<t t-name="web.Bar">\n'
        '  <t t-set="helper" t-value="1"/>\n'
        '  <t t-foreach="props.items" t-as="row" t-key="row.id">\n'
        '    <div t-if="helper"/>\n'
        "  </t>\n</t>\n</templates>\n",
    )
    assert _run(tree)[0] == []
