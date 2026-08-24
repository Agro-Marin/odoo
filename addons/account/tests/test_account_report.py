from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestAccountReport(AccountTestInvoicingCommon):
    def test_copy_report(self):
        report = self.env["account.report"].create(
            {
                "name": "Report To Copy",
                "column_ids": [
                    Command.create(
                        {
                            "name": "balance",
                            "sequence": 1,
                            "expression_label": "balance",
                        }
                    )
                ],
                "line_ids": [
                    Command.create(
                        {
                            "name": "test_line_1",
                            "code": "test_line_1",
                            "sequence": 1,
                            "expression_ids": [
                                Command.create(
                                    {
                                        "date_scope": "strict_range",
                                        "engine": "external",
                                        "formula": "sum",
                                        "label": "balance",
                                    }
                                ),
                            ],
                        }
                    ),
                    Command.create(
                        {
                            "name": "test_line_2",
                            "code": "test_line_2",
                            "sequence": 2,
                            "expression_ids": [
                                Command.create(
                                    {
                                        "date_scope": "strict_range",
                                        "engine": "aggregation",
                                        "formula": "test_line_1.balance",
                                        "subformula": "if_other_expr_above(test_line_1.balance, USD(0))",
                                        "label": "balance",
                                    }
                                )
                            ],
                        }
                    ),
                ],
            }
        )
        copy = report.copy()
        self.assertEqual(copy.line_ids[0].code, "test_line_1_COPY")
        self.assertEqual(copy.line_ids[1].code, "test_line_2_COPY")
        expression = copy.line_ids[1].expression_ids
        self.assertEqual(expression.formula, "test_line_1_COPY.balance")
        self.assertEqual(
            expression.subformula,
            "if_other_expr_above(test_line_1_COPY.balance, USD(0))",
        )

        with self.assertRaisesRegex(
            ValidationError,
            "Invalid formula for expression 'balance' of line 'test_line_2'",
        ):
            expression.write(
                {
                    "engine": "account_codes",
                    "formula": "test(12)",
                },
            )

    def test_domain_formula_malformed_raises_validation_error(self):
        report = self.env["account.report"].create({"name": "Domain Formula Report"})
        line = self.env["account.report.line"].create(
            {"name": "dom_line", "report_id": report.id}
        )
        for bad_formula in ("summ(domain)", "just text", "sum missing parens"):
            with self.assertRaisesRegex(ValidationError, "Invalid domain formula"):
                line.domain_formula = bad_formula
        line.domain_formula = "sum([('account_id.account_type', '=', 'income')])"
        self.assertTrue(line.expression_ids)

    def _create_report(self, name, **vals):
        return self.env["account.report"].create({"name": name, **vals})

    def _create_line(self, report, name, engine, formula, **vals):
        return self.env["account.report.line"].create(
            {
                "report_id": report.id,
                "name": name,
                "expression_ids": [
                    Command.create(
                        {"label": "balance", "engine": engine, "formula": formula}
                    )
                ],
                **vals,
            }
        )

    def test_copy_report_does_not_chain_code_substitutions(self):
        report = self._create_report("Colliding Codes")
        self._create_line(report, "A", "account_codes", "400", code="AAA", sequence=1)
        self._create_line(
            report, "B", "account_codes", "401", code="AAA_COPY", sequence=2
        )
        self._create_line(
            report,
            "C",
            "aggregation",
            "AAA.balance + AAA_COPY.balance",
            code="CCC",
            sequence=3,
        )

        copied = report.copy()

        self.assertEqual(
            copied.line_ids.mapped("code"), ["AAA_COPY", "AAA_COPY_COPY", "CCC_COPY"]
        )
        self.assertEqual(
            copied.line_ids[2].expression_ids.formula,
            "AAA_COPY.balance + AAA_COPY_COPY.balance",
        )

    def test_formula_shortcut_on_line_without_balance_expression(self):
        report = self._create_report("Shortcut Without Balance")
        line = self.env["account.report.line"].create(
            {
                "report_id": report.id,
                "name": "no balance",
                "expression_ids": [
                    Command.create(
                        {
                            "label": "other",
                            "engine": "account_codes",
                            "formula": "700",
                        }
                    )
                ],
            }
        )

        line.account_codes_formula = "600"

        balance = line.expression_ids.filtered(lambda x: x.label == "balance")
        self.assertEqual(balance.formula, "600")
        self.assertEqual(balance.engine, "account_codes")

    def test_aggregation_terms_ignore_numeric_literals(self):
        report = self._create_report("Numeric Terms")
        line = self._create_line(
            report, "num", "aggregation", "1e5 + 12.5 + AAA.balance", code="NUM"
        )
        self.assertEqual(
            dict(line.expression_ids._get_aggregation_terms_details()),
            {"AAA": {"balance"}},
        )

    def test_parent_line_cycle_is_rejected(self):
        report = self._create_report("Cyclic Lines")
        parent = self._create_line(report, "A", "account_codes", "1", sequence=1)
        child = self._create_line(
            report, "B", "account_codes", "2", sequence=2, parent_id=parent.id
        )
        with self.assertRaises(ValidationError):
            parent.parent_id = child
            parent.flush_recordset()

    def test_report_unlink_cleans_up_tax_tags(self):
        country = self.env.ref("base.be")
        report = self._create_report(
            "Tag Owner", country_id=country.id, availability_condition="country"
        )
        line = self._create_line(report, "tagged", "tax_tags", "TESTTAGUNLINK")
        tag_domain = [
            ("name", "=", "TESTTAGUNLINK"),
            ("country_id", "=", country.id),
        ]
        tag_model = self.env["account.account.tag"].with_context(
            active_test=False, lang="en_US"
        )
        self.assertTrue(tag_model.search(tag_domain))

        line.report_id.unlink()

        self.assertFalse(tag_model.search(tag_domain))

    def test_report_unlink_removes_its_columns(self):
        report = self._create_report(
            "Column Owner",
            column_ids=[
                Command.create({"name": "Balance", "expression_label": "balance"})
            ],
        )
        column = report.column_ids
        report.unlink()
        self.assertFalse(column.exists())

    def test_writing_one_option_filter_with_the_root_keeps_the_others_inherited(self):
        # Option filters must keep one compute each. Fields sharing a compute form one
        # group in registry.field_computed, and write() protects the whole group as soon
        # as any one member is in vals -- so this write, which is what a module update
        # replays from a variant's XML, would resolve every other filter to False.
        root = self._create_report(
            "Inherit Root", filter_partner=True, filter_journals=True
        )
        variant = self._create_report("Inherit Variant")
        variant.write({"root_report_id": root.id, "filter_journals": False})
        variant.flush_recordset()
        variant.invalidate_recordset()
        self.assertFalse(variant.filter_journals)
        self.assertTrue(variant.filter_partner)

    def test_option_filter_defaults_and_variant_inheritance(self):
        plain = self._create_report("Plain Defaults")
        self.assertEqual(plain.filter_multi_company, "selector")
        self.assertEqual(plain.currency_translation, "cta")
        self.assertEqual(plain.default_opening_date_filter, "previous_month")
        self.assertTrue(plain.filter_date_range)
        self.assertFalse(plain.filter_journals)

        root = self._create_report(
            "Root", filter_journals=True, currency_translation="current"
        )
        variant = self._create_report("Variant", root_report_id=root.id)
        self.assertTrue(variant.filter_journals)
        self.assertEqual(variant.currency_translation, "current")

    def test_accessible_report_ids_parses_the_action_context(self):
        report = self._create_report("Has An Action")
        other = self._create_report("Has No Action")
        self.assertEqual(report._get_accessible_report_ids(), set())

        self.env["ir.actions.client"].create(
            {
                "name": "Has An Action",
                "tag": "account_report",
                "context": '{"report_id": %d}' % report.id,
            }
        )
        self.assertEqual(report._get_accessible_report_ids(), {report.id})
        self.assertEqual(other._get_accessible_report_ids(), set())

    def test_accessible_report_ids_ignores_unparseable_contexts(self):
        report = self._create_report("Dynamic Context")
        self.env["ir.actions.client"].create(
            {
                "name": "Dynamic Context",
                "tag": "account_report",
                "context": "{'report_id': active_id}",
            }
        )
        self.assertEqual(report._get_accessible_report_ids(), set())

    def test_unlink_keeps_a_tag_another_expression_spells_with_a_sign(self):
        country = self.env.ref("base.be")
        tag_model = self.env["account.account.tag"].with_context(
            active_test=False, lang="en_US"
        )
        tag_domain = [("name", "=", "SIGNEDTAG"), ("country_id", "=", country.id)]

        plain = self._create_line(
            self._create_report(
                "Plain Sign",
                country_id=country.id,
                availability_condition="country",
            ),
            "plain",
            "tax_tags",
            "SIGNEDTAG",
        )
        negated = self._create_line(
            self._create_report(
                "Negated Sign",
                country_id=country.id,
                availability_condition="country",
            ),
            "negated",
            "tax_tags",
            "-SIGNEDTAG",
        )
        self.assertEqual(len(tag_model.search(tag_domain)), 1)

        plain.expression_ids.unlink()

        self.assertTrue(negated.expression_ids.exists())
        self.assertTrue(
            tag_model.search(tag_domain),
            "A tag another expression still spells as '-NAME' must survive.",
        )

    def test_refused_report_deletion_keeps_its_lines(self):
        # ondelete methods run in alphabetical order, so the hook that unlinks the
        # child lines must not be a separate method sorting before the variant guard.
        root = self._create_report("Guarded Root")
        line = self._create_line(root, "kept", "account_codes", "400", code="KEEPME")
        self._create_report("Guarded Variant", root_report_id=root.id)

        # Not self.assertRaises: it opens a savepoint (tests/common.py::_assertRaises),
        # which rolls back whatever the refused unlink had already written and would
        # make the assertions below pass no matter what.
        try:
            root.unlink()
        except UserError:
            pass
        else:
            self.fail("deleting a report with variants should have been refused")

        self.assertTrue(line.exists())
        self.assertTrue(root.exists())

    def test_unlink_keeps_a_tag_spelled_with_repeated_signs(self):
        country = self.env.ref("base.be")
        tag_model = self.env["account.account.tag"].with_context(
            active_test=False, lang="en_US"
        )
        tag_domain = [("name", "=", "DOUBLESIGN"), ("country_id", "=", country.id)]
        plain = self._create_line(
            self._create_report(
                "Plain Double", country_id=country.id, availability_condition="country"
            ),
            "plain",
            "tax_tags",
            "DOUBLESIGN",
        )
        self._create_line(
            self._create_report(
                "Negated Double",
                country_id=country.id,
                availability_condition="country",
            ),
            "negated",
            "tax_tags",
            "--DOUBLESIGN",
        )
        self.assertEqual(len(tag_model.search(tag_domain)), 1)

        plain.expression_ids.unlink()

        self.assertTrue(tag_model.search(tag_domain))

    def test_unlink_still_removes_a_tag_whose_name_is_a_substring(self):
        country = self.env.ref("base.be")
        tag_model = self.env["account.account.tag"].with_context(
            active_test=False, lang="en_US"
        )
        owner = self._create_line(
            self._create_report(
                "Substring Owner",
                country_id=country.id,
                availability_condition="country",
            ),
            "owner",
            "tax_tags",
            "SUBTAG",
        )
        self._create_line(
            self._create_report(
                "Substring Neighbour",
                country_id=country.id,
                availability_condition="country",
            ),
            "neighbour",
            "tax_tags",
            "PRESUBTAGPOST",
        )

        owner.expression_ids.unlink()

        self.assertFalse(
            tag_model.search(
                [("name", "=", "SUBTAG"), ("country_id", "=", country.id)]
            ),
            "A merely-overlapping formula must not keep an orphan tag alive.",
        )

    def test_changing_country_reuses_an_existing_tag_of_that_name(self):
        belgium = self.env.ref("base.be")
        italy = self.env.ref("base.it")
        tag_model = self.env["account.account.tag"].with_context(
            active_test=False, lang="en_US"
        )
        moving = self._create_report(
            "Moving Report",
            country_id=belgium.id,
            availability_condition="country",
        )
        self._create_line(moving, "moving", "tax_tags", "SHAREDNAME")
        staying = self._create_report(
            "Italian Report", country_id=italy.id, availability_condition="country"
        )
        self._create_line(staying, "staying", "tax_tags", "SHAREDNAME")
        self.assertEqual(
            len(tag_model.search([("name", "=", "SHAREDNAME")])),
            2,
            "one tag per country to start with",
        )

        moving.write({"country_id": italy.id})

        tags = tag_model.search([("name", "=", "SHAREDNAME")])
        self.assertEqual(tags.country_id, belgium + italy)
        self.assertEqual(
            len(tags), 2, "the Belgian tag must not be moved onto the Italian one"
        )

    def test_changing_country_moves_a_tag_nobody_else_uses(self):
        belgium = self.env.ref("base.be")
        italy = self.env.ref("base.it")
        tag_model = self.env["account.account.tag"].with_context(
            active_test=False, lang="en_US"
        )
        report = self._create_report(
            "Lone Report", country_id=belgium.id, availability_condition="country"
        )
        self._create_line(report, "lone", "tax_tags", "LONETAG")

        report.write({"country_id": italy.id})

        tags = tag_model.search([("name", "=", "LONETAG")])
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags.country_id, italy)

    def test_related_tax_report_expressions_ignores_the_active_language(self):
        belgium = self.env.ref("base.be")
        self.env["res.lang"]._activate_lang("fr_FR")
        report = self._create_report(
            "Translated Tag", country_id=belgium.id, availability_condition="country"
        )
        self._create_line(report, "tagged", "tax_tags", "TRANSTAG")
        tag = (
            self.env["account.account.tag"]
            .with_context(active_test=False, lang="en_US")
            .search([("name", "=", "TRANSTAG"), ("country_id", "=", belgium.id)])
        )
        tag.with_context(lang="fr_FR").name = "ETIQUETTE"

        self.assertTrue(
            tag.with_context(lang="fr_FR")._get_related_tax_report_expressions(),
            "the lookup compares an untranslated formula and must not read a "
            "translated tag name",
        )

    def test_copying_a_report_costs_a_query_per_level_not_per_line(self):
        report = self._create_report("Batched Copy")
        parent = self._create_line(report, "root", "account_codes", "400", code="BC0")
        self.env["account.report.line"].create(
            [
                {
                    "report_id": report.id,
                    "name": f"child{index}",
                    "code": f"BC{index}",
                    "sequence": index,
                    "parent_id": parent.id,
                    "expression_ids": [
                        Command.create(
                            {
                                "label": "balance",
                                "engine": "account_codes",
                                "formula": str(400 + index),
                            }
                        )
                    ],
                }
                for index in range(1, 40)
            ]
        )
        report.flush_recordset()
        report.copy()  # warm

        with self.assertQueryCount(default=15, accountman=15):
            copied = report.copy()
            copied.flush_recordset()

        self.assertEqual(len(copied.line_ids), 40)
        self.assertEqual(len(copied.line_ids.expression_ids), 40)
        self.assertEqual(
            sorted(copied.line_ids.mapped("hierarchy_level")),
            sorted(report.line_ids.mapped("hierarchy_level")),
        )
        self.assertEqual(
            copied.line_ids.filtered(lambda x: x.parent_id).parent_id,
            copied.line_ids.filtered(lambda x: not x.parent_id),
        )

    def test_copied_names_do_not_chain_copy_suffixes(self):
        report = self._create_report("Suffix Base")
        names = [report.copy().name for _ in range(3)]
        self.assertEqual(
            names,
            ["Suffix Base (copy)", "Suffix Base (copy) 2", "Suffix Base (copy) 3"],
        )

    def test_user_groupby_is_seeded_once_and_never_overwritten(self):
        report = self._create_report("Groupby Seed")
        seeded = self.env["account.report.line"].create(
            {"report_id": report.id, "name": "seeded", "groupby": "partner_id"}
        )
        self.assertEqual(seeded.user_groupby, "partner_id")

        explicit = self.env["account.report.line"].create(
            {
                "report_id": report.id,
                "name": "explicit",
                "groupby": "partner_id",
                "user_groupby": "account_id",
            }
        )
        self.assertEqual(explicit.user_groupby, "account_id")

        explicit.write({"groupby": "journal_id"})
        explicit.flush_recordset()
        explicit.invalidate_recordset()
        self.assertEqual(explicit.user_groupby, "account_id")

    def test_strip_formula_returns_instead_of_mutating(self):
        vals = {"formula": "  a   b  "}
        self.assertEqual(
            self.env["account.report.expression"]._strip_formula(vals["formula"]),
            "a b",
        )
        self.assertEqual(vals, {"formula": "  a   b  "})

    def test_a_line_cannot_have_its_parent_in_another_report(self):
        first = self._create_report("Parent Elsewhere A")
        second = self._create_report("Parent Elsewhere B")
        parent = self._create_line(first, "parent", "account_codes", "400", code="PEA")

        with self.assertRaises(ValidationError):
            self._create_line(
                second,
                "child",
                "account_codes",
                "401",
                code="PEB",
                parent_id=parent.id,
            )

    def test_moving_a_line_out_of_its_parents_report_is_refused(self):
        first = self._create_report("Move Out A")
        second = self._create_report("Move Out B")
        parent = self._create_line(first, "parent", "account_codes", "400", code="MOA")
        child = self._create_line(
            first, "child", "account_codes", "401", code="MOB", parent_id=parent.id
        )

        with self.assertRaises(ValidationError):
            child.write({"report_id": second.id})
            child.flush_recordset()

    def test_cross_report_must_name_a_report_that_exists(self):
        report = self._create_report("Cross Source")
        for subformula in (
            "cross_report(999999)",
            "cross_report(no_such.report)",
            "cross_report(base.main_company)",
        ):
            line = self._create_line(
                report,
                f"agg {subformula}",
                "aggregation",
                "OTHER.balance",
                code=f"CR{abs(hash(subformula)) % 10000}",
            )
            line.expression_ids.subformula = subformula
            with self.assertRaises(UserError, msg=subformula):
                line.expression_ids._get_cross_report_id()

    def test_cross_report_accepts_a_real_report_by_id_and_by_xml_id(self):
        report = self._create_report("Cross Source 2")
        target = self.env.ref("account.generic_tax_report")
        line = self._create_line(
            report, "agg", "aggregation", "OTHER.balance", code="CRVALID"
        )
        line.expression_ids.subformula = f"cross_report({target.id})"
        self.assertEqual(line.expression_ids._get_cross_report_id(), target.id)
        line.expression_ids.subformula = "cross_report(account.generic_tax_report)"
        self.assertEqual(line.expression_ids._get_cross_report_id(), target.id)
