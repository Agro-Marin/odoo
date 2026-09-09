from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import module_category_vocabulary as gate


class TestTheXmlIdRule:
    @pytest.mark.parametrize(
        ("segments", "expected"),
        [
            (["Accounting"], "module_category_accounting"),
            (["Supply Chain", "IoT"], "module_category_supply_chain_iot"),
            (["Sales", "Point of Sale"], "module_category_sales_point_of_sale"),
            (["Research & Development"], "module_category_research_and_development"),
        ],
    )
    def test_the_path_is_what_names_the_record(self, segments, expected):
        assert gate.category_xmlid(segments) == expected

    def test_case_is_not_part_of_the_identity(self):
        # "Sales/Point Of Sale" and "Sales/Point of Sale" are one category, so a
        # database stores whichever spelling the module scan reached first. Ten
        # manifests carried the second spelling and the name was decided by load
        # order, which is why the sweep normalised them rather than leaving it.
        assert gate.category_xmlid(["Sales", "Point Of Sale"]) == gate.category_xmlid(
            ["Sales", "Point of Sale"]
        )


class TestRootDeclared:
    def _tree(self, tmp_path, monkeypatch, manifests, declared_xml):
        root = tmp_path / "addons"
        for name, category in manifests.items():
            module = root / name
            module.mkdir(parents=True)
            (module / "__manifest__.py").write_text(
                '{"name": "x", "category": %r}' % category, encoding="utf-8"
            )
        data = root / "base_like" / "data"
        data.mkdir(parents=True)
        (data / "categories.xml").write_text(declared_xml, encoding="utf-8")
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])
        return root

    DECLARED = """<odoo>
        <record id="module_category_sales" model="ir.module.category">
            <field name="name">Sales</field>
        </record>
        <record id="module_category_human_resources" model="ir.module.category">
            <field name="name">Human Resources</field>
        </record>
    </odoo>"""

    def test_a_declared_root_passes(self, tmp_path, monkeypatch):
        self._tree(tmp_path, monkeypatch, {"sale": "Sales/Sales"}, self.DECLARED)
        assert gate.measure() == []

    def test_a_root_no_data_file_declares_is_reported(self, tmp_path, monkeypatch):
        self._tree(tmp_path, monkeypatch, {"fleet_x": "Fleet"}, self.DECLARED)
        found = gate.measure()
        assert [v.rule for v in found] == ["root-declared"]
        assert "module_category_fleet" in found[0].detail

    def test_only_the_root_segment_has_to_be_declared(self, tmp_path, monkeypatch):
        # A module has always been free to name its own leaf; it is the root the
        # app launcher reads as a group heading, so it is the root that is closed.
        self._tree(
            tmp_path,
            monkeypatch,
            {"hr_x": "Human Resources/Something Nobody Declared"},
            self.DECLARED,
        )
        assert gate.measure() == []


class TestPathImpliesParent:
    def _declared(self, tmp_path, monkeypatch, xml):
        root = tmp_path / "addons"
        module = root / "any"
        module.mkdir(parents=True)
        (module / "__manifest__.py").write_text(
            '{"name": "x", "category": "Services/Project"}', encoding="utf-8"
        )
        (module / "categories.xml").write_text(xml, encoding="utf-8")
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])

    PARENTLESS = """<odoo>
        <record id="module_category_services" model="ir.module.category">
            <field name="name">Services</field>
        </record>
        <record id="module_category_services_helpdesk" model="ir.module.category">
            <field name="name">Helpdesk</field>
        </record>
    </odoo>"""

    PARENTED = PARENTLESS.replace(
        '<field name="name">Helpdesk</field>',
        '<field name="name">Helpdesk</field>'
        '<field name="parent_id" ref="module_category_services"/>',
    )

    def test_a_leaf_declared_as_a_root_is_reported(self, tmp_path, monkeypatch):
        self._declared(tmp_path, monkeypatch, self.PARENTLESS)
        found = gate.measure()
        assert [v.rule for v in found] == ["path-implies-parent"]
        assert found[0].where == "module_category_services_helpdesk"

    def test_declaring_the_parent_settles_it(self, tmp_path, monkeypatch):
        self._declared(tmp_path, monkeypatch, self.PARENTED)
        assert gate.measure() == []

    def test_a_root_whose_path_implies_nothing_is_left_alone(
        self, tmp_path, monkeypatch
    ):
        # `module_category_services` implies no parent, so a parentless top-level
        # category is the normal shape and must not be reported. 22 of base's 27
        # records are exactly this.
        self._declared(
            tmp_path,
            monkeypatch,
            """<odoo>
                <record id="module_category_services" model="ir.module.category">
                    <field name="name">Services</field>
                </record>
            </odoo>""",
        )
        assert gate.measure() == []

    def test_a_fully_qualified_id_is_normalised(self, tmp_path, monkeypatch):
        # base's own data file declares one record as
        # `id="base.module_category_human_resources_referrals"`, unlike its 26
        # siblings. A scan keying on the raw id does not match it, and reports
        # four where there are five.
        self._declared(
            tmp_path,
            monkeypatch,
            """<odoo>
                <record id="module_category_services" model="ir.module.category">
                    <field name="name">Services</field>
                </record>
                <record id="base.module_category_services_helpdesk"
                        model="ir.module.category">
                    <field name="name">Helpdesk</field>
                </record>
            </odoo>""",
        )
        assert [v.rule for v in gate.measure()] == ["path-implies-parent"]


class TestRefusals:
    def test_a_tree_with_no_manifest_refuses_rather_than_passing(
        self, tmp_path, monkeypatch
    ):
        empty = tmp_path / "addons"
        empty.mkdir()
        monkeypatch.setattr(gate, "scan_roots", lambda: [empty])
        with pytest.raises(RuntimeError):
            gate.measure()

    def test_a_tree_with_no_declared_category_refuses(self, tmp_path, monkeypatch):
        root = tmp_path / "addons"
        (root / "sale").mkdir(parents=True)
        (root / "sale" / "__manifest__.py").write_text(
            '{"name": "x", "category": "Sales/Sales"}', encoding="utf-8"
        )
        monkeypatch.setattr(gate, "scan_roots", lambda: [root])
        with pytest.raises(RuntimeError):
            gate.measure()
