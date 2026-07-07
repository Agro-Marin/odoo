from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.ir_actions import _safe_eval_dict


@tagged("post_install", "-at_install")
class TestIrActionsExists(TransactionCase):
    """IRA-L1: ir.actions exists() must reflect uncommitted changes in the
    current transaction. The public exists() override that read the cached
    _existing() id set (stale for NewId / just-created records) was removed; the
    cache is now used only inside the already-flushing _get_bindings.
    """

    def test_exists_reflects_uncommitted_create(self):
        model = self.env["ir.actions.act_url"]
        action = model.create({"name": "audit-ira-l1", "url": "/audit/ira-l1"})
        # Standard ORM exists() must see the just-created (uncommitted) record.
        # The removed act_window override consulted a cached id-set that could
        # exclude such records.
        self.assertEqual(action.exists(), action)

    def test_get_bindings_still_resolves(self):
        # _get_bindings filters to existing actions via _existing(); it must
        # still return a mapping without raising after the override removal.
        bindings = self.env["ir.actions.actions"]._get_bindings("res.partner")
        self.assertIsInstance(dict(bindings), dict)


@tagged("post_install", "-at_install")
class TestIrActionsBindingsCacheOnCreate(TransactionCase):
    """ir.actions.actions.create must only clear the registry cache when a
    created action is bound: the protected cache (_get_bindings) only selects
    rows whose binding_model_id is set, so unbound creates cannot stale it.
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
