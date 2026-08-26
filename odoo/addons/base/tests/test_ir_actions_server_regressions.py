import inspect
from unittest.mock import patch

import requests

from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.base.models.ir_actions_server import _get_webhook_blocked_reason

_MODULE = "odoo.addons.base.models.ir_actions_server"


class ServerActionCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env["ir.model"]._get("res.partner")
        cls.Action = cls.env["ir.actions.server"]

    def _action(self, **vals):
        return self.Action.create(
            {"model_id": self.partner_model.id, "name": "act", **vals}
        )

    def _partners(self, n, prefix="p"):
        return self.env["res.partner"].create(
            [{"name": f"{prefix}{i}"} for i in range(n)]
        )

    def _ctx(self, records):
        return {
            "active_model": "res.partner",
            "active_ids": records.ids,
            "active_id": records[:1].id,
        }


@tagged("post_install", "-at_install")
class TestNameIsNeverNull(ServerActionCase):
    """`name` is required and computed, and stored computes run after the INSERT.

    Both an omitted and a falsy name reached Postgres as NULL and died with a raw
    `NotNullViolation`. `precompute=True` cannot fix it -- the ORM disables it
    because `_compute_names` depends on `crud_model_id`, itself a non-precomputed
    stored compute -- so `create` derives the name instead.
    """

    def test_an_omitted_name_is_derived_from_the_type(self):
        action = self.Action.create(
            {"model_id": self.partner_model.id, "state": "code", "code": "pass"}
        )
        self.env.flush_all()
        self.assertEqual(action.name, "Execute Code")

    def test_a_falsy_name_is_derived_too(self):
        for blank in (False, ""):
            with self.subTest(blank=blank):
                action = self.Action.create(
                    {
                        "name": blank,
                        "model_id": self.partner_model.id,
                        "state": "code",
                        "code": "pass",
                    }
                )
                self.env.flush_all()
                self.assertEqual(action.name, "Execute Code")

    def test_a_typed_name_survives_a_type_change(self):
        """Even when it happens to equal the label the type would have produced."""
        action = self._action(name="Execute Code", state="code", code="pass")
        self.env.flush_all()
        action.write({"state": "object_create", "value": "x"})
        self.env.flush_all()
        self.assertEqual(
            action.name,
            "Execute Code",
            "a name the user typed is theirs, whatever it happens to say",
        )

    def test_a_derived_name_follows_the_type(self):
        action = self.Action.create(
            {"model_id": self.partner_model.id, "state": "code", "code": "pass"}
        )
        self.env.flush_all()
        action.write({"state": "object_create", "value": "x"})
        self.env.flush_all()
        self.assertEqual(action.name, "Create Contact")


@tagged("post_install", "-at_install")
class TestObjectCopyDuplicatesTheRecordItNames(ServerActionCase):
    """The id came from `resource_ref` and the model from `crud_model_id`.

    Nothing kept the two in step -- not a `Form`, not `load()`, not a plain
    `write` -- so an action set to duplicate a country duplicated whichever
    record of the action's own model happened to share that id.
    """

    def test_it_copies_the_referenced_record_not_its_own_model(self):
        shared = sorted(
            set(self.env["res.partner"].search([]).ids)
            & set(self.env["res.country"].search([]).ids)
        )
        self.assertTrue(shared, "precondition: an id naming a record in both models")
        partner = self.env["res.partner"].browse(shared[0])
        country_model = self.env["ir.model"]._get("res.country")

        action = self.Action.create(
            {"name": "dup", "model_id": country_model.id, "state": "object_copy"}
        )
        action.write({"resource_ref": f"res.partner,{partner.id}"})
        self.assertEqual(
            action.crud_model_id.model,
            "res.country",
            "the action's own model, which is not the reference's",
        )

        countries_before = self.env["res.country"].search([]).ids
        partners_before = self.env["res.partner"].search([]).ids
        action.with_context(
            active_model="res.country",
            active_id=shared[0],
            active_ids=[shared[0]],
        ).run()
        self.env.flush_all()

        self.assertFalse(
            self.env["res.country"].search([("id", "not in", countries_before)]),
            "nothing of the action's own model was touched",
        )
        new = self.env["res.partner"].search([("id", "not in", partners_before)])
        self.assertEqual(len(new), 1, "the referenced partner was duplicated")
        self.assertEqual(new.name, f"{partner.name} (copy)")


