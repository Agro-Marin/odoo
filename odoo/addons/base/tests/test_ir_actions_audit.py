from psycopg.errors import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

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
        self.assertIs(Actions._get_bindings("res.partner"), before)

    def test_bound_create_clears_bindings_cache(self):
        Actions = self.env["ir.actions.actions"]
        Actions._get_bindings("res.partner")
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
        self.assertEqual(_safe_eval_dict(False, {}, {"d": 1}), {})
        sentinel = {"d": 1}
        self.assertIs(_safe_eval_dict("1/0", {}, sentinel), sentinel)
        self.assertIs(_safe_eval_dict("[(", {}, sentinel), sentinel)
        self.assertIs(_safe_eval_dict("[1, 2]", {}, sentinel), sentinel)
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


@tagged("post_install", "-at_install")
class TestIrActionsUnenforcedReferences(TransactionCase):
    """unlink() derives the references PostgreSQL cannot cascade from the
    registry, instead of hard-coding ir.actions.todo / ir.filters /
    ir.embedded.actions -- which silently left rows behind for every module
    that declared its own Many2one to ir.actions.actions.
    """

    def test_registry_sweep_lists_every_declared_reference(self):
        Actions = self.env["ir.actions.actions"]
        declared = {
            (model_name, field_name)
            for model_name, model in self.env.registry.items()
            if not model._abstract
            for field_name, field in model._fields.items()
            if field.type == "many2one"
            and field.comodel_name
            in ("ir.actions.actions", "ir.actions.act_window_close")
        }
        swept = {(m, f) for m, f, __ in Actions._unenforced_reference_fields()}
        self.assertEqual(swept, declared)

    def test_no_real_foreign_key_backs_those_fields(self):
        """The premise of the sweep: no FK exists, so ondelete never fires."""
        self.env.cr.execute(
            """
            SELECT count(*) FROM pg_constraint con
              JOIN pg_class fcl ON fcl.oid = con.confrelid
             WHERE con.contype = 'f' AND fcl.relname = 'ir_actions'
            """
        )
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_cascade_reference_is_deleted(self):
        action = self.env["ir.actions.act_window"].create(
            {"name": "audit-sweep-cascade", "res_model": "res.partner"}
        )
        filter_ = self.env["ir.filters"].create(
            {
                "name": "audit-sweep-filter",
                "model_id": "res.partner",
                "action_id": action.id,
            }
        )
        todo = self.env["ir.actions.todo"].create({"action_id": action.id})
        action.unlink()
        self.assertFalse(filter_.exists())
        self.assertFalse(todo.exists())

    def test_set_null_reference_is_cleared(self):
        """res.users.action_id declares no ondelete, so it defaults to set null."""
        action = self.env["ir.actions.act_window"].create(
            {"name": "audit-sweep-home", "res_model": "res.partner"}
        )
        user = self.env["res.users"].create(
            {
                "login": "audit-sweep-user",
                "name": "audit-sweep-user",
                "action_id": action.id,
            }
        )
        action.unlink()
        self.assertFalse(user.action_id)

    def test_todo_action_id_declares_cascade(self):
        """The sweep obeys the declaration, so it has to state the real intent."""
        self.assertEqual(
            self.env["ir.actions.todo"]._fields["action_id"].ondelete, "cascade"
        )


