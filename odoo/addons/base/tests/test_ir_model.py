import traceback
from unittest.mock import patch

from psycopg import IntegrityError
from psycopg.errors import NotNullViolation
from psycopg.types.json import Json

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import NO_ACCESS
from odoo.models import is_model_definition, pop_field
from odoo.tests import Form, HttpCase, TransactionCase, tagged
from odoo.tests.common import new_test_user
from odoo.tools import SQL, escape_psql, mute_logger


class TestXMLID(TransactionCase):
    def get_data(self, xml_id):
        """Return the 'ir.model.data' record corresponding to ``xml_id``."""
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
        """Check that related field are handled correctly on new field"""
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
        """IMOD-L1: _reflect_models([]) is a clean no-op (no IndexError)."""
        self.assertIsNone(self.env["ir.model"]._reflect_models([]))

    def test_reflect_models_prewarms_get_id_cache(self):
        """IMOD-P1: after reflecting a model, _get_id resolves its id without a
        round-trip (the cache was pre-warmed from the model->id map)."""
        IrModel = self.env["ir.model"]
        model = IrModel.create({"model": "x_prewarm", "name": "Prewarm test"})
        self.env.registry.clear_cache("stable")
        IrModel._reflect_models(["x_prewarm"])
        with self.assertQueryCount(0):
            self.assertEqual(IrModel._get_id("x_prewarm"), model.id)

    def test_name_create_slugifies_name(self):
        """name_create turns punctuation/accents into a valid model name instead
        of failing the _check_model_name constraint."""
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
        """upsert_en must refuse a translated conflict column: its RETURNING
        round-trip yields an unhashable jsonb dict that would silently break the
        input-order reconstruction (previously a cryptic ``TypeError``)."""
        from odoo.addons.base.models.ir_model_common import upsert_en

        IrModel = self.env["ir.model"]
        self.assertTrue(IrModel._fields["name"].translate)
        with self.assertRaises(ValueError):
            upsert_en(IrModel, ["name", "model"], [("X", "x_up")], conflict=["name"])

    def test_upsert_en_rejects_duplicate_conflict_keys(self):
        """Two rows sharing a conflict key make PostgreSQL MERGE raise (a
        cardinality/unique violation) and would collapse onto one id; upsert_en
        rejects them up front with a clear ValueError."""
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
        """Empty fnames used to divide by zero when sizing the parameter batch;
        it now raises a clear ValueError."""
        from odoo.addons.base.models.ir_model_common import upsert_en

        IrModel = self.env["ir.model"]
        with self.assertRaises(ValueError):
            upsert_en(IrModel, [], [("x",)], conflict=["model"])

    def test_upsert_en_empty_rows_returns_empty(self):
        """No rows is a no-op that returns an empty id list without touching
        the database."""
        from odoo.addons.base.models.ir_model_common import upsert_en

        IrModel = self.env["ir.model"]
        self.assertEqual(
            upsert_en(IrModel, ["model", "name"], [], conflict=["model"]), []
        )

    def test_make_compute_filters_blank_dependencies(self):
        """A trailing/double comma in a manual field's ``depends`` must not
        produce an empty dependency name (which would later fail as
        ``model._fields['']`` during registry setup)."""
        from odoo.addons.base.models.ir_model_common import make_compute

        compute = make_compute("pass", "field_a, , field_b,")
        self.assertEqual(compute._depends, ("field_a", "field_b"))
        self.assertEqual(compute.__name__, "compute")

    def test_manual_compute_failure_names_the_field(self):
        """IMC-E1: a custom compute is ``exec``-ed from a shared helper, so the
        deepest traceback frame read ``File ""`` and *nothing* in the failure
        said which field ran.  The code block is now filed under
        ``<compute model.field>``."""
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
        """IMC-E1: a syntax error is only raised when the field is *read*, and
        used to surface as a bare ``SyntaxError (, line 1)`` naming nothing."""
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
        """_compute_count (single UNION ALL) returns the true archived-inclusive
        row count per model, 0 for abstract models, and stays correct when a
        whole recordset of mixed models is computed in one batch."""
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
        """IMOD-D1: a custom m2m table is never reflected into
        ``ir.model.relation`` (only non-manual ones are), so ``_drop_column`` is
        its only owner.  Deleting the *model* removed the field rows through the
        ``model_id`` FK cascade -- no Python, no drop -- leaking the table."""
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
        """IMOD-D2: the drop is guarded by "is any other field still using this
        table?" -- that guard must survive the extraction into
        ``_drop_m2m_tables``."""
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
        """IMOD-C1: the batch is one UNION ALL, so a model whose table is gone
        used to fail the whole query *and abort the transaction*, 500-ing the
        Models list view instead of showing the other counts."""
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
    """ir.model.fields write/constraint paths: translate-only optimisation and
    the relation-table name guard."""

    def _make_manual_field(self, stem, **vals):
        """Create a manual model with one manual char field; return ``(Model, field)``."""
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
        """IMF-P1: write({}) is a no-op and does not rebuild the registry."""
        _model, field = self._make_manual_field("empty")
        with patch.object(self.env.registry, "_setup_models__") as mock_setup:
            self.assertTrue(field.write({}))
        mock_setup.assert_not_called()

    def test_label_translate_write_skips_registry_setup(self):
        """IMF-P2: a label-only (translatable field_description) write refreshes
        the label cache via a targeted 'stable' clear, without a full rebuild.
        Mirrors test_selection_label_rename_skips_registry_setup.
        """
        Model, field = self._make_manual_field("label")
        with patch.object(self.env.registry, "_setup_models__") as mock_setup:
            field.write({"field_description": "Renamed Label"})
        mock_setup.assert_not_called()
        self.assertEqual(
            self.env["ir.model.fields"].get_field_string(Model._name)[field.name],
            "Renamed Label",
        )

    def test_field_rename_preserves_column_index_and_data(self):
        """IMF-R1: renaming a stored, indexed manual field renames the column
        and its index in place (no drop/recreate) and keeps the stored data."""
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
        """IMF-R2: a rename runs the expensive _prepare_update (view LIKE-scan
        + full registry rebuild) exactly once, not once per item plus once for
        the whole recordset."""
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
        """IMF-C4: the pre-19 boolean form of ``translate`` raises instead of
        being silently converted (the old shim guessed 'standard' for html
        fields on write)."""
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
        """IMF-C5: @api.constrains handlers raise ValidationError (not
        UserError) per the guidelines -- unknown dependency case."""
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
        """IMF-C5: _related_field errors surface as ValidationError through the
        _check_related constraint."""
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
        """IMF-C6: the ormcached _all_manual_field_data mapping is frozen, so a
        caller cannot corrupt the shared cached value."""
        self._make_manual_field("frozen")
        data = self.env["ir.model.fields"]._all_manual_field_data()
        self.assertIn("x_imf_frozen", data)
        with self.assertRaises((TypeError, NotImplementedError)):
            data["x_bogus"] = {}

    def test_compute_modules_shared_helper(self):
        """The shared compute_modules helper resolves the defining modules for
        both ir.model and ir.model.fields."""
        model = self.env["ir.model"]._get("res.partner")
        self.assertIn("base", model.modules.split(", "))
        field = self.env["ir.model.fields"]._get("res.partner", "name")
        self.assertIn("base", field.modules.split(", "))

    def test_display_name_batch_fetches_model_names(self):
        """IMF-P3: computing display_name pre-fetches every referenced model's
        name in one batch; the per-model _get(model).name read then needs no
        further query."""
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
        """IMF-C2: an invalid relation_table raises a translated, relation-table
        specific ValidationError (not the raw 'table name' message)."""
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
        """IMF-P3: the translate-only fast path must rebuild the registry when a
        translatable attribute appears or disappears.

        ``Field._description_help`` short-circuits on a falsy ``self.help`` and
        never consults the label cache, so clearing 'stable' alone left a newly
        added tooltip invisible in ``fields_get`` until the next full setup.
        """
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
        """IMF-P2 (regression guard): a label write that changes neither
        attribute's emptiness keeps the cheap 'stable' clear."""
        Model, field = self._make_manual_field("keepfast", help="Tip")
        with patch.object(self.env.registry, "_setup_models__") as mock_setup:
            field.write({"field_description": "Renamed", "help": "Tip 2"})
        mock_setup.assert_not_called()
        self.assertEqual(
            self.env["ir.model.fields"].get_field_help(Model._name)[field.name],
            "Tip 2",
        )

    def test_field_groups_without_xmlid_are_enforceable(self):
        """IMF-S1: ``Field.groups`` is a list of external ids, so a restricting
        group created through the UI (no xml id) used to reflect as *no*
        restriction at all -- the field became readable by everyone.  Creating
        the field now provisions the external id."""
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
        """IMF-S2: pre-existing data whose restricting groups lost their xml ids
        must hide the field, never expose it."""
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
        """IMF-A1: ``write`` used to ``pop`` model_id/model/state out of the
        caller's dict, so a reused vals dict silently lost keys."""
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
        """IMF-R3: the view scan feeds the field name to LIKE, where '_' -- in
        every ``x_`` name -- is a wildcard.  A view that merely *matched the
        wildcard* and was independently broken failed the ``_check_xml`` pass and
        blocked the delete with a bogus 'still present in views' error.

        Note the scan stays approximate even escaped: it is a substring match, so
        deleting ``x_ab`` still pulls in views referencing ``x_ab_long``.  Those
        false positives are harmless precisely because they pass ``_check_xml``;
        only an independently broken one turns into a spurious error.
        """
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
        # matched by 'x_ab_cd' only through the '_' wildcards, and broken on
        # its own account (unknown field) so _check_xml raises
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
        """IMF-R3 control: escaping must not weaken the real guard -- a view that
        genuinely references the field still blocks its deletion."""
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
        """IMF-R5: the view scan matches on a word boundary across every
        translation.  A ``LIKE`` scan could not: ``_`` is a wildcard, and even
        escaped it stays a substring match, so deleting ``x_ab`` dragged in every
        view mentioning ``x_ab_long``."""
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
        """IMF-R5: ``arch_db`` is per-language, so a field referenced only in a
        translated arch must still be found -- a ``like`` on the field looked at
        the active language alone."""
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
        """IMF-D1: ``_prepare_update`` pops the field from the registry before
        ``_drop_column`` runs, so a custom m2m with no stored ``relation_table``
        had no name to drop -- it raised ``KeyError``, and guarding that with
        ``.get()`` alone would silently leak the table instead."""
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
        """IMF-R4: renaming a field whose model is absent from the registry
        raised ``AttributeError: 'NoneType' has no attribute '_table'``."""
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
        """IMI-C1: ``UNIQUE(model_id, parent_id)`` cannot record both an
        ``_inherit`` and an ``_inherits`` link to one parent.  That used to
        surface as ``upsert_en: rows are not unique on conflict columns`` from
        deep inside the reflection; the model and parent are now named."""
        IrModelInherit = self.env["ir.model.inherit"]
        # the reflection walks the model-definition classes in the MRO, so the
        # overlap has to be introduced on the class that declares _inherits
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
    """IMR-P1: m2m relation reflection is batched like every other reflector."""

    def test_reflect_relations_is_idempotent_and_batched(self):
        """One call reflects every ``(model, table, module)`` triple; a second
        pass over the same input inserts nothing."""
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
        """An unresolvable module is logged and skipped, not crashed on: the
        row is NOT NULL on both module and model."""
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
    """Selection-row write: value rename on stored columns + uniqueness guard.
    Pins SEL-C1 (company-dependent jsonb rename corruption) and SEL-C2 (batch
    rename to a duplicate value).
    """

    def _make_selection_field(self, stem, *, company_dependent=False, values=None):
        """Create a manual model with one stored selection field, defaulting to
        ``draft``/``done`` values; return ``(Model, field)``.

        :param bool company_dependent: store the column as per-company jsonb.
        :param values: optional ``[(value, label), ...]`` selection options.
        """
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
        """Seed a company-dependent jsonb column with ``{company_id: value}``.

        Written directly because company-dependent ORM writes for a company
        outside the user's allowed set fall back instead of storing a distinct
        key, which would prevent genuinely distinct per-company values.
        """
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
        """Return the raw per-company jsonb stored for ``record``."""
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
        """Renaming a value on a plain selection column migrates stored data."""
        Model, field = self._make_selection_field("plain")
        record = Model.create({"x_plain": "draft"})
        record.flush_recordset()

        field.selection_ids.filtered(lambda s: s.value == "draft").write(
            {"value": "pending"}
        )

        record.invalidate_recordset(["x_plain"])
        self.assertEqual(record.x_plain, "pending")

    def test_selection_value_rename_company_dependent(self):
        """SEL-C1: a value rename migrates EVERY company's jsonb key.

        The pre-fix ``UPDATE col = new WHERE col = old`` errors on a jsonb
        (company-dependent) column / matches nothing, orphaning stored values.
        """
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
        """SEL-C1: only jsonb keys holding the renamed value migrate; siblings stay."""
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
        """SEL-C2: renaming several rows of one field to the same value is
        rejected up front, not aborted mid-write on the UNIQUE constraint."""
        _model, field = self._make_selection_field("batch")
        self.assertEqual(len(field.selection_ids), 2)
        with self.assertRaises(UserError):
            field.selection_ids.write({"value": "merged"})

    def test_selection_label_rename_skips_registry_setup(self):
        """SEL-C6: a label-only edit refreshes the selection label cache via a
        targeted 'stable' clear, without a full registry rebuild."""
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
        """SEL-C6: a value change still rebuilds the registry (the valid-value
        set changed, so live-read fields and validation must be refreshed)."""
        _model, field = self._make_selection_field("setup")
        draft = field.selection_ids.filtered(lambda s: s.value == "draft")
        with patch.object(self.env.registry, "_setup_models__") as mock_setup:
            draft.write({"value": "pending"})
        mock_setup.assert_called()

    def test_selection_ondelete_bypass_on_recoverable_error(self):
        """SEL-C4: a recoverable ORM-write failure during ondelete cleanup falls
        back to the raw column update (the documented module-uninstall path)."""
        Model, field = self._make_selection_field("ondok")
        record = Model.create({"x_ondok": "draft"})
        record.flush_recordset()
        draft = field.selection_ids.filtered(lambda s: s.value == "draft")

        original_write = type(record).write

        def refusing_write(self, vals):
            if "x_ondok" in vals:
                raise ValidationError("ondelete write refused by a constraint")
            return original_write(self, vals)

        with patch.object(type(record), "write", refusing_write):
            draft.unlink()

        record.invalidate_recordset(["x_ondok"])
        self.assertFalse(record.x_ondok)

    def test_selection_ondelete_propagates_programming_error(self):
        """SEL-C4: a non-recoverable programming error during ondelete cleanup is
        no longer masked by a silent ORM bypass -- it propagates."""
        Model, field = self._make_selection_field("ondbug")
        record = Model.create({"x_ondbug": "draft"})
        record.flush_recordset()
        draft = field.selection_ids.filtered(lambda s: s.value == "draft")

        original_write = type(record).write

        def buggy_write(self, vals):
            if "x_ondbug" in vals:
                raise TypeError("programming error in an override")
            return original_write(self, vals)

        with patch.object(type(record), "write", buggy_write):
            with self.assertRaises(TypeError):
                draft.unlink()

    def _field_obj(self, model, stem):
        """Return the live ORM field object for a manual selection field."""
        return self.env[model._name]._fields[f"x_{stem}"]

    def test_ondelete_set_null(self):
        """The implicit 'set null' policy (manual field) clears holders."""
        Model, field = self._make_selection_field("pnull")
        record = Model.create({"x_pnull": "draft"})
        record.flush_recordset()
        field.selection_ids.filtered(lambda s: s.value == "draft").unlink()
        record.invalidate_recordset(["x_pnull"])
        self.assertFalse(record.x_pnull)

    def test_ondelete_set_constant(self):
        """'set X' rewrites holders to the constant value X."""
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
        """'set default' rewrites holders to the field default."""
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
        """'cascade' unlinks the records holding the deleted value."""
        Model, field = self._make_selection_field("pcasc")
        record = Model.create({"x_pcasc": "draft"})
        record.flush_recordset()
        with patch.object(
            self._field_obj(Model, "pcasc"), "ondelete", {"draft": "cascade"}
        ):
            field.selection_ids.filtered(lambda s: s.value == "draft").unlink()
        self.assertFalse(record.exists())

    def test_ondelete_callable(self):
        """A callable ondelete policy receives the recordset holding the value."""
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
        """SEL-P3: a field's deleted values are resolved in a single batched
        query per company, and every value's holders are still processed."""
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
        """SEL-C8 (finding 15): _update_selection's return value was unused by
        all callers and inaccurate; it now returns None while still applying
        the insert/update/remove diff."""
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
        """SEL-P3: the jsonb (company-dependent) resolve branch finds and clears
        the per-company holders of the deleted value."""
        company = self.env.company
        Model, field = self._make_selection_field("pcd", company_dependent=True)
        record = Model.create({})
        record.flush_recordset()
        self._set_jsonb(Model, field, record, {company.id: "draft"})

        field.selection_ids.filtered(lambda s: s.value == "draft").unlink()

        record.invalidate_recordset(["x_pcd"])
        self.assertFalse(record.with_company(company).x_pcd)

    def test_ondelete_company_dependent_outside_env_companies(self):
        """SEL-P4: the ondelete sweep is driven by the companies that actually
        hold a value, not by ``env.companies``.

        ``env.companies`` is the acting user's UI scope; scoping the sweep to it
        left the deleted value stored for every other company -- an asymmetry
        with a value *rename*, whose ``jsonb_object_agg`` covers every key."""
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
        """SEL-C3: when the ORM write fails, the bypass writes raw SQL.
        ``convert_to_column_insert`` renders a company-dependent value as a whole
        ``{company: value}`` object (``NULL`` when falsy), so assigning it wiped
        every *other* company's value.  Widening the ondelete sweep past
        ``env.companies`` makes that fallback markedly easier to reach.
        """
        other = self.env["res.company"].create({"name": "SEL-C3 other"})
        Model, field = self._make_selection_field("bypass", company_dependent=True)
        record = Model.create({})
        record.flush_recordset()
        self._set_jsonb(
            Model, field, record, {self.env.company.id: "draft", other.id: "done"}
        )

        original_write = type(Model).write

        def failing_write(records, vals):
            if field.name in vals:
                raise UserError("forced ORM failure")
            return original_write(records, vals)

        with patch.object(type(Model), "write", failing_write):
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
        """SEL-C4: the company sweep calls ``jsonb_object_keys``, which raises on
        any non-object.  The JSON scalar ``null`` is not SQL ``NULL``, so an
        ``IS NOT NULL`` guard lets it through and the whole unlink blows up on
        data the previous ``env.companies`` sweep simply ignored.
        """
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
    """IMD-T2: the symmetric `groups`-cache clears on the create/unlink/
    _update_xmlids res.groups paths, plus the _xmlid_lookup cache population."""

    def _groups_cleared(self, mock):
        """True if the patched clear_cache was called with the 'groups' bucket."""
        return any(call.args == ("groups",) for call in mock.call_args_list)

    def test_create_groups_xmlid_clears_groups_cache(self):
        """create() of a res.groups xmlid busts the groups cache."""
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
        """unlink() of a surviving res.groups xmlid busts the groups cache."""
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
        """_update_xmlids busts the groups cache for a res.groups row and
        pre-populates _xmlid_lookup with the freshly upserted value."""
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
    """IMD-T3: toggle_noupdate access gate and multi-xid flip semantics."""

    def test_toggle_noupdate_access_and_flip(self):
        """A user lacking write access on the target is rejected; with access,
        every xid of the record flips its noupdate flag."""
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
        """IMD-P1: a write touching only ``noupdate`` must not flush the whole
        default registry cache (no cached result depends on ``noupdate``),
        while any other key still does."""
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
        """IMD-P2: ``toggle_noupdate`` groups the xids by current value and
        issues at most two write() calls, not one per xid -- while still
        flipping each xid independently."""
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
        """IMD-P3 (finding 12): a write/unlink on an empty ir.model.data
        recordset is a no-op and must not clear any registry cache."""
        empty = self.env["ir.model.data"].browse()
        with patch.object(
            self.env.registry, "clear_cache", wraps=self.env.registry.clear_cache
        ) as mock_clear:
            self.assertTrue(empty.write({"noupdate": True, "name": "zzz"}))
            self.assertTrue(empty.unlink())
        mock_clear.assert_not_called()

    def test_update_xmlids_literal_percent(self):
        """IMD-S2 (finding 13): the SQL-composed xmlid upsert handles values
        containing a literal '%' (previously a str.format template with
        classic placeholders)."""
        record = self.env["res.partner.category"].create({"name": "Percent"})
        xmlid = "test_convert.category_100%_percent"
        self.env["ir.model.data"]._update_xmlids([{"xml_id": xmlid, "record": record}])
        self.assertEqual(
            self.env["ir.model.data"]._xmlid_lookup(xmlid),
            (record._name, record.id),
        )

    def _isolated_process_end(self, modules):
        """Run ``_process_end`` without disturbing the loader's xml-id set.

        ``_process_end`` ends with ``loaded_xmlids.clear()``.  Called from a test
        that runs *during* module loading, that empties the set the loader has
        been accumulating across modules, and the real ``_process_end`` at the
        end of the load then treats every earlier record as removed from the
        data and deletes it.  A throwaway set keeps the blast radius inside the
        test; the registry attribute is restored on exit.
        """
        with patch.object(self.env.registry, "loaded_xmlids", set()):
            self.env["ir.model.data"]._process_end(modules)

    def test_process_end_keeps_record_while_another_xmlid_lives(self):
        """IMD-P1: ``_process_end`` deletes a record only once *all* its xml ids
        are gone.  The per-row ``search_count`` that answered "does another live
        xml id point here?" is now a single batched count that the loop
        decrements, so the ordering must still hold: with three xml ids, the two
        highest ids are dropped and only the last one deletes the record."""
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
        """IMD-P1: an xml id from a module outside the batch still counts as a
        live owner, so the record survives."""
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
        """IMD-S1 guard: ``_lookup_xmlids`` (rewritten onto the SQL wrapper)
        still resolves an existing xmlid with the joined record id, and an
        unknown suffix yields no row."""
        group = self.env.ref("base.group_user")
        rows = self.env["ir.model.data"]._lookup_xmlids(
            ["base.group_user", "base.zzz_no_such_xmlid"], self.env["res.groups"]
        )
        self.assertEqual(len(rows), 1)
        _id, module, name, model, res_id, _noupdate, r_id = rows[0]
        self.assertEqual(
            (module, name, model, res_id, r_id),
            ("base", "group_user", "res.groups", group.id, group.id),
        )


class TestIrModelConstraintReflection(TransactionCase):
    """IMC-P1 (finding 14): batched _reflect_constraints keeps the reflected
    rows in sync -- idempotent on unchanged rows, repairing drifted ones."""

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
        """IMC-D1: ``unlink`` runs while the owning module is being uninstalled,
        i.e. exactly when its model is gone from the registry.  The old fallback
        derived the table as ``model.replace(".", "_")``, which is wrong for
        every model with a custom ``_table`` (``ir.actions.client`` lives in
        ``ir_act_client``), so the constraint was silently left in place."""
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
