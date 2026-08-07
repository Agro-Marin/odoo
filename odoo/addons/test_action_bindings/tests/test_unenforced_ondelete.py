from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUnenforcedOndeleteOwnership(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Actions = cls.env["ir.actions.actions"]
        cls.action = cls.env["ir.actions.act_window"].create(
            {"name": "tab-ondelete", "res_model": "res.currency"}
        )
        cls.holder = cls.env["tab.action.holder"].create({"action_id": cls.action.id})
        cls.mirror = cls.env["tab.action.mirror"].create({"holder_id": cls.holder.id})
        cls.env.flush_all()

    def _swept(self):
        return {
            (model_name, field_name): ondelete
            for model_name, field_name, ondelete in self.Actions._unenforced_reference_fields()
        }

    def _unfiltered_references(self):
        roots = self.Actions._root_model_names()
        return sorted(
            (model_name, field.name, field.ondelete or "set null")
            for model_name, model in self.env.registry.items()
            if not model._abstract
            for field in model._fields.values()
            if field.type == "many2one" and field.comodel_name in roots
        )

    def test_the_owning_field_is_swept(self):
        self.assertEqual(self._swept()[("tab.action.holder", "action_id")], "cascade")

    def test_the_related_field_is_not_swept(self):
        self.assertNotIn(("tab.action.mirror", "action_id"), self._swept())
        self.assertIn(
            ("tab.action.mirror", "action_id", "set null"),
            self._unfiltered_references(),
        )

    def test_the_computed_field_is_not_swept(self):
        self.assertNotIn(("tab.action.computed", "action_id"), self._swept())
        self.assertIn(
            ("tab.action.computed", "action_id", "set null"),
            self._unfiltered_references(),
        )

    def test_sweeping_a_computed_field_cannot_work(self):
        field = self.env["tab.action.computed"]._fields["action_id"]
        self.assertFalse(field.store)
        self.assertIsNone(field.search)
        with self.assertRaises(ValueError):
            self.env["tab.action.computed"].search(
                [("action_id", "in", self.action.ids)]
            )

    def test_sweeping_a_related_field_is_only_wasted_work(self):
        mirrors = self.env["tab.action.mirror"].search(
            [("action_id", "in", self.action.ids)]
        )
        self.assertTrue(mirrors)
        self.env["tab.action.holder"].search(
            [("action_id", "in", self.action.ids)]
        ).unlink()
        self.env.flush_all()
        self.assertFalse(mirrors.exists())
        mirrors.write({"action_id": False})

    def test_cascade_reaches_the_mirror_through_the_holder(self):
        holder_id, mirror_id = self.holder.id, self.mirror.id
        self.assertEqual(self.mirror.action_id.id, self.action.id)

        self.action.unlink()
        self.env.flush_all()

        for table, row_id in (
            ("tab_action_holder", holder_id),
            ("tab_action_mirror", mirror_id),
        ):
            self.env.cr.execute(
                f"SELECT count(*) FROM {table} WHERE id = %s",
                [row_id],
            )
            self.assertEqual(self.env.cr.fetchone()[0], 0, table)

    def test_the_filter_drops_exactly_the_non_owning_fields(self):
        unfiltered = {(m, f) for m, f, __ in self._unfiltered_references()}
        dropped = unfiltered - set(self._swept())
        self.assertEqual(
            dropped,
            {
                (model_name, field_name)
                for model_name, field_name in unfiltered
                if not (
                    (field := self.env[model_name]._fields[field_name]).store
                    and not field.related
                )
            },
        )
        self.assertIn(("tab.action.mirror", "action_id"), dropped)
        self.assertIn(("tab.action.computed", "action_id"), dropped)