@tagged("post_install", "-at_install")
class TestUpdatePathIsHonouredOnEveryPath(ServerActionCase):
    """The on-change branch used only the path's LEAF field name.

    `record_cached` is the ROOT record, so `parent_id.ref` wrote `ref` on the
    record being edited -- silent corruption when the leaf name also exists on
    the root, a bare `KeyError` when it does not.
    """

    def test_the_normal_path_writes_the_record_the_path_names(self):
        parent = self.env["res.partner"].create({"name": "PARENT"})
        child = self.env["res.partner"].create(
            {"name": "CHILD", "parent_id": parent.id}
        )
        action = self._action(
            state="object_write",
            update_path="parent_id.ref",
            evaluation_type="value",
            value="LEAF",
        )
        action.with_context(**self._ctx(child)).run()
        self.env.flush_all()
        self.assertEqual(parent.ref, "LEAF")
        self.assertFalse(child.ref, "the root record is not the target")

    def test_an_on_change_refuses_a_path_that_leaves_the_record(self):
        partner = self.env["res.partner"].create({"name": "root"})
        action = self._action(
            state="object_write",
            update_path="parent_id.ref",
            evaluation_type="value",
            value="LEAF",
        )
        with self.assertRaises(UserError):
            action.with_context(
                onchange_self=partner.new(origin=partner),
                active_model="res.partner",
                active_id=partner.id,
            ).run()

    def test_an_on_change_still_writes_a_single_segment_path(self):
        partner = self.env["res.partner"].create({"name": "root"})
        cached = partner.new(origin=partner)
        action = self._action(
            state="object_write",
            update_path="function",
            evaluation_type="value",
            value="Set By Action",
        )
        action.with_context(
            onchange_self=cached, active_model="res.partner", active_id=partner.id
        ).run()
        self.assertEqual(cached.function, "Set By Action")
        self.assertFalse(partner.function, "an on-change writes the cache only")


@tagged("post_install", "-at_install")
class TestConfigurationSurvivesAStateChange(ServerActionCase):
    """`_compute_crud_relations` assigned `update_path` -- a field it does not
    compute, and one of its own dependencies. Switching the type and switching
    back left `value` in place and the path gone, and the path is invisible
    unless the state is `object_write`, so the loss was never on screen."""

    def test_update_path_round_trips_through_another_state(self):
        action = self._action(
            state="object_write", update_path="ref", evaluation_type="value", value="V"
        )
        self.env.flush_all()
        action.write({"state": "code", "code": "pass"})
        self.env.flush_all()
        self.assertFalse(action.update_field_id, "the derived field is cleared")
        action.write({"state": "object_write"})
        self.env.flush_all()
        self.assertEqual(action.update_path, "ref")
        self.assertEqual(action.update_field_id.name, "ref")
        self.assertEqual(action.value, "V")

    def test_a_chosen_crud_model_is_seeded_not_imposed(self):
        users_model = self.env["ir.model"]._get("res.users")
        action = self._action(state="object_create", value="n")
        self.assertEqual(
            action.crud_model_id, self.partner_model, "seeded from the action's model"
        )
        action.write({"crud_model_id": users_model.id})
        self.env.flush_all()
        action.write({"state": "object_create"})
        self.env.flush_all()
        self.assertEqual(
            action.crud_model_id, users_model, "a value the user chose is kept"
        )


@tagged("post_install", "-at_install")
class TestBatchingIsDeliveredNotJustPromised(ServerActionCase):
    """`_is_batchable()` said a `multi` took the whole batch while
    `_resolve_runner` classified it non-batch: there is no
    `_run_action_multi_multi`, so `_run` looped per record and threw the batch
    away one level down. Registering the batch runner unconditionally is worse
    -- a `code` child then runs once for the whole batch instead of once each."""

    def _multi_over(self, children):
        return self._action(
            name="P", state="multi", child_ids=[Command.set(children.ids)]
        )

    def test_a_multi_over_a_code_child_still_runs_it_once_per_record(self):
        child = self._action(
            name="C",
            state="code",
            code="record.write({'ref': (record.ref or '') + 'x'})",
        )
        parent = self._multi_over(child)
        self.assertFalse(parent._is_batchable())
        records = self._partners(5, "batch")
        parent.with_context(**self._ctx(records)).run()
        self.env.flush_all()
        self.assertEqual(records.mapped("ref"), ["x"] * 5, "every record got a run")

    def test_a_multi_over_a_batchable_child_hands_it_the_whole_batch(self):
        child = self._action(
            name="C",
            state="object_write",
            update_path="ref",
            evaluation_type="value",
            value="B",
        )
        parent = self._multi_over(child)
        self.assertTrue(parent._is_batchable())
        records = self._partners(5, "whole")

        seen = []
        cls = type(self.env["ir.actions.server"])
        origin = cls._run_action_object_write_multi

        def spy(action, eval_context=None):
            seen.append(len(action._get_target_records()))
            return origin(action, eval_context=eval_context)

        self.patch(cls, "_run_action_object_write_multi", spy)
        parent.with_context(**self._ctx(records)).run()
        self.env.flush_all()
        self.assertEqual(seen, [5], "one call carrying the whole batch")
        self.assertEqual(records.mapped("ref"), ["B"] * 5)

    def test_an_empty_multi_batches_nothing(self):
        self.assertFalse(
            self._multi_over(self.Action.browse())._is_batchable(),
            "all() over no children is vacuously true, which is not an answer",
        )


