from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.ir_actions import _safe_eval_dict


@tagged("post_install", "-at_install")
class TestIrActionsExists(TransactionCase):
    """IRA-L1: ir.actions exists() must reflect uncommitted changes; the cached
    _existing() id-set (stale for NewId/just-created records) is now consulted
    only inside the already-flushing _get_bindings, not in a public override.
    """

    def test_exists_reflects_uncommitted_create(self):
        model = self.env["ir.actions.act_url"]
        action = model.create({"name": "audit-ira-l1", "url": "/audit/ira-l1"})
        # exists() must see the just-created (uncommitted) record.
        self.assertEqual(action.exists(), action)

    def test_get_bindings_still_resolves(self):
        bindings = self.env["ir.actions.actions"]._get_bindings("res.partner")
        self.assertIsInstance(dict(bindings), dict)


@tagged("post_install", "-at_install")
class TestIrActionsBindingsCacheOnCreate(TransactionCase):
    """ir.actions.actions.create only clears the registry cache for a bound
    action: _get_bindings selects only rows with binding_model_id set, so
    unbound creates cannot stale it.
    """

    def test_unbound_create_keeps_bindings_cache(self):
        Actions = self.env["ir.actions.actions"]
        before = Actions._get_bindings("res.partner")
        self.env["ir.actions.act_window"].create(
            {"name": "audit-unbound-action", "res_model": "res.partner"}
        )
        # Same cached object: the unbound create skipped the cache clear.
        self.assertIs(Actions._get_bindings("res.partner"), before)

    def test_bound_create_clears_bindings_cache(self):
        Actions = self.env["ir.actions.actions"]
        Actions._get_bindings("res.partner")  # warm the cache
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "audit-bound-action",
                "res_model": "res.partner",
                "binding_model_id": self.env["ir.model"]._get("res.partner").id,
            }
        )
        bindings = Actions._get_bindings("res.partner")
        self.assertIn(
            action.id,
            [a["id"] for bucket in bindings.values() for a in bucket],
            "a bound create must invalidate the cache so the binding shows up",
        )


class TestSafeEvalDict(TransactionCase):
    """Shared degrade-to-default evaluator for stored dict expressions."""

    def test_safe_eval_dict_degrades(self):
        self.assertEqual(_safe_eval_dict("{'a': 1}", {}, {}), {"a": 1})
        # A missing/falsy expression evaluates the "{}" fallback, not default.
        self.assertEqual(_safe_eval_dict(False, {}, {"d": 1}), {})
        sentinel = {"d": 1}
        # An un-evaluable expression degrades to the default.
        self.assertIs(_safe_eval_dict("1/0", {}, sentinel), sentinel)
        self.assertIs(_safe_eval_dict("[(", {}, sentinel), sentinel)
        # A non-dict result degrades to the default too.
        self.assertIs(_safe_eval_dict("[1, 2]", {}, sentinel), sentinel)
        # The eval context is visible to the expression.
        self.assertEqual(_safe_eval_dict("{'u': uid}", {"uid": 7}, {}), {"u": 7})


@tagged("post_install", "-at_install")
class TestIrActionsUnlinkCascadesEmbedded(TransactionCase):
    """ir.actions unlink() must manually cascade to ir.embedded.actions: the
    ``ondelete="cascade"`` on action_id never becomes a working FK (ir_actions
    is a PostgreSQL inheritance root), so without it deleted actions leave
    dangling embedded actions behind.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.parent_action = cls.env["ir.actions.act_window"].create(
            {"name": "audit-embedded-parent", "res_model": "res.partner"}
        )
        cls.target_action = cls.env["ir.actions.act_window"].create(
            {"name": "audit-embedded-target", "res_model": "res.partner"}
        )

    def _create_embedded(self):
        return self.env["ir.embedded.actions"].create(
            {
                "parent_action_id": self.parent_action.id,
                "parent_res_model": "res.partner",
                "action_id": self.target_action.id,
            }
        )

    def test_unlink_cascades_deletable_embedded_actions(self):
        embedded = self._create_embedded()
        self.target_action.unlink()
        self.assertFalse(
            embedded.exists(),
            "deleting an action must cascade-delete its embedded actions",
        )

    def test_unlink_blocked_by_seeded_embedded_action(self):
        # A data-file-seeded embedded action (real external id) is not deletable,
        # so the cascade's ondelete hook must block the action's deletion instead
        # of leaving it dangling.
        embedded = self._create_embedded()
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "audit_seeded_embedded_action",
                "model": "ir.embedded.actions",
                "res_id": embedded.id,
            }
        )
        with self.assertRaises(UserError):
            self.target_action.unlink()
        self.assertTrue(embedded.exists())
        self.assertTrue(self.target_action.exists())


@tagged("post_install", "-at_install")
class TestEmbeddedActionsGroupIdsConvention(TransactionCase):
    """ir.embedded.actions follows the group_ids naming convention of sibling
    action models (the field was historically misnamed groups_ids)."""

    def test_group_ids_field_renamed(self):
        fields = self.env["ir.embedded.actions"]._fields
        self.assertIn("group_ids", fields)
        self.assertNotIn("groups_ids", fields)
        self.assertIn(
            "group_ids",
            self.env["ir.embedded.actions"]._get_readable_fields(),
        )
