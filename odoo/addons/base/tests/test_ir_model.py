import traceback
from contextlib import contextmanager
from unittest.mock import patch

from psycopg import IntegrityError
from psycopg.errors import NotNullViolation
from psycopg.types.json import Json

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import NO_ACCESS
from odoo.models import BaseModel, is_model_definition, pop_field
from odoo.tests import Form, HttpCase, TransactionCase, tagged
from odoo.tests.common import new_test_user
from odoo.tools import SQL, escape_psql, mute_logger


class TestXMLID(TransactionCase):
    def get_data(self, xml_id):
        module, suffix = xml_id.split(".", 1)
        domain = [("module", "=", module), ("name", "=", suffix)]
        return self.env["ir.model.data"].search(domain)

    def test_create(self):
        model = self.env["res.partner.category"]
        xml_id = "test_convert.category_foo"

        data = {"xml_id": xml_id, "values": {"name": "Foo"}}
        category = model._load_records([data])
        self.assertEqual(category, self.env.ref(xml_id, raise_if_not_found=False))
        self.assertEqual(category.name, "Foo")
        self.assertEqual(self.get_data(xml_id).noupdate, False)

        data = {"xml_id": xml_id, "values": {"name": "Bar"}}
        category1 = model._load_records([data], update=True)
        self.assertEqual(category, category1)
        self.assertEqual(category.name, "Bar")
        self.assertEqual(self.get_data(xml_id).noupdate, False)

        data = {"xml_id": xml_id, "values": {"name": "Baz"}, "noupdate": True}
        category2 = model._load_records([data], update=True)
        self.assertEqual(category, category2)
        self.assertEqual(category.name, "Baz")
        self.assertEqual(self.get_data(xml_id).noupdate, False)

    def test_create_noupdate(self):
        model = self.env["res.partner.category"]
        xml_id = "test_convert.category_foo"

        data = {"xml_id": xml_id, "values": {"name": "Foo"}, "noupdate": True}
        category = model._load_records([data])
        self.assertEqual(category, self.env.ref(xml_id, raise_if_not_found=False))
        self.assertEqual(category.name, "Foo")
        self.assertEqual(self.get_data(xml_id).noupdate, True)

        data = {"xml_id": xml_id, "values": {"name": "Bar"}, "noupdate": False}
        category1 = model._load_records([data], update=True)
        self.assertEqual(category, category1)
        self.assertEqual(category.name, "Foo")
        self.assertEqual(self.get_data(xml_id).noupdate, True)

        data = {"xml_id": xml_id, "values": {"name": "Baz"}, "noupdate": True}
        category2 = model._load_records([data], update=True)
        self.assertEqual(category, category2)
        self.assertEqual(category.name, "Foo")
        self.assertEqual(self.get_data(xml_id).noupdate, True)

    def test_create_noupdate_multi(self):
        model = self.env["res.partner.category"]
        data_list = [
            {
                "xml_id": "test_convert.category_foo",
                "values": {"name": "Foo"},
                "noupdate": True,
            },
            {
                "xml_id": "test_convert.category_bar",
                "values": {"name": "Bar"},
                "noupdate": True,
            },
        ]

        categories = model._load_records(data_list)
        foo = self.env.ref("test_convert.category_foo")
        bar = self.env.ref("test_convert.category_bar")
        self.assertEqual(categories, foo + bar)
        self.assertEqual(foo.name, "Foo")
        self.assertEqual(bar.name, "Bar")

        self.assertEqual(self.get_data("test_convert.category_foo").noupdate, True)
        self.assertEqual(self.get_data("test_convert.category_bar").noupdate, True)

    def test_create_order(self):
        model = self.env["res.partner.category"]
        data_list = [
            {"xml_id": "test_convert.category_foo", "values": {"name": "Foo"}},
            {
                "xml_id": "test_convert.category_bar",
                "values": {"name": "Bar"},
                "noupdate": True,
            },
            {"xml_id": "test_convert.category_baz", "values": {"name": "Baz"}},
        ]

        foo = model._load_records([data_list[0]])
        bar = model._load_records([data_list[1]])
        baz = model._load_records([data_list[2]])
        self.assertEqual(foo.name, "Foo")
        self.assertEqual(bar.name, "Bar")
        self.assertEqual(baz.name, "Baz")

        for data in data_list:
            data["values"]["name"] += "X"
        cats = model._load_records(data_list, update=True)
        self.assertEqual(list(cats), [foo, bar, baz])
        self.assertEqual(foo.name, "FooX")
        self.assertEqual(bar.name, "Bar")
        self.assertEqual(baz.name, "BazX")

    def test_create_inherits(self):
        model = self.env["res.users"]
        xml_id = "test_convert.user_foo"
        par_xml_id = xml_id + "_res_partner"

        user = model._load_records(
            [{"xml_id": xml_id, "values": {"name": "Foo", "login": "foo"}}]
        )
        self.assertEqual(user, self.env.ref(xml_id, raise_if_not_found=False))
        self.assertEqual(
            user.partner_id, self.env.ref(par_xml_id, raise_if_not_found=False)
        )
        self.assertEqual(user.name, "Foo")
        self.assertEqual(user.login, "foo")

    def test_recreate(self):
        model = self.env["res.partner.category"]
        xml_id = "test_convert.category_foo"
        data = {"xml_id": xml_id, "values": {"name": "Foo"}}

        category = model._load_records([data])
        self.assertEqual(category, self.env.ref(xml_id, raise_if_not_found=False))
        self.assertEqual(category.name, "Foo")

        category.unlink()
        self.assertFalse(self.env.ref(xml_id, raise_if_not_found=False))

        category = model._load_records([data], update=True)
        self.assertEqual(category, self.env.ref(xml_id, raise_if_not_found=False))
        self.assertEqual(category.name, "Foo")

    def test_create_xmlids(self):
        foo, bar = self.env["res.users"]._load_records(
            [
                {
                    "xml_id": "test_convert.foo",
                    "values": {"name": "Foo", "login": "foo"},
                    "noupdate": True,
                },
                {
                    "xml_id": "test_convert.bar",
                    "values": {"name": "Bar", "login": "bar"},
                    "noupdate": True,
                },
            ]
        )

        self.assertEqual(
            foo, self.env.ref("test_convert.foo", raise_if_not_found=False)
        )
        self.assertEqual(
            bar, self.env.ref("test_convert.bar", raise_if_not_found=False)
        )

        self.assertEqual(
            foo.partner_id,
            self.env.ref("test_convert.foo_res_partner", raise_if_not_found=False),
        )
        self.assertEqual(
            bar.partner_id,
            self.env.ref("test_convert.bar_res_partner", raise_if_not_found=False),
        )

        self.assertEqual(self.get_data("test_convert.foo").noupdate, True)
        self.assertEqual(self.get_data("test_convert.bar").noupdate, True)

    @mute_logger(
        "odoo.db",
        "odoo.addons.base.models.ir_model",
        "odoo.addons.base.models.ir_model_data",
    )
    def test_create_external_id_with_space(self):
        model = self.env["res.partner.category"]
        data_list = [
            {
                "xml_id": "test_convert.category_with space",
                "values": {"name": "Bar"},
            }
        ]
        with self.assertRaisesRegex(IntegrityError, "ir_model_data_name_nospaces"):
            model._load_records(data_list)

    def test_update_xmlid(self):
        def assert_xmlid(xmlid, value, message):
            expected_values = (value._name, value.id)
            with self.assertQueryCount(0):
                self.assertEqual(
                    self.env["ir.model.data"]._xmlid_lookup(xmlid),
                    expected_values,
                    message,
                )
            module, name = xmlid.split(".")
            self.env.cr.execute(
                "SELECT model, res_id FROM ir_model_data where module=%s and name=%s",
                [module, name],
            )
            self.assertEqual((value._name, value.id), self.env.cr.fetchone(), message)

        xmlid = "base.test_xmlid"
        records = self.env["ir.model.data"].search([], limit=6)
        with self.assertQueryCount(1):
            self.env["ir.model.data"]._update_xmlids(
                [
                    {"xml_id": xmlid, "record": records[0]},
                ]
            )
        assert_xmlid(
            xmlid,
            records[0],
            f"The xmlid {xmlid} should have been created with record {records[0]}",
        )

        with self.assertQueryCount(1):
            self.env["ir.model.data"]._update_xmlids(
                [
                    {"xml_id": xmlid, "record": records[1]},
                ],
                update=True,
            )
        assert_xmlid(
            xmlid,
            records[1],
            f"The xmlid {xmlid} should have been updated with record {records[1]}",
        )

        with self.assertQueryCount(1):
            self.env["ir.model.data"]._update_xmlids(
                [
                    {"xml_id": xmlid, "record": records[2]},
                ]
            )
        assert_xmlid(
            xmlid,
            records[2],
            f"The xmlid {xmlid} should have been updated with record {records[1]}",
        )

        xmlid = "base.test_xmlid_noupdates"
        with self.assertQueryCount(1):
            self.env["ir.model.data"]._update_xmlids(
                [
                    {
                        "xml_id": xmlid,
                        "record": records[3],
                        "noupdate": True,
                    },
                ]
            )

        assert_xmlid(
            xmlid,
            records[3],
            f"The xmlid {xmlid} should have been created for record {records[2]}",
        )

        with self.assertQueryCount(1):
            self.env["ir.model.data"]._update_xmlids(
                [
                    {"xml_id": xmlid, "record": records[4]},
                ],
                update=True,
            )
        assert_xmlid(
            xmlid,
            records[3],
            f"The xmlid {xmlid} should not have been updated (update mode)",
        )

        with self.assertQueryCount(1):
            self.env["ir.model.data"]._update_xmlids(
                [
                    {"xml_id": xmlid, "record": records[5]},
                ]
            )
        assert_xmlid(
            xmlid,
            records[5],
            f"The xmlid {xmlid} should have been updated with record (not an update) {records[1]}",
        )