@tagged("post_install", "-at_install")
class TestIrActionsCacheInvalidation(TransactionCase):
    """write() invalidates on the fields that registry caches actually read.

    The previous safelist-of-everything-else marked ``path`` cache-safe, but
    ``ir.ui.menu.load_menus`` embeds it as each menu's ``action_path``, so
    renaming a path left the whole web client linking to the old URL.
    """

    def test_path_write_invalidates_menu_cache(self):
        menu = self.env["ir.ui.menu"].search([("action", "!=", False)], limit=1)
        action = self.env[menu.action._name].browse(menu.action.id)
        action.path = "audit_cache_path_before"
        self.env.flush_all()
        self.env.registry.clear_cache()

        self.assertEqual(
            self.env["ir.ui.menu"].load_menus(False)[menu.id]["action_path"],
            "audit_cache_path_before",
        )
        action.write({"path": "audit_cache_path_after"})
        self.env.flush_all()
        self.assertEqual(
            self.env["ir.ui.menu"].load_menus(False)[menu.id]["action_path"],
            "audit_cache_path_after",
        )

    def test_inert_field_write_keeps_cache(self):
        """Writing a field no registry cache reads must not flush the caches."""
        Actions = self.env["ir.actions.actions"]
        action = self.env["ir.actions.act_window"].create(
            {"name": "audit-inert", "res_model": "res.partner"}
        )
        self.env.flush_all()
        before = Actions._get_bindings("res.partner")
        action.write({"limit": 42})
        self.assertIs(Actions._get_bindings("res.partner"), before)


@tagged("post_install", "-at_install")
class TestIrActionsComputeDependencies(TransactionCase):
    """Non-stored computes must declare what they actually read."""

    def test_embedded_actions_are_per_active_record(self):
        """embedded_action_ids is context-derived; without depends_context the
        first record's result was served for every other record."""
        partner_a = self.env["res.partner"].create({"name": "audit-emb-A"})
        partner_b = self.env["res.partner"].create({"name": "audit-emb-B"})
        parent = self.env["ir.actions.act_window"].create(
            {"name": "audit-emb-parent", "res_model": "res.partner"}
        )
        target = self.env["ir.actions.act_window"].create(
            {"name": "audit-emb-target", "res_model": "res.partner"}
        )
        embedded = self.env["ir.embedded.actions"].create(
            {
                "parent_action_id": parent.id,
                "parent_res_model": "res.partner",
                "action_id": target.id,
                "parent_res_id": partner_a.id,
            }
        )
        self.env.flush_all()

        ctx_a = {"active_id": partner_a.id, "active_model": "res.partner"}
        ctx_b = {"active_id": partner_b.id, "active_model": "res.partner"}
        self.assertEqual(
            parent.with_context(**ctx_a).embedded_action_ids.ids, embedded.ids
        )
        self.assertEqual(parent.with_context(**ctx_b).embedded_action_ids.ids, [])

    def test_views_follow_view_ids_sequence(self):
        """views is ordered by view_ids._order, so it depends on sequence."""
        list_view = self.env["ir.ui.view"].search(
            [("type", "=", "list"), ("model", "=", "res.partner")], limit=1
        )
        form_view = self.env["ir.ui.view"].search(
            [("type", "=", "form"), ("model", "=", "res.partner")], limit=1
        )
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "audit-views",
                "res_model": "res.partner",
                "view_mode": "list,form",
            }
        )
        line = self.env["ir.actions.act_window.view"].create(
            {
                "act_window_id": action.id,
                "view_id": list_view.id,
                "view_mode": "list",
                "sequence": 1,
            }
        )
        self.env["ir.actions.act_window.view"].create(
            {
                "act_window_id": action.id,
                "view_id": form_view.id,
                "view_mode": "form",
                "sequence": 2,
            }
        )
        self.assertEqual(action.views[0], (list_view.id, "list"))
        line.sequence = 99
        self.assertEqual(action.views[0], (form_view.id, "form"))

    def test_client_params_depend_on_uid(self):
        """_compute_params evaluates the stored expression with `uid`."""
        params_field = self.env["ir.actions.client"]._fields["params"]
        __depends, depends_context = params_field.get_depends(
            self.env["ir.actions.client"]
        )
        self.assertIn("uid", depends_context)