@tagged("post_install", "-at_install")
class TestObjectWriteCostsNothingPerExtraRecord(ServerActionCase):
    """`_run`'s per-record loop browsed singletons, which have nothing to
    prefetch with: two queries per target record, while the ORM's flush was
    already batching the UPDATE itself. N=2 against N=20 so cache warmth cannot
    make the assertion vacuous."""

    def _cost(self, action, n):
        records = self._partners(n, f"cost{n}_")
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        action.with_context(**self._ctx(records)).run()
        self.env.flush_all()
        return self.env.cr.sql_log_count - before

    def test_a_static_update_costs_the_same_for_two_records_and_twenty(self):
        action = self._action(
            state="object_write", update_path="ref", evaluation_type="value", value="B"
        )
        small, large = self._cost(action, 2), self._cost(action, 20)
        self.assertLessEqual(
            large - small,
            2,
            f"18 further records must be nearly free; measured {small} -> {large}",
        )

    def test_a_sequence_still_gets_one_number_per_record(self):
        """Batching must not collapse a per-record value into a shared one."""
        sequence = self.env["ir.sequence"].create(
            {"name": "Seq", "prefix": "S-", "padding": 3}
        )
        action = self._action(
            state="object_write",
            update_path="ref",
            evaluation_type="sequence",
            sequence_id=sequence.id,
        )
        self.assertFalse(action._is_batch_safe())
        records = self._partners(3, "seq")
        action.with_context(**self._ctx(records)).run()
        self.env.flush_all()
        self.assertEqual(
            len(set(records.mapped("ref"))), 3, "three records, three numbers"
        )

    def test_an_equation_is_evaluated_against_each_record(self):
        action = self._action(
            state="object_write",
            update_path="ref",
            evaluation_type="equation",
            value="record.name",
        )
        self.assertFalse(action._is_batch_safe())
        records = self._partners(3, "eq")
        action.with_context(**self._ctx(records)).run()
        self.env.flush_all()
        self.assertEqual(records.mapped("ref"), records.mapped("name"))


@tagged("post_install", "-at_install")
class TestWebhookGuardHoldsAtSendTime(ServerActionCase):
    def _webhook(self, **vals):
        return self._action(
            state="webhook", webhook_url="https://example.com/hook", **vals
        )

    def test_an_unresolvable_host_is_blocked_not_allowed(self):
        self.assertIsNotNone(
            _get_webhook_blocked_reason("http://nx.invalid/hook"),
            "an address the guard cannot judge is not one it may allow",
        )

    def test_a_public_host_is_still_allowed(self):
        self.assertIsNone(_get_webhook_blocked_reason("https://1.1.1.1/hook"))

    def test_multicast_and_reserved_are_still_blocked(self):
        """`not is_global` does not cover these; the trimmed chain must."""
        for host in ("224.0.0.1", "[ff02::1]", "[64:ff9b::1.2.3.4]"):
            with self.subTest(host=host):
                self.assertIsNotNone(_get_webhook_blocked_reason(f"http://{host}/h"))

    def test_the_request_does_not_follow_redirects(self):
        """A permitted host answering 307 would otherwise hand the record to
        whatever the guard exists to keep it away from."""
        action = self._webhook()
        with patch.object(requests, "post") as post:
            action.with_context(**self._ctx(self._partners(1))).run()
            self.env.cr.postcommit.run()
        self.assertIs(post.call_args.kwargs["allow_redirects"], False)

    @mute_logger(_MODULE)
    def test_the_guard_runs_again_at_delivery(self):
        """The check happens when the action runs, the POST after the commit."""
        action = self._webhook()
        with (
            patch.object(requests, "post") as post,
            patch(
                f"{_MODULE}._get_webhook_blocked_reason", side_effect=[None, "moved"]
            ),
        ):
            action.with_context(**self._ctx(self._partners(1))).run()
            self.env.cr.postcommit.run()
        post.assert_not_called()

    def test_the_timeout_is_re_checked_when_the_state_becomes_webhook(self):
        action = self._action(state="code", code="pass", webhook_timeout=0)
        with self.assertRaises(ValidationError):
            action.write({"state": "webhook", "webhook_url": "https://e.com/hook"})