@tagged("-at_install", "post_install")
class TestIrModelEdition(TransactionCase):
    def test_new_ir_model_fields_related(self):
        model = self.env["ir.model"].create({"name": "Bananas", "model": "x_bananas"})
        with self.debug_mode():
            form = Form(
                self.env["ir.model.fields"].with_context(default_model_id=model.id)
            )
            form.related = "id"
            self.assertEqual(form.ttype, "integer")

    def test_delete_manual_models_with_base_fields(self):
        model = self.env["ir.model"].create(
            {
                "model": "x_test_base_delete",
                "name": "test base delete",
                "field_id": [
                    Command.create(
                        {
                            "name": "x_my_field",
                            "ttype": "char",
                        }
                    ),
                    Command.create(
                        {
                            "name": "active",
                            "ttype": "boolean",
                            "state": "base",
                        }
                    ),
                ],
            }
        )
        model2 = self.env["ir.model"].create(
            {
                "model": "x_test_base_delete2",
                "name": "test base delete2",
                "field_id": [
                    Command.create(
                        {
                            "name": "x_my_field2",
                            "ttype": "char",
                        }
                    ),
                    Command.create(
                        {
                            "name": "active",
                            "ttype": "boolean",
                            "state": "base",
                        }
                    ),
                ],
            }
        )
        self.assertTrue(model.exists())
        self.assertTrue(model2.exists())

        self.env["ir.model"].browse(model.ids + model2.ids).unlink()
        self.assertFalse(model.exists())
        self.assertFalse(model2.exists())

    @mute_logger("odoo.db")
    def test_ir_model_fields_name_create(self):
        model = self.env["ir.model"].create({"name": "Bananas", "model": "x_bananas"})
        with self.assertRaises(NotNullViolation):
            self.env["ir.model.fields"].name_create("field_name")

        self.env["ir.model.fields"].with_context(
            default_model_id=model.id,
            default_model=model.name,
            default_ttype="char",
        ).name_create("field_name")

    def test_reflect_models_empty_no_raise(self):
        self.assertIsNone(self.env["ir.model"]._reflect_models([]))

    def test_reflect_models_prewarms_get_id_cache(self):
        IrModel = self.env["ir.model"]
        model = IrModel.create({"model": "x_prewarm", "name": "Prewarm test"})
        self.env.registry.clear_cache("stable")
        IrModel._reflect_models(["x_prewarm"])
        with self.assertQueryCount(0):
            self.assertEqual(IrModel._get_id("x_prewarm"), model.id)

    def test_name_create_slugifies_name(self):
        IrModel = self.env["ir.model"]
        cases = [
            ("Coûts 2024!", "x_couts_2024"),
            ("My-Model", "x_my_model"),
            ("My New Model", "x_my_new_model"),
        ]
        for label, expected in cases:
            record_id, _display = IrModel.name_create(label)
            self.assertEqual(IrModel.browse(record_id).model, expected)

    def test_upsert_en_rejects_translated_conflict_column(self):
        from odoo.addons.base.models.ir_model_common import upsert_en

        IrModel = self.env["ir.model"]
        self.assertTrue(IrModel._fields["name"].translate)
        with self.assertRaises(ValueError):
            upsert_en(IrModel, ["name", "model"], [("X", "x_up")], conflict=["name"])

    def test_upsert_en_rejects_duplicate_conflict_keys(self):
        from odoo.addons.base.models.ir_model_common import upsert_en

        IrModel = self.env["ir.model"]
        with self.assertRaises(ValueError):
            upsert_en(
                IrModel,
                ["model", "name"],
                [("dup.model", "A"), ("dup.model", "B")],
                conflict=["model"],
            )

    def test_upsert_en_rejects_empty_fnames(self):
        from odoo.addons.base.models.ir_model_common import upsert_en

        IrModel = self.env["ir.model"]
        with self.assertRaises(ValueError):
            upsert_en(IrModel, [], [("x",)], conflict=["model"])

    def test_upsert_en_empty_rows_returns_empty(self):
        from odoo.addons.base.models.ir_model_common import upsert_en

        IrModel = self.env["ir.model"]
        self.assertEqual(
            upsert_en(IrModel, ["model", "name"], [], conflict=["model"]), []
        )

    def test_make_compute_filters_blank_dependencies(self):
        from odoo.addons.base.models.ir_model_common import make_compute

        compute = make_compute("pass", "field_a, , field_b,")
        self.assertEqual(compute._depends, ("field_a", "field_b"))
        self.assertEqual(compute.__name__, "compute")

    def test_manual_compute_failure_names_the_field(self):
        model = self.env["ir.model"].create({"model": "x_imc_boom", "name": "IMC boom"})
        self.env["ir.model.fields"].create(
            {
                "name": "x_src",
                "field_description": "Src",
                "model_id": model.id,
                "ttype": "char",
            }
        )
        self.env.flush_all()
        self.env["ir.model.fields"].create(
            {
                "name": "x_calc",
                "field_description": "Calc",
                "model_id": model.id,
                "ttype": "integer",
                "store": False,
                "readonly": True,
                "depends": "x_src",
                "compute": "for record in self:\n    record['x_calc'] = 1 / 0\n",
            }
        )
        self.env.flush_all()
        self.env.registry._setup_models__(self.env.cr, [model.model])
        record = self.env[model.model].create({"x_src": "a"})

        try:
            record.read(["x_calc"])
        except ZeroDivisionError:
            frames = traceback.format_exc()
        else:
            self.fail("the compute code was expected to raise")
        self.assertIn("<compute x_imc_boom.x_calc>", frames)

    def test_manual_compute_syntax_error_names_the_field(self):
        from odoo.addons.base.models.ir_model_common import make_compute

        compute = make_compute("for record in self\n    pass\n", None, "x_m.x_f")
        with self.assertRaises(SyntaxError) as cm:
            compute(self.env["ir.model"])
        self.assertIn("<compute x_m.x_f>", str(cm.exception))

    def test_inherit_xmlid_format(self):
        from odoo.addons.base.models.ir_model_common import inherit_xmlid

        self.assertEqual(
            inherit_xmlid("base", "a.b", "c.d"), "base.model_inherit__a_b__c_d"
        )

    def test_compute_count_matches_table_rowcount(self):
        IrModel = self.env["ir.model"]
        concrete = IrModel._get("res.country")
        abstract = IrModel._get("base")
        expected = (
            self.env["res.country"].with_context(active_test=False).search_count([])
        )
        batch = concrete + abstract
        batch.invalidate_recordset(["count"])
        self.assertEqual(concrete.count, expected)
        self.assertEqual(abstract.count, 0)

    def test_model_deletion_drops_its_custom_m2m_tables(self):
        model = self.env["ir.model"].create({"model": "x_imod_m2m", "name": "IMOD m2m"})
        field = self.env["ir.model.fields"].create(
            {
                "name": "x_partners",
                "field_description": "Partners",
                "model_id": model.id,
                "ttype": "many2many",
                "relation": "res.partner",
            }
        )
        self.env.flush_all()
        table = field.relation_table
        self.env.cr.execute("SELECT to_regclass(%s)", (table,))
        self.assertIsNotNone(self.env.cr.fetchone()[0], "precondition: table exists")

        model.unlink()
        self.env.flush_all()

        self.env.cr.execute("SELECT to_regclass(%s)", (table,))
        self.assertIsNone(self.env.cr.fetchone()[0], "m2m table must not leak")

    def test_m2m_table_kept_while_another_field_uses_it(self):
        model = self.env["ir.model"].create(
            {"model": "x_imod_share", "name": "IMOD share"}
        )
        first = self.env["ir.model.fields"].create(
            {
                "name": "x_partners",
                "field_description": "Partners",
                "model_id": model.id,
                "ttype": "many2many",
                "relation": "res.partner",
            }
        )
        self.env.flush_all()
        table = first.relation_table
        self.env["ir.model.fields"].create(
            {
                "name": "x_partners_too",
                "field_description": "Partners again",
                "model_id": model.id,
                "ttype": "many2many",
                "relation": "res.partner",
                "relation_table": table,
                "column1": first.column1,
                "column2": first.column2,
            }
        )
        self.env.flush_all()

        first.unlink()
        self.env.flush_all()

        self.env.cr.execute("SELECT to_regclass(%s)", (table,))
        self.assertIsNotNone(
            self.env.cr.fetchone()[0], "another field still uses the table"
        )

    def test_compute_count_survives_a_missing_table(self):
        IrModel = self.env["ir.model"]
        orphan = IrModel.create({"model": "x_imod_notable", "name": "No table"})
        self.env.cr.execute("DROP TABLE IF EXISTS x_imod_notable CASCADE")
        self.env.invalidate_all()

        batch = IrModel._get("res.country") + orphan
        batch.invalidate_recordset(["count"])
        counts = {record.model: record.count for record in batch}

        self.assertEqual(counts["x_imod_notable"], 0)
        self.assertEqual(
            counts["res.country"],
            self.env["res.country"].with_context(active_test=False).search_count([]),
        )
        self.env.cr.execute("SELECT 1")
        self.assertEqual(self.env.cr.fetchone(), (1,), "transaction still usable")