@tagged("post_install", "-at_install")
class TestIrActionsReadableFieldsAreFields(TransactionCase):
    """_get_readable_fields() feeds read(), so every name must be a real field.

    Virtual client-side keys (effect/infos/close, the report action dict keys)
    live in _get_client_only_keys() instead; clean_action keeps the union.
    """

    def _action_models(self):
        Actions = self.env.registry["ir.actions.actions"]
        return [
            name
            for name, model in self.env.registry.items()
            if issubclass(model, Actions)
        ]

    def test_readable_fields_are_all_orm_fields(self):
        for name in self._action_models():
            model = self.env[name]
            virtual = sorted(
                f for f in model._get_readable_fields() if f not in model._fields
            )
            self.assertFalse(virtual, "%s lists non-fields %s" % (name, virtual))

    def test_client_only_keys_are_not_orm_fields(self):
        for name in self._action_models():
            model = self.env[name]
            stored = sorted(
                k for k in model._get_client_only_keys() if k in model._fields
            )
            self.assertFalse(stored, "%s lists real fields %s" % (name, stored))

    def test_clean_action_keeps_client_only_keys(self):
        from odoo.addons.web.controllers.utils import clean_action

        with self.assertNoLogs("odoo.addons.web.controllers.utils", "WARNING"):
            cleaned = clean_action(
                {"type": "ir.actions.act_window_close", "effect": {"type": "rainbow"}},
                env=self.env,
            )
        self.assertEqual(cleaned["effect"], {"type": "rainbow"})

    def test_action_dict_key_order_is_deterministic(self):
        action = self.env["ir.actions.act_window"].create(
            {"name": "audit-order", "res_model": "res.partner"}
        )
        readable = action._get_readable_fields()
        keys = list(action._get_action_dict())
        self.assertEqual(set(keys), set(readable))
        # read() preserves the order of the field list it is given, so the
        # payload's key order is stable only because _get_action_dict sorts.
        self.assertEqual(keys, list(action.sudo().read(sorted(readable))[0]))
        self.assertNotEqual(
            keys, list(action.sudo().read(sorted(readable, reverse=True))[0])
        )


@tagged("post_install", "-at_install")
class TestIrActionsTodoOpenState(TransactionCase):
    """Opening a configuration wizard must actually open it."""

    def _make_todo(self, sequence):
        return self.env["ir.actions.todo"].create(
            {
                "action_id": self.env.ref("base.action_client_base_menu").id,
                "sequence": sequence,
            }
        )

    def test_reopening_a_todo_wins_over_older_open_ones(self):
        """The regression: opening the higher-sequence todo used to be a
        silent no-op, because the old rule kept the lowest sequence instead of
        the record whose write triggered it."""
        self.env["ir.actions.todo"].search([]).write({"state": "done"})
        early = self._make_todo(1)
        late = self._make_todo(5)
        self.env.flush_all()

        early.action_open()
        self.assertEqual(early.state, "open")
        self.assertEqual(late.state, "done")

        late.action_open()
        self.assertEqual(late.state, "open")
        self.assertEqual(early.state, "done")

    def test_only_one_todo_stays_open(self):
        self.env["ir.actions.todo"].search([]).write({"state": "done"})
        self._make_todo(1)
        self._make_todo(2)
        self._make_todo(3)
        self.assertEqual(
            self.env["ir.actions.todo"].search_count([("state", "=", "open")]), 1
        )

    def test_action_launch_returns_only_readable_fields(self):
        server_action = self.env["ir.actions.server"].create(
            {
                "name": "audit-launch-server",
                "model_id": self.env["ir.model"]._get("res.partner").id,
                "state": "code",
                "code": "record.name",
            }
        )
        todo = self.env["ir.actions.todo"].create({"action_id": server_action.id})
        result = todo.action_launch()
        self.assertEqual(todo.state, "done")
        self.assertLessEqual(set(result), server_action._get_readable_fields())
        self.assertNotIn("code", result)

    def test_unlink_keeps_open_menu_and_deletes_the_rest(self):
        open_menu = self.env.ref("base.open_menu")
        other = self._make_todo(50)
        (open_menu | other).unlink()
        self.assertTrue(open_menu.exists())
        self.assertFalse(other.exists())
        self.assertEqual(
            open_menu.action_id.id, self.env.ref("base.action_client_base_menu").id
        )


