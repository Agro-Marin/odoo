import textwrap

from lxml import etree

from odoo.tests.common import BaseCase, no_retry

from . import _xml_rules, _xml_scan
from ._xml_identity import PARSER
from .lint_case import LintCase


class TestXmlLint(LintCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _xml_scan.findings()

    def test_every_rule_is_held_at_its_floor(self):
        for rule in _xml_rules.RULES:
            with self.subTest(rule=rule.name):
                self.assert_ratchet(
                    sorted(
                        _xml_scan.findings().get(rule.name, []),
                        key=lambda finding: finding.sort_key,
                    ),
                    rule.gate,
                    f"{rule.name} finding(s)",
                    f"{rule.advice}.",
                )

    def test_the_scan_reaches_the_data_files(self):
        files = _xml_scan.data_files()
        self.assertGreater(len(files), 3000, "the scan reached almost nothing")
        self.assertTrue(
            any(file.listed for file in files),
            "no data file is recognised as listed by its manifest, so the "
            "orphan rule would report every file",
        )
        self.assertGreater(
            len(_xml_scan.context().declared_models),
            1000,
            "the model scan reached almost no _name, so unknown-model would "
            "report every record",
        )

    def test_every_rule_reaches_the_scan(self):
        self.assertEqual(
            sorted(_xml_scan.findings().keys() ^ _xml_rules.BY_NAME.keys()), []
        )


def _file(source: str, *, listed=True, loaded_from_python=False, path="m/views/x.xml"):
    root = etree.fromstring(textwrap.dedent(source).strip().encode(), PARSER)
    return _xml_rules.DataFile(path, "m", root, listed, loaded_from_python)


_CONTEXT = _xml_rules.Context(
    declared_models=frozenset({"res.partner", "ir.ui.view", "ir.actions.act_window"}),
    known_modules=frozenset({"m", "base"}),
)


@no_retry
class TestXmlRules(BaseCase):
    maxDiff = None

    def _run(self, rule: str, source: str, **kwargs) -> list[str]:
        check = _xml_rules.BY_NAME[rule].check
        return [message for _line, message in check(_file(source, **kwargs), _CONTEXT)]

    def test_every_rule_has_a_planted_positive_and_a_clean_negative(self):
        for rule, positive, negative, *rest in _CASES:
            kwargs = rest[0] if rest else {}
            with self.subTest(rule=rule):
                self.assertTrue(
                    self._run(rule, positive, **kwargs),
                    f"{rule} missed the planted case",
                )
                self.assertEqual(
                    self._run(rule, negative), [], f"{rule} flagged the clean case"
                )
        self.assertEqual(
            sorted(_xml_rules.BY_NAME),
            sorted({case[0] for case in _CASES}),
            "every rule must carry a planted positive and a clean negative",
        )

    def test_a_percent_reference_is_not_a_syntax_error(self):
        self.assertEqual(
            self._run(
                "expression-syntax",
                """
                <odoo>
                    <record id="v" model="ir.ui.view">
                        <field name="model">res.partner</field>
                        <field name="arch" type="xml">
                            <form>
                                <field name="a" domain="[('id', '=', %(base.x)d)]"/>
                                <label string="%%(year)s"/>
                            </form>
                        </field>
                    </record>
                </odoo>
                """,
            ),
            [],
        )

    def test_a_qweb_boolean_attribute_is_not_an_expression(self):
        self.assertEqual(
            self._run(
                "expression-syntax",
                """
                <odoo>
                    <template id="t"><input required=""/></template>
                    <record id="v" model="ir.ui.view">
                        <field name="arch" type="xml"><t><input required=""/></t></field>
                    </record>
                </odoo>
                """,
            ),
            [],
        )

    def test_a_groupby_domain_is_reported_once(self):
        source = """
            <odoo>
                <record id="v" model="ir.ui.view">
                    <field name="model">res.partner</field>
                    <field name="arch" type="xml">
                        <search>
                            <filter name="g" domain="" context="{'group_by': 'a'}"/>
                        </search>
                    </field>
                </record>
            </odoo>
        """
        self.assertEqual(self._run("expression-syntax", source), [])
        self.assertEqual(len(self._run("groupby-filter-domain", source)), 1)

    def test_a_scenario_file_loaded_from_python_is_not_an_orphan(self):
        self.assertEqual(
            self._run(
                "orphan-data-file", "<odoo/>", listed=False, loaded_from_python=True
            ),
            [],
        )

    def test_the_command_helper_is_not_a_legacy_tuple(self):
        self.assertEqual(
            self._run(
                "legacy-x2many-command",
                """
                <odoo>
                    <record id="r" model="res.partner">
                        <field name="a" eval="[Command.set([ref('x')]), Command.clear()]"/>
                        <field name="b" eval="[(1, 2), (3, 4)]"/>
                        <field name="c" eval="(0, 0)"/>
                    </record>
                </odoo>
                """,
            ),
            [],
        )


_MODEL_VIEW = """
    <odoo>
        <record id="v" model="ir.ui.view">
            <field name="model">res.partner</field>
            <field name="arch" type="xml">
                {arch}
            </field>
        </record>
    </odoo>
"""


def _view(arch: str) -> str:
    return _MODEL_VIEW.format(arch=arch)


_CASES: tuple[tuple, ...] = (
    (
        "attributes-spec-child",
        _view(
            '<xpath expr="//a" position="attributes"><field name="b"/>'
            '<attribute name="invisible">1</attribute></xpath>'
        ),
        _view(
            '<xpath expr="//a" position="attributes">'
            '<attribute name="invisible">1</attribute></xpath>'
        ),
    ),
    (
        "duplicate-field",
        (
            '<odoo><record id="r" model="res.partner"><field name="a">1</field>'
            '<field name="a">2</field></record></odoo>'
        ),
        (
            '<odoo><record id="r" model="res.partner"><field name="a">1</field>'
            '<field name="b">2</field></record></odoo>'
        ),
    ),
    (
        "expression-syntax",
        _view('<form><field name="a" invisible="state = 1"/></form>'),
        _view('<form><field name="a" invisible="state == 1"/></form>'),
    ),
    (
        "eval-syntax",
        (
            '<odoo><record id="r" model="res.partner"><field name="a" eval=""/>'
            "</record></odoo>"
        ),
        (
            '<odoo><record id="r" model="res.partner"><field name="a" eval="[1]"/>'
            "</record></odoo>"
        ),
    ),
    (
        "xpath-syntax",
        _view('<xpath expr="//a[@b=" position="after"/>'),
        _view('<xpath expr="//a[hasclass(\'b\')]" position="after"/>'),
    ),
    (
        "tree-view",
        _view('<tree><field name="a"/></tree>'),
        _view('<list><field name="a"/></list>'),
    ),
    (
        "removed-attribute",
        _view(
            "<form><field name=\"a\" attrs=\"{'invisible': [('b', '=', 1)]}\"/></form>"
        ),
        _view('<form><field name="a" invisible="b == 1"/></form>'),
    ),
    (
        "kanban-box",
        _view('<kanban><templates><t t-name="kanban-box"/></templates></kanban>'),
        _view('<kanban><templates><t t-name="card"/></templates></kanban>'),
    ),
    (
        "search-item-name",
        _view(
            '<search><group string="G"><filter string="F" domain="[]"/></group></search>'
        ),
        _view(
            '<search><group><filter name="f" string="F" domain="[]"/></group></search>'
        ),
    ),
    (
        "deprecated-output-directive",
        '<odoo><template id="t"><span t-esc="x"/></template></odoo>',
        '<odoo><template id="t"><span t-out="x"/></template></odoo>',
    ),
    (
        "legacy-x2many-command",
        (
            '<odoo><record id="r" model="res.partner">'
            '<field name="a" eval="[(6, 0, [ref(\'x\')])]"/></record></odoo>'
        ),
        (
            '<odoo><record id="r" model="res.partner">'
            '<field name="a" eval="[Command.set([ref(\'x\')])]"/></record></odoo>'
        ),
    ),
    (
        "menuitem-placement",
        '<odoo><menuitem id="menu_a" name="A"/></odoo>',
        '<odoo><record id="r" model="res.partner"/></odoo>',
    ),
    (
        "data-root",
        '<data><record id="r" model="res.partner"/></data>',
        '<odoo><record id="r" model="res.partner"/></odoo>',
    ),
    (
        "orphan-data-file",
        "<odoo/>",
        "<odoo/>",
        {"listed": False},
    ),
    (
        "unknown-model",
        '<odoo><record id="r" model="res.partnerr"/></odoo>',
        '<odoo><record id="r" model="res.partner"/></odoo>',
    ),
    (
        "optional-value",
        _view('<list><field name="a" optional="hidden"/></list>'),
        _view('<list><field name="a" optional="hide"/></list>'),
    ),
    (
        "kanban-template-scope",
        _view(
            '<kanban><templates><t t-name="menu"><t t-set="x" t-value="1"/></t>'
            '<t t-name="card"><div t-if="x"/></t></templates></kanban>'
        ),
        _view(
            '<kanban><templates><t t-name="menu"><t t-set="x" t-value="1"/></t>'
            '<t t-name="card"><t t-set="x" t-value="1"/><div t-if="x"/></t>'
            "</templates></kanban>"
        ),
    ),
    (
        "groupby-filter-domain",
        _view(
            '<search><filter name="g" domain="[]" context="{\'group_by\': \'a\'}"/></search>'
        ),
        _view("<search><filter name=\"g\" context=\"{'group_by': 'a'}\"/></search>"),
    ),
)