@tagged("test_eval_context")
class TestEvalContext(TransactionCase):
    def test_module_usage(self):
        self.env["ir.model.fields"].create(
            {
                "name": "x_foo_bar_baz",
                "model_id": self.env["ir.model"]
                .search([("model", "=", "res.partner")])
                .id,
                "field_description": "foo",
                "ttype": "integer",
                "store": False,
                "depends": "name",
                "compute": (
                    "time.time()\ndatetime.datetime.now()\ndateutil.relativedelta.relativedelta(hours=1)"
                ),
            }
        )
        _ = self.env["res.partner"].create({"name": "foo"}).x_foo_bar_baz


@tagged("-at_install", "post_install")
class TestIrModelFieldsTranslation(HttpCase):
    def test_ir_model_fields_translation(self):
        group_order_template = self.env.ref(
            "sale_management.group_sale_order_template",
            raise_if_not_found=False,
        )
        if group_order_template:
            self.env.ref("base.group_user").write(
                {"implied_ids": [(4, group_order_template.id)]}
            )

        field = self.env["ir.model.fields"].search(
            [("model_id.model", "=", "res.users"), ("name", "=", "login")]
        )
        self.assertEqual(field.with_context(lang="en_US").field_description, "Login")
        self.start_tour("/odoo", "ir_model_fields_translation_en_tour", login="admin")
        field.update_field_translations("field_description", {"en_US": "Login2"})
        self.start_tour("/odoo", "ir_model_fields_translation_en_tour2", login="admin")

        self.env["res.lang"]._activate_lang("fr_FR")
        field = self.env["ir.model.fields"].search(
            [("model_id.model", "=", "res.users"), ("name", "=", "login")]
        )
        field.update_field_translations("field_description", {"fr_FR": "Identifiant"})
        self.assertEqual(
            field.with_context(lang="fr_FR").field_description, "Identifiant"
        )
        admin = self.env["res.users"].search([("login", "=", "admin")], limit=1)
        admin.lang = "fr_FR"
        self.start_tour("/odoo", "ir_model_fields_translation_fr_tour", login="admin")
        field.update_field_translations("field_description", {"fr_FR": "Identifiant2"})
        self.start_tour("/odoo", "ir_model_fields_translation_fr_tour2", login="admin")