@tagged("post_install", "-at_install")
class TestIrActionsActWindowValidation(TransactionCase):
    def test_empty_view_mode_segment_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["ir.actions.act_window"].create(
                {
                    "name": "audit-empty-mode",
                    "res_model": "res.partner",
                    "view_mode": "list,,form",
                }
            )

    def test_create_does_not_mutate_caller_vals(self):
        vals = {"res_model": "res.partner"}
        self.env["ir.actions.act_window"].create([vals])
        self.assertEqual(vals, {"res_model": "res.partner"})

    def test_create_still_defaults_the_name(self):
        action = self.env["ir.actions.act_window"].create({"res_model": "res.partner"})
        self.assertEqual(action.name, self.env["res.partner"]._description)


@tagged("post_install", "-at_install")
class TestIrActionsUnlinkIsAtomic(TransactionCase):
    """The reference sweep must not survive its own failure.

    unlink() applies the ondelete rules PostgreSQL cannot, one model at a time
    in the registry's alphabetical order. Any reference the ORM refuses to
    delete -- an @api.ondelete guard, an access error, a constraint -- used to
    abort the sweep with the earlier models' deletions already applied and the
    action itself still there. ValidationError/UserError leave the transaction
    usable, so a caller that catches one keeps the destruction.
    """

    def setUp(self):
        super().setUp()
        self.action = self.env["ir.actions.act_window"].create(
            {"name": "audit-atomic-target", "res_model": "res.partner"}
        )
        self.parent = self.env["ir.actions.act_window"].create(
            {"name": "audit-atomic-parent", "res_model": "res.partner"}
        )

    def _seeded_embedded_action(self):
        """An embedded action ir.embedded.actions refuses to delete."""
        embedded = self.env["ir.embedded.actions"].create(
            {
                "parent_action_id": self.parent.id,
                "parent_res_model": "res.partner",
                "action_id": self.action.id,
            }
        )
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "audit_atomic_seeded_embedded",
                "model": "ir.embedded.actions",
                "res_id": embedded.id,
            }
        )
        return embedded

    def test_failed_unlink_keeps_earlier_cascades(self):
        # ir.actions.todo sorts before ir.embedded.actions in the sweep, so it
        # is cascade-deleted before the guard on the latter aborts the unlink.
        todo = self.env["ir.actions.todo"].create({"action_id": self.action.id})
        embedded = self._seeded_embedded_action()

        with self.assertRaises(UserError):
            self.action.unlink()

        self.assertTrue(self.action.exists(), "the action itself survived")
        self.assertTrue(embedded.exists(), "the blocking reference survived")
        self.assertTrue(
            todo.exists(),
            "a reference deleted earlier in the sweep must be restored when the "
            "sweep aborts, exactly as a foreign key cascade would be",
        )

    def test_failed_unlink_keeps_earlier_set_null(self):
        user = self.env["res.users"].create(
            {
                "login": "audit-atomic-user",
                "name": "audit-atomic-user",
                "action_id": self.action.id,
            }
        )
        self._seeded_embedded_action()

        with self.assertRaises(UserError):
            self.action.unlink()

        self.assertEqual(user.action_id.id, self.action.id)

    def test_restrict_is_resolved_before_anything_is_destroyed(self):
        todo = self.env["ir.actions.todo"].create({"action_id": self.action.id})
        Actions = self.env.registry["ir.actions.actions"]
        self.patch(
            Actions,
            "_unenforced_reference_fields",
            lambda records: (
                ("ir.actions.todo", "action_id", "cascade"),
                ("res.users", "action_id", "restrict"),
            ),
        )
        self.env["res.users"].create(
            {
                "login": "audit-restrict-user",
                "name": "audit-restrict-user",
                "action_id": self.action.id,
            }
        )
        with self.assertRaises(ValidationError):
            self.action.unlink()
        self.assertTrue(todo.exists())
        self.assertTrue(self.action.exists())

    def test_related_reference_field_normalises_its_ondelete(self):
        """A related field skips setup_nonrelated, so its ondelete stays None.

        The sweep normalises it the way Many2one.update_db_foreign_key would,
        instead of letting None reach the policy dispatch as a fourth value.
        """
        policies = {
            ondelete
            for __, __, ondelete in self.env[
                "ir.actions.actions"
            ]._unenforced_reference_fields()
        }
        self.assertNotIn(None, policies)
        self.assertLessEqual(policies, {"cascade", "restrict", "set null"})


