from odoo.tests.common import TransactionCase


class TestInverseCacheAlignment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        cls.old_parent = Partner.create({"name": "Old parent", "is_company": True})
        cls.new_parent = Partner.create({"name": "New parent", "is_company": True})
        cls.child = Partner.create({"name": "Child", "parent_id": cls.old_parent.id})

    @property
    def _parent_id_field(self):
        return self.env["res.partner"]._fields["parent_id"]

    @property
    def _child_ids_field(self):
        return self.env["res.partner"]._fields["child_ids"]

    def _reparent_under_protection(self, targets):
        self.env.flush_all()
        self.env.invalidate_all()
        self.old_parent.child_ids
        parent_id = self._parent_id_field
        with self.env.protecting([parent_id], targets):
            parent_id.__set__(targets, self.new_parent)
        return self._child_ids_field._get_cache(self.env).get(self.old_parent.id)

    def test_all_real_recordset_prunes_the_old_parent(self):
        cached = self._reparent_under_protection(self.child)
        self.assertEqual(
            tuple(cached or ()),
            (),
            "the old parent still lists a child that moved away",
        )

    def test_recordset_mixing_real_and_new_records_prunes_the_real_one(self):
        targets = self.env["res.partner"].browse(
            (self.child.id, self.env["res.partner"].new({"name": "Unsaved"}).id)
        )
        self.assertFalse(all(targets._ids), "the probe needs a mixed recordset")
        cached = self._reparent_under_protection(targets)
        self.assertEqual(
            tuple(cached or ()),
            (),
            "one unsaved record in the set made the real record's inverse "
            "lookup miss, so the old parent kept it in its cached child_ids",
        )

    def test_the_cached_inverse_agrees_with_the_database(self):
        targets = self.env["res.partner"].browse(
            (self.child.id, self.env["res.partner"].new({"name": "Unsaved"}).id)
        )
        self._reparent_under_protection(targets)
        cached = self.env["res.partner"].browse(self.old_parent.id).child_ids.ids
        self.env.flush_all()
        self.env.invalidate_all()
        fresh = self.env["res.partner"].browse(self.old_parent.id).child_ids.ids
        self.assertEqual(cached, fresh)


class TestRefCachePruning(TransactionCase):
    def test_unlink_drops_the_ref_memo(self):
        partner = self.env["res.partner"].create({"name": "Ref target"})
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "test_ref_cache_pruning",
                "model": "res.partner",
                "res_id": partner.id,
            }
        )
        self.env.flush_all()
        self.assertEqual(self.env.ref("base.test_ref_cache_pruning"), partner)
        key = ("res.partner", partner.id)
        self.assertIn(key, self.env.transaction._ref_cache)

        partner.unlink()

        self.assertNotIn(
            key,
            self.env.transaction._ref_cache,
            "the existence memo outlived the record it describes",
        )