@tagged("-at_install", "post_install")
class TestIrModelFields(TransactionCase):
    def _make_manual_field(self, stem, **vals):
        model = self.env["ir.model"].create(
            {"model": f"x_imf_{stem}", "name": f"IMF test {stem}"}
        )
        field = self.env["ir.model.fields"].create(
            {
                "name": f"x_{stem}",
                "field_description": f"Field {stem}",
                "model_id": model.id,
                "ttype": "char",
                **vals,
            }
        )
        return self.env[model.model], field

    def test_empty_write_skips_registry_setup(self):
        _model, field = self._make_manual_field("empty")
        with patch.object(self.env.registry, "_setup_models__") as mock_setup:
            self.assertTrue(field.write({}))
        mock_setup.assert_not_called()

    def test_label_translate_write_skips_registry_setup(self):
        Model, field = self._make_manual_field("label")
        with patch.object(self.env.registry, "_setup_models__") as mock_setup:
            field.write({"field_description": "Renamed Label"})
        mock_setup.assert_not_called()
        self.assertEqual(
            self.env["ir.model.fields"].get_field_string(Model._name)[field.name],
            "Renamed Label",
        )

    def test_field_rename_preserves_column_index_and_data(self):
        Model, field = self._make_manual_field("rename", index=True)
        table = Model._table
        record = Model.create({"x_rename": "kept"})
        record.flush_recordset()

        field.write({"name": "x_renamed"})

        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = %s AND column_name IN ('x_rename', 'x_renamed')",
            (table,),
        )
        self.assertEqual(
            [row[0] for row in self.env.cr.fetchall()],
            ["x_renamed"],
            "only the renamed column must remain",
        )
        self.env.cr.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = %s", (table,)
        )
        indexes = {row[0] for row in self.env.cr.fetchall()}
        self.assertIn(f"{table}__x_renamed_index", indexes)
        self.assertNotIn(f"{table}__x_rename_index", indexes)
        record = self.env[Model._name].browse(record.id)
        self.assertEqual(record.x_renamed, "kept")

    def test_field_rename_single_prepare_update_pass(self):
        _Model, field = self._make_manual_field("renonce")
        cls = type(self.env["ir.model.fields"])
        original = cls._prepare_update
        calls = []

        def counting(records):
            calls.append(records)
            return original(records)

        with patch.object(cls, "_prepare_update", counting):
            field.write({"name": "x_renonce2"})
        self.assertEqual(len(calls), 1)

    def test_boolean_translate_rejected(self):
        model = self.env["ir.model"].create(
            {"model": "x_imf_transl", "name": "IMF translate test"}
        )
        with self.assertRaises(ValueError):
            self.env["ir.model.fields"].create(
                {
                    "name": "x_transl",
                    "field_description": "Translated",
                    "model_id": model.id,
                    "ttype": "char",
                    "translate": True,
                }
            )
        _Model, field = self._make_manual_field("translw")
        with self.assertRaises(ValueError):
            field.write({"translate": True})

    def test_check_depends_raises_validation_error(self):
        model = self.env["ir.model"].create(
            {"model": "x_imf_deps", "name": "IMF depends test"}
        )
        with self.assertRaises(ValidationError):
            self.env["ir.model.fields"].create(
                {
                    "name": "x_dep",
                    "field_description": "Dep",
                    "model_id": model.id,
                    "ttype": "char",
                    "store": False,
                    "compute": "pass",
                    "depends": "no_such_field",
                }
            )

    def test_check_related_raises_validation_error(self):
        model = self.env["ir.model"].create(
            {"model": "x_imf_rel", "name": "IMF related test"}
        )
        with self.assertRaises(ValidationError):
            self.env["ir.model.fields"].create(
                {
                    "name": "x_rel",
                    "field_description": "Rel",
                    "model_id": model.id,
                    "ttype": "char",
                    "related": "no_such_field",
                }
            )

    def test_all_manual_field_data_immutable(self):
        self._make_manual_field("frozen")
        data = self.env["ir.model.fields"]._all_manual_field_data()
        self.assertIn("x_imf_frozen", data)
        with self.assertRaises((TypeError, NotImplementedError)):
            data["x_bogus"] = {}

    def test_compute_modules_shared_helper(self):
        model = self.env["ir.model"]._get("res.partner")
        self.assertIn("base", model.modules.split(", "))
        field = self.env["ir.model.fields"]._get("res.partner", "name")
        self.assertIn("base", field.modules.split(", "))

    def test_display_name_batch_fetches_model_names(self):
        fields_ = self.env["ir.model.fields"].search(
            [("model", "=", "res.partner"), ("name", "in", ["name", "email"])]
        )
        self.env.invalidate_all()
        names = fields_.mapped("display_name")
        model_name = self.env["ir.model"]._get("res.partner").name
        for field, display_name in zip(fields_, names, strict=True):
            self.assertEqual(display_name, f"{field.field_description} ({model_name})")
        self.env.invalidate_all()
        fields_.mapped("display_name")
        with self.assertQueryCount(0):
            self.env["ir.model"]._get("res.partner").name

    def test_check_relation_table_invalid_name(self):
        model = self.env["ir.model"].create(
            {"model": "x_imf_m2m", "name": "IMF m2m test"}
        )
        comodel = self.env["ir.model"].search([("model", "=", "res.partner")])
        with self.assertRaises(ValidationError) as cm:
            self.env["ir.model.fields"].create(
                {
                    "name": "x_partner_ids",
                    "field_description": "Partners",
                    "model_id": model.id,
                    "ttype": "many2many",
                    "relation": comodel.model,
                    "relation_table": "bad-name!",
                }
            )
        self.assertIn("Relation table names", str(cm.exception))

    def test_help_added_by_translate_only_write_is_visible(self):
        Model, field = self._make_manual_field("addhelp")
        model_name = Model._name
        self.assertIsNone(Model._fields[field.name].help)

        field.write({"help": "Tooltip"})

        self.assertEqual(
            self.env[model_name].fields_get([field.name])[field.name]["help"],
            "Tooltip",
        )
        self.assertEqual(
            self.env.registry[model_name]._fields[field.name].help, "Tooltip"
        )

    def test_presence_preserving_label_write_still_skips_setup(self):
        Model, field = self._make_manual_field("keepfast", help="Tip")
        with patch.object(self.env.registry, "_setup_models__") as mock_setup:
            field.write({"field_description": "Renamed", "help": "Tip 2"})
        mock_setup.assert_not_called()
        self.assertEqual(
            self.env["ir.model.fields"].get_field_help(Model._name)[field.name],
            "Tip 2",
        )

    def test_field_groups_without_xmlid_are_enforceable(self):
        model = self.env["ir.model"].create(
            {"model": "x_imf_sec", "name": "IMF security test"}
        )
        group = self.env["res.groups"].create({"name": "IMF ad-hoc group"})
        self.assertFalse(group.get_external_id()[group.id])

        field = self.env["ir.model.fields"].create(
            {
                "name": "x_secret",
                "field_description": "Secret",
                "model_id": model.id,
                "ttype": "char",
                "groups": [Command.set([group.id])],
            }
        )
        self.env["ir.model.access"].create(
            {
                "name": "imf sec acl",
                "model_id": model.id,
                "group_id": self.env.ref("base.group_user").id,
                "perm_read": True,
                "perm_write": True,
                "perm_create": True,
                "perm_unlink": True,
            }
        )
        self.env.flush_all()
        self.env.registry._setup_models__(self.env.cr, [model.model])

        self.assertTrue(group.get_external_id()[group.id])
        self.assertEqual(
            self.env.registry[model.model]._fields[field.name].groups,
            group.get_external_id()[group.id],
        )

        record = self.env[model.model].create({"x_secret": "classified"})
        self.env.flush_all()
        outsider = new_test_user(self.env, login="imf_outsider")
        with self.assertRaises(AccessError):
            self.env[model.model].with_user(outsider).browse(record.id).read(
                ["x_secret"]
            )
        outsider.write({"group_ids": [Command.link(group.id)]})
        self.assertEqual(
            self.env[model.model].with_user(outsider).browse(record.id).x_secret,
            "classified",
        )

    @mute_logger("odoo.addons.base.models.ir_model_fields")
    def test_field_groups_missing_xmlid_fails_closed(self):
        model = self.env["ir.model"].create(
            {"model": "x_imf_sec2", "name": "IMF security test 2"}
        )
        group = self.env["res.groups"].create({"name": "IMF legacy group"})
        field = self.env["ir.model.fields"].create(
            {
                "name": "x_secret",
                "field_description": "Secret",
                "model_id": model.id,
                "ttype": "char",
                "groups": [Command.set([group.id])],
            }
        )
        self.env.flush_all()
        self.env["ir.model.data"].search(
            [("model", "=", "res.groups"), ("res_id", "=", group.id)]
        ).unlink()
        self.env.registry.clear_cache("stable")
        self.env.registry._setup_models__(self.env.cr, [model.model])

        self.assertEqual(
            self.env.registry[model.model]._fields[field.name].groups,
            NO_ACCESS,
            "an unreflectable restriction must fail closed",
        )

    def test_write_does_not_mutate_caller_vals(self):
        model = self.env["ir.model"].create(
            {"model": "x_imf_vals", "name": "IMF vals test"}
        )
        field = self.env["ir.model.fields"].create(
            {
                "name": "x_v",
                "field_description": "V",
                "model_id": model.id,
                "ttype": "char",
            }
        )
        vals = {"field_description": "V2", "model_id": model.id, "state": "manual"}
        expected = dict(vals)
        field.write(vals)
        self.assertEqual(vals, expected)

        model_vals = {"name": "IMF vals test 2", "field_id": [(4, field.id, False)]}
        expected_model_vals = dict(model_vals)
        model.write(model_vals)
        self.assertEqual(model_vals, expected_model_vals)

    def test_unrelated_broken_view_does_not_block_field_deletion(self):
        _Model, field = self._make_manual_field("ab_cd")
        bait = self.env["ir.ui.view"].create(
            {
                "name": "IMF wildcard bait",
                "model": "res.partner",
                "type": "form",
                "arch": '<form><field name="name"/></form>',
            }
        )
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ir_ui_view SET arch_db = %s WHERE id = %s",
            (Json({"en_US": '<form><field name="xZabZcd_nope"/></form>'}), bait.id),
        )
        self.env.invalidate_all()

        self.assertTrue(
            self.env["ir.ui.view"].search_count(
                [("id", "=", bait.id), ("arch_db", "like", field.name)]
            ),
            "precondition: the raw pattern matches the bait",
        )
        self.assertFalse(
            self.env["ir.ui.view"].search_count(
                [("id", "=", bait.id), ("arch_db", "like", escape_psql(field.name))]
            ),
            "precondition: the escaped pattern does not",
        )
        with self.assertRaises(ValidationError):
            bait._check_xml()

        field.unlink()

    def test_related_view_still_blocks_field_deletion(self):
        Model, field = self._make_manual_field("guard")
        self.env["ir.ui.view"].create(
            {
                "name": "IMF real reference",
                "model": Model._name,
                "type": "form",
                "arch": f'<form><field name="{field.name}"/></form>',
            }
        )
        self.env.flush_all()
        with self.assertRaises(UserError):
            field.unlink()

    def test_view_scan_ignores_substring_and_wildcard_matches(self):
        model = self.env["ir.model"].create({"model": "x_imf_scan", "name": "IMF scan"})
        for name in ("x_ab", "x_ab_long", "x_ab_cd"):
            self.env["ir.model.fields"].create(
                {
                    "name": name,
                    "field_description": name,
                    "model_id": model.id,
                    "ttype": "char",
                }
            )
        self.env.flush_all()
        self.env.registry._setup_models__(self.env.cr, [model.model])
        long_view = self.env["ir.ui.view"].create(
            {
                "name": "IMF scan long",
                "model": model.model,
                "type": "form",
                "arch": '<form><field name="x_ab_long"/></form>',
            }
        )
        wildcard_bait = self.env["ir.ui.view"].create(
            {
                "name": "IMF scan bait",
                "model": "res.partner",
                "type": "form",
                "arch": '<form><field name="name" string="xZabZcd"/></form>',
            }
        )
        self.env.flush_all()

        IrModelFields = self.env["ir.model.fields"]
        self.assertNotIn(long_view.id, IrModelFields._views_mentioning(["x_ab"]).ids)
        self.assertIn(long_view.id, IrModelFields._views_mentioning(["x_ab_long"]).ids)
        self.assertNotIn(
            wildcard_bait.id, IrModelFields._views_mentioning(["x_ab_cd"]).ids
        )

    def test_view_scan_finds_translation_only_occurrences(self):
        model = self.env["ir.model"].create(
            {"model": "x_imf_scanfr", "name": "IMF scan fr"}
        )
        self.env["ir.model.fields"].create(
            {
                "name": "x_only_fr",
                "field_description": "Fr",
                "model_id": model.id,
                "ttype": "char",
            }
        )
        view = self.env["ir.ui.view"].create(
            {
                "name": "IMF scan fr view",
                "model": "res.partner",
                "type": "form",
                "arch": '<form><field name="name"/></form>',
            }
        )
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ir_ui_view SET arch_db = %s WHERE id = %s",
            (
                Json(
                    {
                        "en_US": '<form><field name="name"/></form>',
                        "fr_FR": '<form><field name="x_only_fr"/></form>',
                    }
                ),
                view.id,
            ),
        )
        self.env.invalidate_all()

        self.assertIn(
            view.id,
            self.env["ir.model.fields"]._views_mentioning(["x_only_fr"]).ids,
        )

    def test_drop_column_recovers_m2m_table_name(self):
        model = self.env["ir.model"].create(
            {"model": "x_imf_m2mdrop", "name": "IMF m2m drop"}
        )
        field = self.env["ir.model.fields"].create(
            {
                "name": "x_rel",
                "field_description": "Rel",
                "model_id": model.id,
                "ttype": "many2many",
                "relation": "res.partner",
            }
        )
        self.env.flush_all()
        table = field.relation_table
        self.assertTrue(table)
        self.env.cr.execute(
            "UPDATE ir_model_fields SET relation_table = NULL WHERE id = %s",
            (field.id,),
        )
        self.env.invalidate_all()
        pop_field(self.env.registry["x_imf_m2mdrop"], "x_rel")

        field._drop_column()

        self.env.cr.execute("SELECT to_regclass(%s)", (table,))
        self.assertIsNone(self.env.cr.fetchone()[0], "m2m table must not leak")

    def test_rename_without_registry_model_raises_user_error(self):
        _Model, field = self._make_manual_field("noreg")
        model_cls = self.env.registry.models.pop("x_imf_noreg")
        try:
            with self.assertRaises(UserError):
                field.write({"name": "x_noreg2"})
        finally:
            self.env.registry.models["x_imf_noreg"] = model_cls