@tagged("post_install", "-at_install")
class TestWebhookPayloadHasOneShape(ServerActionCase):
    """The send and the sample built the same dict in two places with two
    serialisers, and the bare `id` beside the documented `_id` appeared only
    when a field happened to be selected."""

    def _sample_record(self):
        return (
            self.env["res.partner"].with_context(active_test=False).search([], limit=1)
        )

    def test_the_sample_is_what_would_be_sent(self):
        field = self.env["ir.model.fields"]._get("res.partner", "name")
        action = self._action(
            state="webhook",
            webhook_url="https://example.com/hook",
            webhook_field_ids=[Command.set(field.ids)],
        )
        record = self._sample_record()
        sent = {}

        def fake_post(url, **kwargs):
            sent.update(kwargs)
            response = requests.Response()
            response.status_code = 200
            return response

        with patch.object(requests, "post", fake_post):
            action.with_context(active_model="res.partner", active_id=record.id).run()
            self.env.cr.postcommit.run()
        self.assertEqual(
            action._dump_webhook_payload(action._get_webhook_payload(record)),
            sent["data"],
        )

    def test_the_shape_does_not_depend_on_the_field_selection(self):
        field = self.env["ir.model.fields"]._get("res.partner", "name")
        record = self._sample_record()
        bare = self._action(state="webhook", webhook_url="https://e.com/h")
        chosen = self._action(
            state="webhook",
            webhook_url="https://e.com/h",
            webhook_field_ids=[Command.set(field.ids)],
        )
        framing = {"_action", "_id", "_model", "id"}
        self.assertEqual(set(bare._get_webhook_payload(record)), framing)
        self.assertEqual(
            set(chosen._get_webhook_payload(record)) - {"name"},
            framing,
            "the framing keys are there whether or not a field is chosen",
        )


@tagged("post_install", "-at_install")
class TestOneRecordResolution(ServerActionCase):
    """`_get_target_records` trusted `active_ids` with no `active_model` while
    `_get_eval_context` refused them. One of the two had to be wrong."""

    def test_ids_without_a_model_name_no_records(self):
        partners = self._partners(2, "amb")
        action = self._action(state="code", code="pass")
        self.assertFalse(
            action.with_context(active_ids=partners.ids).sudo()._get_target_records(),
            "ids that do not say which model they belong to name nothing",
        )

    def test_the_eval_context_and_the_runners_see_the_same_records(self):
        partners = self._partners(3, "same")
        action = self._action(
            state="code", code="action = {'n': len(records), 'r': record.id}"
        )
        scoped = action.with_context(**self._ctx(partners))
        eval_context = scoped._get_eval_context(scoped)
        self.assertEqual(eval_context["records"], scoped.sudo()._get_target_records())
        self.assertEqual(eval_context["record"], partners[:1])
        self.assertEqual(scoped.run(), {"n": 3, "r": partners[0].id})


@tagged("post_install", "-at_install")
class TestTheOverridesStayInTheirChain(ServerActionCase):
    def test_the_readable_fields_override_is_reached(self):
        """It was named `_get_readable_fields` while the caller had moved on to
        `_get_fields_readable`, so the action dict silently lost two keys."""
        action = self._action(state="code", code="pass")
        self.assertLessEqual(
            {"group_ids", "model_name"}, set(action._get_action_dict())
        )

    def test_every_eval_context_override_requires_its_action(self):
        parameter = inspect.signature(type(self.Action)._get_eval_context).parameters[
            "action"
        ]
        self.assertIs(
            parameter.default,
            inspect.Parameter.empty,
            "the registry class, not just the base one, must require the action",
        )