@tagged("post_install", "-at_install")
class TestIrActionsRootModelUnlink(TransactionCase):
    """ir_actions is a PostgreSQL inheritance root, so deleting a subtype row
    through ir.actions.actions reaches it -- but every ORM cleanup keyed on the
    model name misses, leaving a dangling ir.model.data row behind.
    """

    def test_unlink_through_the_root_model_cleans_up_the_xml_id(self):
        action = self.env["ir.actions.act_window"].create(
            {"name": "audit-root-unlink", "res_model": "res.partner"}
        )
        self.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "audit_root_unlink_action",
                "model": "ir.actions.act_window",
                "res_id": action.id,
            }
        )
        self.env["ir.actions.actions"].browse(action.id).unlink()
        self.env.flush_all()

        self.env.cr.execute(
            "SELECT count(*) FROM ONLY ir_act_window WHERE id = %s", [action.id]
        )
        self.assertEqual(self.env.cr.fetchone()[0], 0)
        self.env.cr.execute(
            "SELECT count(*) FROM ir_model_data WHERE model = %s AND res_id = %s",
            ["ir.actions.act_window", action.id],
        )
        self.assertEqual(
            self.env.cr.fetchone()[0], 0, "the xml id must not outlive its record"
        )

    def test_unlink_through_the_root_model_runs_subtype_guards(self):
        action = self.env["ir.actions.act_window"].create(
            {"name": "audit-root-guard", "res_model": "res.partner"}
        )
        parent = self.env["ir.actions.act_window"].create(
            {"name": "audit-root-guard-parent", "res_model": "res.partner"}
        )
        embedded = self.env["ir.embedded.actions"].create(
            {
                "parent_action_id": parent.id,
                "parent_res_model": "res.partner",
                "action_id": action.id,
            }
        )
        self.env["ir.actions.actions"].browse(action.id).unlink()
        self.assertFalse(embedded.exists())


@tagged("post_install", "-at_install")
class TestIrActionsBindingGroupsStayIds(TransactionCase):
    """_get_bindings caches group ids, never external identifiers.

    Resolving them to xml ids made a cached read *create* an ir.model.data row
    for every group that had none. That write lands in the 'groups' cache group
    while the binding lands in 'default': a request that rolls back after
    populating both leaves the identifier cached in 'default' alone, and the
    binding vanishes for every user until 'default' is cleared.
    """

    def setUp(self):
        super().setUp()
        self.group = self.env["res.groups"].create(
            {"name": "audit-binding-group", "user_ids": [(4, self.env.uid)]}
        )
        self.model_id = self.env["ir.model"]._get_id("res.currency")
        self.action = self.env["ir.actions.act_window"].create(
            {
                "name": "audit-binding-action",
                "res_model": "res.currency",
                "binding_model_id": self.model_id,
                "group_ids": [(6, 0, self.group.ids)],
            }
        )
        self.env.flush_all()
        self.env.registry.clear_cache()

    def _bound_names(self):
        bindings = self.env["ir.actions.actions"].get_bindings("res.currency")
        return {action["name"] for actions in bindings.values() for action in actions}

    def test_reading_bindings_creates_no_xml_id(self):
        self.env["ir.actions.actions"]._get_bindings("res.currency")
        self.env.cr.execute(
            "SELECT count(*) FROM ir_model_data WHERE model = 'res.groups' AND res_id = %s",
            [self.group.id],
        )
        self.assertEqual(
            self.env.cr.fetchone()[0], 0, "a cached read must not write to the database"
        )

    def test_cached_group_ids_are_ids(self):
        bindings = self.env["ir.actions.actions"]._get_bindings("res.currency")
        entries = [
            action
            for actions in bindings.values()
            for action in actions
            if action["name"] == "audit-binding-action"
        ]
        self.assertEqual([entry["group_ids"] for entry in entries], [(self.group.id,)])

    def test_member_sees_the_binding_without_an_xml_id(self):
        self.assertIn("audit-binding-action", self._bound_names())

    def test_non_member_does_not_see_the_binding(self):
        other = self.env["res.users"].create(
            {"login": "audit-binding-outsider", "name": "audit-binding-outsider"}
        )
        names = {
            action["name"]
            for actions in self.env["ir.actions.actions"]
            .with_user(other)
            .get_bindings("res.currency")
            .values()
            for action in actions
        }
        self.assertNotIn("audit-binding-action", names)

    def test_binding_survives_a_groups_only_invalidation(self):
        """The desync that used to hide the action from everyone."""
        self.assertIn("audit-binding-action", self._bound_names())
        self.env.registry.clear_cache("groups")
        self.assertIn("audit-binding-action", self._bound_names())