class TestIrModelInherit(TransactionCase):
    def test_inherit(self):
        imi = self.env["ir.model.inherit"].search(
            [
                ("model_id.model", "=", "ir.actions.server"),
                ("parent_id.model", "=", "ir.actions.actions"),
            ]
        )
        self.assertEqual(len(imi), 1)
        self.assertEqual(imi.parent_id.model, "ir.actions.actions")
        self.assertFalse(imi.parent_field_id)

    def test_inherits(self):
        imi = self.env["ir.model.inherit"].search(
            [
                ("model_id.model", "=", "res.users"),
                ("parent_field_id", "!=", False),
            ]
        )
        self.assertEqual(len(imi), 1)
        self.assertEqual(imi.parent_id.model, "res.partner")
        self.assertEqual(imi.parent_field_id.name, "partner_id")

    def test_inherit_and_inherits_same_parent_is_rejected_clearly(self):
        IrModelInherit = self.env["ir.model.inherit"]
        definition = next(
            cls
            for cls in type(self.env["res.users"]).mro()
            if is_model_definition(cls) and "res.partner" in cls._inherits
        )

        with (
            patch.object(definition, "_inherit", ["res.partner"]),
            self.assertRaises(ValueError) as cm,
        ):
            IrModelInherit._reflect_inherits(["res.users"])
        self.assertIn("res.users", str(cm.exception))
        self.assertIn("res.partner", str(cm.exception))


class TestIrModelRelationReflection(TransactionCase):
    def test_reflect_relations_is_idempotent_and_batched(self):
        IrModelRelation = self.env["ir.model.relation"]
        model_name = "res.partner"
        table = "x_imr_probe_rel"
        self.env.cr.execute("DELETE FROM ir_model_relation WHERE name = %s", (table,))

        IrModelRelation._reflect_relations(
            [(model_name, table, "base"), (model_name, table, "base")]
        )
        self.env.cr.execute(
            "SELECT im.model, m.name FROM ir_model_relation r"
            " JOIN ir_model im ON r.model = im.id"
            " JOIN ir_module_module m ON r.module = m.id"
            " WHERE r.name = %s",
            (table,),
        )
        self.assertEqual(self.env.cr.fetchall(), [(model_name, "base")])

        IrModelRelation._reflect_relations([(model_name, table, "base")])
        self.env.cr.execute(
            "SELECT count(*) FROM ir_model_relation WHERE name = %s", (table,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], 1, "no duplicate row")

    def test_reflect_relations_skips_unknown_module(self):
        with mute_logger("odoo.addons.base.models.ir_model_reflection"):
            self.env["ir.model.relation"]._reflect_relations(
                [("res.partner", "x_imr_nomodule_rel", "no_such_module_xyz")]
            )
        self.env.cr.execute(
            "SELECT count(*) FROM ir_model_relation WHERE name = %s",
            ("x_imr_nomodule_rel",),
        )
        self.assertEqual(self.env.cr.fetchone()[0], 0)


