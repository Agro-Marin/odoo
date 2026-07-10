from unittest.mock import patch

from psycopg import IntegrityError
from psycopg.errors import NotNullViolation
from psycopg.types.json import Json

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, HttpCase, TransactionCase, tagged
from odoo.tests.common import new_test_user
from odoo.tools import SQL, mute_logger


class TestXMLID(TransactionCase):
    def get_data(self, xml_id):
        """Return the 'ir.model.data' record corresponding to ``xml_id``."""
        module, suffix = xml_id.split(".", 1)
        domain = [("module", "=", module), ("name", "=", suffix)]
        return self.env["ir.model.data"].search(domain)

    def test_create(self):
        model = self.env["res.partner.category"]
        xml_id = "test_convert.category_foo"

        # create category (flag 'noupdate' should be False by default)
        data = {"xml_id": xml_id, "values": {"name": "Foo"}}
        category = model._load_records([data])
        self.assertEqual(category, self.env.ref(xml_id, raise_if_not_found=False))
        self.assertEqual(category.name, "Foo")
        self.assertEqual(self.get_data(xml_id).noupdate, False)

        # update category
        data = {"xml_id": xml_id, "values": {"name": "Bar"}}
        category1 = model._load_records([data], update=True)
        self.assertEqual(category, category1)
        self.assertEqual(category.name, "Bar")
        self.assertEqual(self.get_data(xml_id).noupdate, False)

        # update category
        data = {"xml_id": xml_id, "values": {"name": "Baz"}, "noupdate": True}
        category2 = model._load_records([data], update=True)
        self.assertEqual(category, category2)
        self.assertEqual(category.name, "Baz")
        self.assertEqual(self.get_data(xml_id).noupdate, False)

    def test_create_noupdate(self):
        model = self.env["res.partner.category"]
        xml_id = "test_convert.category_foo"

        # create category
        data = {"xml_id": xml_id, "values": {"name": "Foo"}, "noupdate": True}
        category = model._load_records([data])
        self.assertEqual(category, self.env.ref(xml_id, raise_if_not_found=False))
        self.assertEqual(category.name, "Foo")
        self.assertEqual(self.get_data(xml_id).noupdate, True)

        # update category
        data = {"xml_id": xml_id, "values": {"name": "Bar"}, "noupdate": False}
        category1 = model._load_records([data], update=True)
        self.assertEqual(category, category1)
        self.assertEqual(category.name, "Foo")
        self.assertEqual(self.get_data(xml_id).noupdate, True)

        # update category
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

        # create category
        categories = model._load_records(data_list)
        foo = self.env.ref("test_convert.category_foo")
        bar = self.env.ref("test_convert.category_bar")
        self.assertEqual(categories, foo + bar)
        self.assertEqual(foo.name, "Foo")
        self.assertEqual(bar.name, "Bar")

        # check data
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

        # create categories
        foo = model._load_records([data_list[0]])
        bar = model._load_records([data_list[1]])
        baz = model._load_records([data_list[2]])
        self.assertEqual(foo.name, "Foo")
        self.assertEqual(bar.name, "Bar")
        self.assertEqual(baz.name, "Baz")

        # update them, and check the order of result
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

        # create user
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

        # create category
        category = model._load_records([data])
        self.assertEqual(category, self.env.ref(xml_id, raise_if_not_found=False))
        self.assertEqual(category.name, "Foo")

        # suppress category
        category.unlink()
        self.assertFalse(self.env.ref(xml_id, raise_if_not_found=False))

        # update category, this should recreate it
        category = model._load_records([data], update=True)
        self.assertEqual(category, self.env.ref(xml_id, raise_if_not_found=False))
        self.assertEqual(category.name, "Foo")

    def test_create_xmlids(self):
        # create users and assign them xml ids
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

        # noupdate case: pins current behaviour, not asserting it makes sense
        xmlid = "base.test_xmlid_noupdates"
        with self.assertQueryCount(1):
            self.env["ir.model.data"]._update_xmlids(
                [
                    {
                        "xml_id": xmlid,
                        "record": records[3],
                        "noupdate": True,
                    },  # record created as noupdate
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
        # Quick create an ir_model_field should not be possible
        # It should be raise a ValidationError
        with self.assertRaises(NotNullViolation):
            self.env["ir.model.fields"].name_create("field_name")

        # But with default_ we should be able to name_create
        self.env["ir.model.fields"].with_context(
            default_model_id=model.id,
            default_model=model.name,
            default_ttype="char",
        ).name_create("field_name")

    def test_reflect_models_empty_no_raise(self):
        """IMOD-L1: _reflect_models([]) is a clean no-op (no IndexError)."""
        # the guard lives in the method now, not only in the init_models caller
        self.assertIsNone(self.env["ir.model"]._reflect_models([]))

    def test_reflect_models_prewarms_get_id_cache(self):
        """IMOD-P1: after reflecting a model, _get_id resolves its id without a
        round-trip (the cache was pre-warmed from the model->id map)."""
        IrModel = self.env["ir.model"]
        model = IrModel.create({"model": "x_prewarm", "name": "Prewarm test"})
        # drop any cached entry so the assertion below proves the pre-warm,
        # not a leftover from create()
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
        # the inner function is named for readable tracebacks
        self.assertEqual(compute.__name__, "compute")

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
        abstract = IrModel._get("base")  # abstract: no table
        expected = (
            self.env["res.country"].with_context(active_test=False).search_count([])
        )
        # compute the batch in one shot (exercises the UNION ALL path)
        batch = concrete + abstract
        batch.invalidate_recordset(["count"])
        self.assertEqual(concrete.count, expected)
        self.assertEqual(abstract.count, 0)


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
        # If not enabled (like in demo data), landing on res.config will try
        # to disable module_sale_quotation_builder and raise an warning
        group_order_template = self.env.ref(
            "sale_management.group_sale_order_template",
            raise_if_not_found=False,
        )
        if group_order_template:
            self.env.ref("base.group_user").write(
                {"implied_ids": [(4, group_order_template.id)]}
            )

        # modify en_US translation
        field = self.env["ir.model.fields"].search(
            [("model_id.model", "=", "res.users"), ("name", "=", "login")]
        )
        self.assertEqual(field.with_context(lang="en_US").field_description, "Login")
        # check the name column of res.users is displayed as 'Login'
        self.start_tour("/odoo", "ir_model_fields_translation_en_tour", login="admin")
        field.update_field_translations("field_description", {"en_US": "Login2"})
        # check the name column of res.users is displayed as 'Login2'
        self.start_tour("/odoo", "ir_model_fields_translation_en_tour2", login="admin")

        # modify fr_FR translation
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
        # check the name column of res.users is displayed as 'Identifiant'
        self.start_tour("/odoo", "ir_model_fields_translation_fr_tour", login="admin")
        field.update_field_translations("field_description", {"fr_FR": "Identifiant2"})
        # check the name column of res.users is displayed as 'Identifiant2'
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

        # the column was renamed, not dropped and recreated
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
        # the index followed the rename (fork naming: '{table}__{column}_index')
        self.env.cr.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = %s", (table,)
        )
        indexes = {row[0] for row in self.env.cr.fetchall()}
        self.assertIn(f"{table}__x_renamed_index", indexes)
        self.assertNotIn(f"{table}__x_rename_index", indexes)
        # the data survived the rename
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
        # the batch fetch left the model name in cache: no query needed
        self.env.invalidate_all()
        fields_.mapped("display_name")
        with self.assertQueryCount(0):
            self.env["ir.model"]._get("res.partner").name  # noqa: B018

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


class TestIrModelInherit(TransactionCase):
    def test_inherit(self):
        # Filter for the base inheritance (ir.actions.actions) - other modules may add more
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

        # Deleting the value runs the 'set null' ondelete -> safe_write; the
        # refused ORM write must fall back to the raw column update.
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

    # --- ondelete policy branches (SEL-T1: previously untested) ---

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
            field.selection_ids.unlink()  # delete all three values at once

        # one company -> one batched resolve for all three values, not three
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
            [("draft", "Brouillon"), ("new", "New")],  # update + insert + remove
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
        # add_value populated the lookup cache: no query needed to resolve it
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
        # ir.config_parameter is writable only by group_system; a plain
        # internal user therefore fails the write-access gate.
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

        # access gate: non-system user cannot write ir.config_parameter
        user = new_test_user(self.env, login="imd_toggle_user")
        with self.assertRaises(AccessError):
            self.env["ir.model.data"].with_user(user).toggle_noupdate(
                "ir.config_parameter", param.id
            )

        # with access: each xid's noupdate flips
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

        # guard: any other key still busts the default (_xmlid_lookup) cache
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

    def test_reflect_constraints_idempotent_and_repairs(self):
        Constraint = self.env["ir.model.constraint"]
        names = list(self.env[self.MODEL]._table_objects)
        self.assertTrue(names, "test model must declare table objects")

        # settle: reflect once, then a second run must not touch any row
        Constraint._reflect_constraints([self.MODEL])
        before = self._constraint_rows(names)
        self.assertEqual(set(before), set(names), "every table object reflected")
        Constraint._reflect_constraints([self.MODEL])
        self.assertEqual(
            self._constraint_rows(names),
            before,
            "an unchanged constraint must not be rewritten (write_date stable)",
        )

        # a drifted definition is repaired by the batched upsert
        drifted = names[0]
        self.env.cr.execute(
            "UPDATE ir_model_constraint SET definition = 'bogus' WHERE name = %s",
            (drifted,),
        )
        Constraint._reflect_constraints([self.MODEL])
        after = self._constraint_rows(names)
        self.assertNotEqual(after[drifted][2], "bogus", "drifted row repaired")
        # ids preserved: repaired in place, not deleted and recreated
        self.assertEqual(after[drifted][0], before[drifted][0])