@tagged("post_install", "-at_install")
class TestIrActionsBindingAccess(TransactionCase):
    """get_bindings is a public RPC entry point: it must not describe the
    actions bound to a model the caller cannot read. Filtering only on each
    action's own res_model missed ir.actions.server and ir.actions.report,
    which name their model model_id/model.
    """

    def setUp(self):
        super().setUp()
        self.model_id = self.env["ir.model"]._get_id("ir.module.module")
        self.env["ir.actions.server"].create(
            {
                "name": "audit-acl-server",
                "model_id": self.model_id,
                "state": "code",
                "code": "pass",
                "binding_model_id": self.model_id,
            }
        )
        self.portal = self.env["res.users"].create(
            {
                "login": "audit-acl-portal",
                "name": "audit-acl-portal",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        self.env.flush_all()
        self.env.registry.clear_cache()

    def test_unreadable_model_yields_no_bindings(self):
        Access = self.env["ir.model.access"].with_user(self.portal)
        self.assertFalse(Access.check("ir.module.module", "read", False))
        self.assertEqual(
            self.env["ir.actions.actions"]
            .with_user(self.portal)
            .get_bindings("ir.module.module"),
            {},
        )

    def test_unknown_model_yields_no_bindings(self):
        self.assertEqual(
            self.env["ir.actions.actions"].get_bindings("no.such.model"), {}
        )

    def test_readable_model_still_yields_its_bindings(self):
        names = {
            action["name"]
            for actions in self.env["ir.actions.actions"]
            .get_bindings("ir.module.module")
            .values()
            for action in actions
        }
        self.assertIn("audit-acl-server", names)


@tagged("post_install", "-at_install")
class TestIrActionsEmbeddedInvalidation(TransactionCase):
    """embedded_action_ids is computed from a search in upstream, which gives
    the ORM no dependency to invalidate: an embedded action created in the same
    transaction stayed invisible until something else flushed the field cache.
    """

    def test_new_embedded_action_is_visible_immediately(self):
        parent = self.env["ir.actions.act_window"].create(
            {"name": "audit-embedded-invalidation", "res_model": "res.partner"}
        )
        partner = self.env["res.partner"].create({"name": "audit-embedded-partner"})
        scoped = parent.with_context(active_id=partner.id, active_model="res.partner")
        self.assertFalse(scoped.embedded_action_ids)

        embedded = self.env["ir.embedded.actions"].create(
            {
                "name": "audit-embedded-new",
                "parent_action_id": parent.id,
                "parent_res_model": "res.partner",
                "python_method": "action_archive",
            }
        )
        self.assertEqual(scoped.embedded_action_ids, embedded)


@tagged("post_install", "-at_install")
class TestIrActionsViewModeVocabulary(TransactionCase):
    """ir.actions.act_window.view.view_mode duplicates ir.ui.view.type: every
    module adding a view type must extend both. The two cannot be derived from
    one another (selection_add needs a list-valued base, and only that form
    carries the ondelete policies that clean up act_window lines on uninstall),
    so the invariant is asserted instead.
    """

    def test_view_mode_is_view_type_minus_the_non_window_ones(self):
        from odoo.addons.base.models.ir_actions import NON_WINDOW_VIEW_TYPES

        view_modes = set(
            self.env["ir.actions.act_window.view"]
            ._fields["view_mode"]
            .get_values(self.env)
        )
        view_types = set(self.env["ir.ui.view"]._fields["type"].get_values(self.env))
        self.assertEqual(
            view_types - view_modes,
            set(NON_WINDOW_VIEW_TYPES),
            "a view type was added to ir.ui.view without extending view_mode",
        )
        self.assertFalse(
            view_modes - view_types,
            "view_mode offers a mode that is not an ir.ui.view type",
        )


@tagged("post_install", "-at_install")
class TestIrActionsTodoLaunchContext(TransactionCase):
    """action_launch evaluated the action context with only ``user`` in scope,
    so anything referencing uid/active_id/time silently degraded the whole
    context to {'disable_log': True} instead of just failing that key.
    """

    def test_launch_keeps_a_context_referencing_the_eval_context(self):
        action = self.env["ir.actions.act_window"].create(
            {
                "name": "audit-todo-ctx",
                "res_model": "res.partner",
                "context": "{'default_user_id': uid, 'search_default_x': 1}",
            }
        )
        todo = self.env["ir.actions.todo"].create({"action_id": action.id})
        context = todo.action_launch()["context"]
        self.assertEqual(
            context,
            {
                "default_user_id": self.env.uid,
                "search_default_x": 1,
                "disable_log": True,
            },
        )


@tagged("post_install", "-at_install")
class TestIrActionsTableInheritanceRoot(TransactionCase):
    """ir.actions.actions declares that it owns the table its subtypes inherit.

    Relational fields consult that declaration to skip the foreign key
    PostgreSQL would accept but never honour. It used to be a table name
    hard-coded in odoo/orm/fields/relational/many2one.py, which the many2many
    equivalent did not have at all.
    """

    def test_the_root_declares_itself(self):
        self.assertTrue(
            self.env["ir.actions.actions"]._is_table_inheritance_root(),
            "without the declaration the ORM creates foreign keys to ir_actions "
            "that reject every id living in a subtype table",
        )

    def test_subtypes_are_ordinary_tables(self):
        for name in ("ir.actions.act_window", "ir.actions.server", "ir.actions.report"):
            with self.subTest(model=name):
                self.assertFalse(self.env[name]._is_table_inheritance_root())

    def test_a_foreign_key_to_the_root_would_reject_a_subtype_row(self):
        """Why the declaration exists, asserted against PostgreSQL itself."""
        self.env.cr.execute("SELECT id FROM ir_act_window LIMIT 1")
        [act_window_id] = self.env.cr.fetchone()
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self.env.cr.execute("CREATE TABLE audit_root_fk (act_id integer)")
                self.env.cr.execute(
                    "ALTER TABLE audit_root_fk ADD CONSTRAINT audit_root_fk_con "
                    "FOREIGN KEY (act_id) REFERENCES ir_actions(id)"
                )
                self.env.cr.execute(
                    "INSERT INTO audit_root_fk VALUES (%s)", [act_window_id]
                )

    def test_many2many_relations_to_the_root_are_swept_on_unlink(self):
        """No such field exists today; the sweep must be ready if one appears."""
        Actions = self.env["ir.actions.actions"]
        declared = {
            (field.relation, field.column2)
            for model in self.env.registry.values()
            if not model._abstract
            for field in model._fields.values()
            if field.type == "many2many"
            and field.store
            and field.comodel_name in Actions._root_model_names()
        }
        self.assertEqual(set(Actions._unenforced_reference_relations()), declared)