@tagged("-at_install", "post_install")
class TestIrModelFieldsSelection(TransactionCase):
    @contextmanager
    def _write_raises(self, model_name, field_name, error):
        original_write = BaseModel.write

        def guarded_write(records, vals):
            if records._name == model_name and field_name in vals:
                raise error
            return original_write(records, vals)

        with patch.object(BaseModel, "write", guarded_write):
            yield

    def _make_selection_field(self, stem, *, company_dependent=False, values=None):
        values = values or [("draft", "Draft"), ("done", "Done")]
        model = self.env["ir.model"].create(
            {"model": f"x_sel_{stem}", "name": f"Selection test {stem}"}
        )
        field = self.env["ir.model.fields"].create(
            {
                "name": f"x_{stem}",
                "field_description": f"Sel {stem}",
                "model_id": model.id,
                "ttype": "selection",
                "company_dependent": company_dependent,
                "selection_ids": [
                    Command.create({"value": value, "name": label, "sequence": index})
                    for index, (value, label) in enumerate(values)
                ],
            }
        )
        return self.env[model.model], field

    def _set_jsonb(self, model, field, record, mapping):
        self.env.cr.execute(
            SQL(
                "UPDATE %s SET %s = %s WHERE id = %s",
                SQL.identifier(model._table),
                SQL.identifier(field.name),
                Json({str(cid): value for cid, value in mapping.items()}),
                record.id,
            )
        )
        record.invalidate_recordset([field.name])

    def _read_jsonb(self, model, field, record):
        self.env.cr.execute(
            SQL(
                "SELECT %s FROM %s WHERE id = %s",
                SQL.identifier(field.name),
                SQL.identifier(model._table),
                record.id,
            )
        )
        return self.env.cr.fetchone()[0]

    def test_selection_value_rename_normal(self):
        Model, field = self._make_selection_field("plain")
        record = Model.create({"x_plain": "draft"})
        record.flush_recordset()

        field.selection_ids.filtered(lambda s: s.value == "draft").write(
            {"value": "pending"}
        )

        record.invalidate_recordset(["x_plain"])
        self.assertEqual(record.x_plain, "pending")

    def test_selection_value_rename_company_dependent(self):
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "SEL Co B"})
        Model, field = self._make_selection_field("cdep", company_dependent=True)
        record = Model.create({})
        record.flush_recordset()
        self._set_jsonb(
            Model, field, record, {company_a.id: "draft", company_b.id: "draft"}
        )

        field.selection_ids.filtered(lambda s: s.value == "draft").write(
            {"value": "pending"}
        )

        self.assertEqual(
            self._read_jsonb(Model, field, record),
            {str(company_a.id): "pending", str(company_b.id): "pending"},
        )

    def test_selection_value_rename_company_dependent_other_value_untouched(self):
        company_a = self.env.company
        company_b = self.env["res.company"].create({"name": "SEL Co C"})
        Model, field = self._make_selection_field("keep", company_dependent=True)
        record = Model.create({})
        record.flush_recordset()
        self._set_jsonb(
            Model, field, record, {company_a.id: "draft", company_b.id: "done"}
        )

        field.selection_ids.filtered(lambda s: s.value == "draft").write(
            {"value": "pending"}
        )

        self.assertEqual(
            self._read_jsonb(Model, field, record),
            {str(company_a.id): "pending", str(company_b.id): "done"},
        )

    def test_selection_value_rename_same_value_batch_rejected(self):
        _model, field = self._make_selection_field("batch")
        self.assertEqual(len(field.selection_ids), 2)
        with self.assertRaises(UserError):
            field.selection_ids.write({"value": "merged"})

    def test_selection_label_rename_skips_registry_setup(self):
        Model, field = self._make_selection_field("label")
        draft = field.selection_ids.filtered(lambda s: s.value == "draft")
        with patch.object(self.env.registry, "_setup_models__") as mock_setup:
            draft.write({"name": "Brouillon"})
        mock_setup.assert_not_called()
        self.assertIn(
            ("draft", "Brouillon"),
            self.env["ir.model.fields"].get_field_selection(Model._name, field.name),
        )

    def test_selection_value_rename_triggers_registry_setup(self):
        _model, field = self._make_selection_field("setup")
        draft = field.selection_ids.filtered(lambda s: s.value == "draft")
        with patch.object(self.env.registry, "_setup_models__") as mock_setup:
            draft.write({"value": "pending"})
        mock_setup.assert_called()

    def test_selection_ondelete_bypass_on_recoverable_error(self):
        Model, field = self._make_selection_field("ondok")
        record = Model.create({"x_ondok": "draft"})
        record.flush_recordset()
        draft = field.selection_ids.filtered(lambda s: s.value == "draft")

        refusal = ValidationError("ondelete write refused by a constraint")
        with self._write_raises(Model._name, "x_ondok", refusal):
            draft.unlink()

        record.invalidate_recordset(["x_ondok"])
        self.assertFalse(record.x_ondok)

    def test_selection_ondelete_propagates_programming_error(self):
        Model, field = self._make_selection_field("ondbug")
        record = Model.create({"x_ondbug": "draft"})
        record.flush_recordset()
        draft = field.selection_ids.filtered(lambda s: s.value == "draft")

        bug = TypeError("programming error in an override")
        with self._write_raises(Model._name, "x_ondbug", bug):
            with self.assertRaises(TypeError):
                draft.unlink()

    def _field_obj(self, model, stem):
        return self.env[model._name]._fields[f"x_{stem}"]

    def test_ondelete_set_null(self):
        Model, field = self._make_selection_field("pnull")
        record = Model.create({"x_pnull": "draft"})
        record.flush_recordset()
        field.selection_ids.filtered(lambda s: s.value == "draft").unlink()
        record.invalidate_recordset(["x_pnull"])
        self.assertFalse(record.x_pnull)

    def test_ondelete_set_constant(self):
        Model, field = self._make_selection_field("pset")
        record = Model.create({"x_pset": "draft"})
        record.flush_recordset()
        with patch.object(
            self._field_obj(Model, "pset"), "ondelete", {"draft": "set done"}
        ):
            field.selection_ids.filtered(lambda s: s.value == "draft").unlink()
        record.invalidate_recordset(["x_pset"])
        self.assertEqual(record.x_pset, "done")

    def test_ondelete_set_default(self):
        Model, field = self._make_selection_field("pdef")
        record = Model.create({"x_pdef": "draft"})
        record.flush_recordset()
        field_obj = self._field_obj(Model, "pdef")
        with (
            patch.object(field_obj, "ondelete", {"draft": "set default"}),
            patch.object(field_obj, "default", lambda model: "done"),
        ):
            field.selection_ids.filtered(lambda s: s.value == "draft").unlink()
        record.invalidate_recordset(["x_pdef"])
        self.assertEqual(record.x_pdef, "done")

    def test_ondelete_cascade(self):
        Model, field = self._make_selection_field("pcasc")
        record = Model.create({"x_pcasc": "draft"})
        record.flush_recordset()
        with patch.object(
            self._field_obj(Model, "pcasc"), "ondelete", {"draft": "cascade"}
        ):
            field.selection_ids.filtered(lambda s: s.value == "draft").unlink()
        self.assertFalse(record.exists())

    def test_ondelete_callable(self):
        Model, field = self._make_selection_field("pcall")
        record = Model.create({"x_pcall": "draft"})
        record.flush_recordset()
        seen = []

        def policy(records):
            seen.extend(records.ids)
            records.write({"x_pcall": "done"})

        with patch.object(
            self._field_obj(Model, "pcall"), "ondelete", {"draft": policy}
        ):
            field.selection_ids.filtered(lambda s: s.value == "draft").unlink()
        record.invalidate_recordset(["x_pcall"])
        self.assertEqual(seen, record.ids)
        self.assertEqual(record.x_pcall, "done")

    def test_ondelete_resolves_values_in_one_batch(self):
        Model, field = self._make_selection_field(
            "pbatch", values=[("a", "A"), ("b", "B"), ("c", "C")]
        )
        records = Model.create([{"x_pbatch": v} for v in ("a", "b", "c")])
        records.flush_recordset()

        sel_cls = type(self.env["ir.model.fields.selection"])
        original = sel_cls._get_records_by_value
        calls = []

        def counting(self2, *args, **kwargs):
            calls.append(1)
            return original(self2, *args, **kwargs)

        with patch.object(sel_cls, "_get_records_by_value", counting):
            field.selection_ids.unlink()

        self.assertEqual(len(calls), 1)
        records.invalidate_recordset(["x_pbatch"])
        self.assertEqual(records.mapped("x_pbatch"), [False, False, False])

    def test_update_selection_returns_none(self):
        Model, field = self._make_selection_field("updret")
        result = self.env["ir.model.fields.selection"]._update_selection(
            Model._name,
            field.name,
            [("draft", "Brouillon"), ("new", "New")],
        )
        self.assertIsNone(result)
        self.assertEqual(
            self.env["ir.model.fields.selection"]._get_selection_data(field.id),
            [("draft", "Brouillon"), ("new", "New")],
        )

    def test_ondelete_set_null_company_dependent(self):
        company = self.env.company
        Model, field = self._make_selection_field("pcd", company_dependent=True)
        record = Model.create({})
        record.flush_recordset()
        self._set_jsonb(Model, field, record, {company.id: "draft"})

        field.selection_ids.filtered(lambda s: s.value == "draft").unlink()

        record.invalidate_recordset(["x_pcd"])
        self.assertFalse(record.with_company(company).x_pcd)

    def test_ondelete_company_dependent_outside_env_companies(self):
        other = self.env["res.company"].create({"name": "SEL-P4 other"})
        Model, field = self._make_selection_field("outscope", company_dependent=True)
        record = Model.create({})
        record.flush_recordset()
        self._set_jsonb(Model, field, record, {other.id: "draft"})

        scoped = self.env(
            context=dict(self.env.context, allowed_company_ids=[self.env.company.id])
        )
        self.assertNotIn(other.id, scoped.companies.ids)

        field.with_env(scoped).selection_ids.filtered(
            lambda s: s.value == "draft"
        ).unlink()

        self.assertFalse(self._read_jsonb(Model, field, record))

    @mute_logger("odoo.addons.base.models.ir_model_fields_selection")
    def test_ondelete_orm_bypass_preserves_other_companies(self):
        other = self.env["res.company"].create({"name": "SEL-C3 other"})
        Model, field = self._make_selection_field("bypass", company_dependent=True)
        record = Model.create({})
        record.flush_recordset()
        self._set_jsonb(
            Model, field, record, {self.env.company.id: "draft", other.id: "done"}
        )

        failure = UserError("forced ORM failure")
        with self._write_raises(Model._name, field.name, failure):
            field.selection_ids.filtered(lambda s: s.value == "draft").unlink()
        self.env.flush_all()

        stored = self._read_jsonb(Model, field, record)
        self.assertEqual(
            stored.get(str(other.id)),
            "done",
            "the other company's unrelated value must survive the bypass",
        )
        self.assertFalse(stored.get(str(self.env.company.id)))

    def test_ondelete_tolerates_non_object_jsonb(self):
        Model, field = self._make_selection_field("scalar", company_dependent=True)
        polluted = Model.create({})
        healthy = Model.create({})
        Model.flush_model()
        self.env.cr.execute(
            SQL(
                "UPDATE %s SET %s = 'null'::jsonb WHERE id = %s",
                SQL.identifier(Model._table),
                SQL.identifier(field.name),
                polluted.id,
            )
        )
        self._set_jsonb(Model, field, healthy, {self.env.company.id: "draft"})

        field.selection_ids.filtered(lambda s: s.value == "draft").unlink()

        self.assertFalse(self._read_jsonb(Model, field, healthy))


class TestIrModelDataCacheInvalidation(TransactionCase):
    def _groups_cleared(self, mock):
        return any(call.args == ("groups",) for call in mock.call_args_list)

    def test_create_groups_xmlid_clears_groups_cache(self):
        group = self.env["res.groups"].create({"name": "IMD cache group create"})
        with patch.object(
            self.env.registry, "clear_cache", wraps=self.env.registry.clear_cache
        ) as mock_clear:
            self.env["ir.model.data"].create(
                {
                    "module": "base",
                    "name": "imd_cache_group_create",
                    "model": "res.groups",
                    "res_id": group.id,
                }
            )
        self.assertTrue(self._groups_cleared(mock_clear))

    def test_unlink_groups_xmlid_clears_groups_cache(self):
        group = self.env["res.groups"].create({"name": "IMD cache group unlink"})
        data = self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "imd_cache_group_unlink",
                "model": "res.groups",
                "res_id": group.id,
            }
        )
        with patch.object(
            self.env.registry, "clear_cache", wraps=self.env.registry.clear_cache
        ) as mock_clear:
            data.unlink()
        self.assertTrue(self._groups_cleared(mock_clear))

    def test_update_xmlids_populates_lookup_cache_and_clears_groups(self):
        group = self.env["res.groups"].create({"name": "IMD cache group update"})
        xmlid = "base.imd_cache_group_update"
        with patch.object(
            self.env.registry, "clear_cache", wraps=self.env.registry.clear_cache
        ) as mock_clear:
            self.env["ir.model.data"]._update_xmlids(
                [{"xml_id": xmlid, "record": group}]
            )
        self.assertTrue(self._groups_cleared(mock_clear))
        with self.assertQueryCount(0):
            self.assertEqual(
                self.env["ir.model.data"]._xmlid_lookup(xmlid),
                ("res.groups", group.id),
            )


class TestIrModelData(TransactionCase):
    def test_toggle_noupdate_access_and_flip(self):
        param = self.env["ir.config_parameter"].create(
            {"key": "imd.toggle.test", "value": "x"}
        )
        xid1 = self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "imd_toggle_a",
                "model": "ir.config_parameter",
                "res_id": param.id,
                "noupdate": False,
            }
        )
        xid2 = self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "imd_toggle_b",
                "model": "ir.config_parameter",
                "res_id": param.id,
                "noupdate": True,
            }
        )

        user = new_test_user(self.env, login="imd_toggle_user")
        with self.assertRaises(AccessError):
            self.env["ir.model.data"].with_user(user).toggle_noupdate(
                "ir.config_parameter", param.id
            )

        self.env["ir.model.data"].toggle_noupdate("ir.config_parameter", param.id)
        self.assertTrue(xid1.noupdate)
        self.assertFalse(xid2.noupdate)

    def _make_param_xid(self, name, noupdate=False):
        param = self.env["ir.config_parameter"].create(
            {"key": f"imd.{name}", "value": "x"}
        )
        xid = self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": name,
                "model": "ir.config_parameter",
                "res_id": param.id,
                "noupdate": noupdate,
            }
        )
        return param, xid

    def test_noupdate_only_write_skips_default_cache_clear(self):
        _param, xid = self._make_param_xid("imd_p1_noupdate_only")

        with patch.object(
            self.env.registry, "clear_cache", wraps=self.env.registry.clear_cache
        ) as mock_clear:
            xid.write({"noupdate": True})
        self.assertNotIn(
            (),
            [call.args for call in mock_clear.call_args_list],
            "a noupdate-only write must not clear the default registry cache",
        )

        with patch.object(
            self.env.registry, "clear_cache", wraps=self.env.registry.clear_cache
        ) as mock_clear:
            xid.write({"noupdate": False, "name": "imd_p1_noupdate_only_renamed"})
        self.assertIn(
            (),
            [call.args for call in mock_clear.call_args_list],
            "a write touching more than noupdate must clear the default cache",
        )

    def test_toggle_noupdate_batches_writes(self):
        param, _xid_a = self._make_param_xid("imd_p2_toggle_a", noupdate=False)
        for name, noupdate in (
            ("imd_p2_toggle_b", False),
            ("imd_p2_toggle_c", True),
        ):
            self.env["ir.model.data"].create(
                {
                    "module": "base",
                    "name": name,
                    "model": "ir.config_parameter",
                    "res_id": param.id,
                    "noupdate": noupdate,
                }
            )

        DataClass = type(self.env["ir.model.data"])
        orig_write = DataClass.write
        write_vals = []

        def spy(records, vals):
            write_vals.append(vals)
            return orig_write(records, vals)

        with patch.object(DataClass, "write", spy):
            self.env["ir.model.data"].toggle_noupdate("ir.config_parameter", param.id)

        self.assertLessEqual(
            len(write_vals),
            2,
            "toggle_noupdate must batch by current value (at most two writes)",
        )
        xids = self.env["ir.model.data"].search(
            [("model", "=", "ir.config_parameter"), ("res_id", "=", param.id)]
        )
        self.assertEqual(
            {xid.name: xid.noupdate for xid in xids},
            {
                "imd_p2_toggle_a": True,
                "imd_p2_toggle_b": True,
                "imd_p2_toggle_c": False,
            },
            "each xid must flip relative to its own previous value",
        )

    def test_empty_write_and_unlink_skip_cache_clear(self):
        empty = self.env["ir.model.data"].browse()
        with patch.object(
            self.env.registry, "clear_cache", wraps=self.env.registry.clear_cache
        ) as mock_clear:
            self.assertTrue(empty.write({"noupdate": True, "name": "zzz"}))
            self.assertTrue(empty.unlink())
        mock_clear.assert_not_called()

    def test_update_xmlids_literal_percent(self):
        record = self.env["res.partner.category"].create({"name": "Percent"})
        xmlid = "test_convert.category_100%_percent"
        self.env["ir.model.data"]._update_xmlids([{"xml_id": xmlid, "record": record}])
        self.assertEqual(
            self.env["ir.model.data"]._xmlid_lookup(xmlid),
            (record._name, record.id),
        )

    def _isolated_process_end(self, modules):
        with patch.object(self.env.registry, "loaded_xmlids", set()):
            self.env["ir.model.data"]._process_end(modules)

    def test_process_end_keeps_record_while_another_xmlid_lives(self):
        module = "x_imd_procend"
        category = self.env["res.partner.category"].create({"name": "procend"})
        self.env.flush_all()
        for index in range(3):
            self.env["ir.model.data"].create(
                {
                    "module": module,
                    "name": f"cat_{index}",
                    "model": "res.partner.category",
                    "res_id": category.id,
                }
            )
        self.env.flush_all()

        self._isolated_process_end([module])

        self.assertFalse(category.exists(), "record deleted exactly once")
        self.assertFalse(
            self.env["ir.model.data"].search([("module", "=", module)]),
            "every redundant xml id removed",
        )

    def test_process_end_keeps_record_owned_by_another_module(self):
        module = "x_imd_procend2"
        category = self.env["res.partner.category"].create({"name": "procend2"})
        self.env.flush_all()
        self.env["ir.model.data"].create(
            {
                "module": module,
                "name": "cat_a",
                "model": "res.partner.category",
                "res_id": category.id,
            }
        )
        keeper = self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "x_imd_procend2_keeper",
                "model": "res.partner.category",
                "res_id": category.id,
            }
        )
        self.env.flush_all()

        self._isolated_process_end([module])

        self.assertTrue(category.exists(), "another module still owns the record")
        self.assertTrue(keeper.exists())
        self.assertFalse(self.env["ir.model.data"].search([("module", "=", module)]))

    def test_lookup_xmlids_resolves(self):
        group = self.env.ref("base.group_user")
        rows = self.env["ir.model.data"]._get_xmlids(
            ["base.group_user", "base.zzz_no_such_xmlid"], self.env["res.groups"]
        )
        self.assertEqual(len(rows), 1)
        _id, module, name, model, res_id, _noupdate, r_id = rows[0]
        self.assertEqual(
            (module, name, model, res_id, r_id),
            ("base", "group_user", "res.groups", group.id, group.id),
        )


class TestIrModelConstraintReflection(TransactionCase):
    MODEL = "ir.model.data"

    def _constraint_rows(self, names):
        return {
            name: (id_, type_, definition, write_date)
            for name, id_, type_, definition, write_date in self.env.execute_query(
                SQL(
                    "SELECT name, id, type, definition, write_date"
                    " FROM ir_model_constraint WHERE name = ANY(%s)",
                    names,
                )
            )
        }

    def test_constraint_drop_resolves_table_from_postgres(self):
        rows = self.env.execute_query(
            SQL(
                """SELECT c.id, c.name, im.model
                   FROM ir_model_constraint c
                   JOIN ir_model im ON c.model = im.id
                   WHERE im.model = 'ir.actions.client' AND c.type = 'u'
                   LIMIT 1"""
            )
        )
        if not rows:
            self.skipTest("no reflected constraint on ir.actions.client")
        constraint_id, name, model_name = rows[0]
        self.assertNotEqual(
            self.env[model_name]._table,
            model_name.replace(".", "_"),
            "precondition: this model's table is not derivable from its name",
        )

        model_cls = self.env.registry.models.pop(model_name)
        try:
            self.env["ir.model.constraint"].browse(constraint_id).unlink()
        finally:
            self.env.registry.models[model_name] = model_cls

        remaining = self.env.execute_query(
            SQL(
                """SELECT 1 FROM pg_constraint cs
                   JOIN pg_class cl ON cs.conrelid = cl.oid
                   WHERE cs.conname = %s
                   AND cl.relnamespace = current_schema::regnamespace""",
                name,
            )
        )
        self.assertFalse(remaining, "constraint must actually be dropped")

    def test_process_end_keeps_a_constraint_the_registry_still_declares(self):
        rows = self.env.execute_query(
            SQL(
                """SELECT c.id, c.name, im.model, d.module || '.' || d.name
                   FROM ir_model_constraint c
                   JOIN ir_model im ON c.model = im.id
                   JOIN ir_model_data d
                     ON d.model = 'ir.model.constraint' AND d.res_id = c.id
                   WHERE d.module = 'base'
                     AND COALESCE(d.noupdate, false) = false"""
            )
        )
        target = next(
            (
                row
                for row in rows
                if (model := self.env.get(row[2])) is not None
                and row[1] in model._table_objects
            ),
            None,
        )
        if target is None:
            self.skipTest("no constraint reflected under base is still declared")
        cons_id, _name, _model_name, xmlid = target

        others = {
            row[0]
            for row in self.env.execute_query(
                SQL(
                    "SELECT module || '.' || name FROM ir_model_data"
                    " WHERE module = 'base'"
                )
            )
        } - {xmlid}
        loaded = self.env.registry.loaded_xmlids
        saved = set(loaded)
        loaded.clear()
        loaded.update(others)
        try:
            self.env["ir.model.data"]._process_end(["base"])
        finally:
            loaded.clear()
            loaded.update(saved)

        self.assertTrue(
            self.env["ir.model.constraint"].browse(cons_id).exists(),
            "a constraint the registry still declares must survive the GC",
        )

    def test_reflect_constraints_idempotent_and_repairs(self):
        Constraint = self.env["ir.model.constraint"]
        names = list(self.env[self.MODEL]._table_objects)
        self.assertTrue(names, "test model must declare table objects")

        Constraint._reflect_constraints([self.MODEL])
        before = self._constraint_rows(names)
        self.assertEqual(set(before), set(names), "every table object reflected")
        Constraint._reflect_constraints([self.MODEL])
        self.assertEqual(
            self._constraint_rows(names),
            before,
            "an unchanged constraint must not be rewritten (write_date stable)",
        )

        drifted = names[0]
        self.env.cr.execute(
            "UPDATE ir_model_constraint SET definition = 'bogus' WHERE name = %s",
            (drifted,),
        )
        Constraint._reflect_constraints([self.MODEL])
        after = self._constraint_rows(names)
        self.assertNotEqual(after[drifted][2], "bogus", "drifted row repaired")
        self.assertEqual(after[drifted][0], before[drifted][0])
