from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.tests import tagged

from .common import ApprovalCommon

DECLINED = (AccessError, UserError, ValidationError)

# Each script is a list of (action, state, who could approve, who holds an
# approval activity), read after the action. The first action is None: the
# request as confirmed.
SCRIPTS = {
    "any_one_of_two": [
        (None, "pending", {"a", "b"}, {"a", "b"}),
        (("approve", "b"), "approved", set(), set()),
    ],
    "two_of_two": [
        (None, "pending", {"a", "b"}, {"a", "b"}),
        (("approve", "a"), "pending", {"b"}, {"b"}),
        (("approve", "b"), "approved", set(), set()),
    ],
    "required_beside_optional": [
        (None, "pending", {"a", "b"}, {"a", "b"}),
        (("approve", "b"), "pending", {"a"}, {"a"}),
        (("approve", "a"), "approved", set(), set()),
    ],
    "sequential": [
        (None, "pending", {"a"}, {"a"}),
        (("approve", "a"), "pending", {"b"}, {"b"}),
        (("approve", "b"), "approved", set(), set()),
    ],
    "sequential_quorum_of_one": [
        (None, "pending", {"a"}, {"a"}),
        (("approve", "a"), "approved", set(), set()),
    ],
    # What the closest step form (one step per approver, notify_sequentially)
    # does instead. Steps order who is ASKED, not who
    # may DECIDE: the later step's member can approve before the first one is
    # met. And one step per approver needs every one of them, so a quorum of one
    # does not end the chain.
    "sequential_as_steps": [
        (None, "pending", {"a", "b"}, {"a"}),
        (("approve", "a"), "pending", {"b"}, {"b"}),
        (("approve", "b"), "approved", set(), set()),
    ],
    "one_refusal": [
        (None, "pending", {"a", "b"}, {"a", "b"}),
        (("refuse", "a"), "refused", set(), set()),
    ],
    "withdrawal": [
        (None, "pending", {"a", "b"}, {"a", "b"}),
        (("approve", "a"), "pending", {"b"}, {"b"}),
        (("withdraw", "a"), "pending", {"a", "b"}, {"a", "b"}),
    ],
    "group_queue": [
        (None, "pending", {"c", "d"}, set()),
        (("approve", "d"), "approved", set(), set()),
    ],
    "group_two_members": [
        (None, "pending", {"c", "d"}, set()),
        (("approve", "c"), "pending", {"d"}, set()),
        (("approve", "d"), "approved", set(), set()),
    ],
    "owner_not_asked": [
        (None, "pending", {"a"}, {"a"}),
        (("approve", "a"), "approved", set(), set()),
    ],
    "rule_adds_a_required_approver": [
        (None, "pending", {"a", "c"}, {"a", "c"}),
        (("approve", "a"), "pending", {"c"}, {"c"}),
        (("approve", "c"), "approved", set(), set()),
    ],
    "rule_below_its_threshold": [
        (None, "pending", {"a"}, {"a"}),
        (("approve", "a"), "approved", set(), set()),
    ],
    "band_replaces_the_approvers": [
        (None, "pending", {"b"}, {"b"}),
        (("approve", "b"), "approved", set(), set()),
    ],
    "delegated_approver": [
        (None, "pending", {"b", "d"}, {"b", "d"}),
        (("approve", "d"), "approved", set(), set()),
    ],
    "owner_allowed": [
        (None, "pending", {"owner", "a"}, {"owner", "a"}),
        (("approve", "owner"), "approved", set(), set()),
    ],
}


class _Probe(Exception):
    pass


class RoutingOutcomesCase(ApprovalCommon):
    """What a category's routing does, stated in terms no implementation owns.

    After every decision a script records the request's state, who could approve it
    at that moment (tried inside a savepoint that is rolled back), and who holds an
    approval activity. The flat approver list and the step model are each given the
    same scripts; a merge of the two is held to both classes.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_approver = cls.env.ref("approval.group_approval_approver")
        cls.people = {"owner": cls.owner_user}
        for key in ("a", "b", "c", "d"):
            cls.people[key] = cls.env["res.users"].create(
                {
                    "name": f"Routing {key.upper()}",
                    "login": f"routing_outcome_{key}",
                    "email": f"routing_{key}@test.com",
                    "group_ids": [(4, group_approver.id)],
                }
            )
        cls.pool = cls.env["res.groups"].create(
            {
                "name": "Routing Pool",
                "user_ids": [(6, 0, [cls.people["c"].id, cls.people["d"].id])],
            }
        )

    def _decidable(self, request):
        keys = set()
        for key, user in self.people.items():
            try:
                with self.env.cr.savepoint():
                    request.with_user(user).action_approve()
                    raise _Probe
            except _Probe:
                keys.add(key)
            except DECLINED:
                pass
        return keys

    def _notified(self, request):
        activity_users = request._get_approval_activities().user_id
        return {key for key, user in self.people.items() if user in activity_users}

    def _act(self, request, verb, key):
        actor = request.with_user(self.people[key])
        if verb == "approve":
            actor.action_approve()
        elif verb == "refuse":
            actor.with_context(skip_wizard=True).action_refuse()
        elif verb == "withdraw":
            actor.action_withdraw()
        request.invalidate_recordset()

    def _run(self, category, script_name, request_vals=None, after_confirm=None):
        request = self._prepare_request(category, **(request_vals or {}))
        if after_confirm:
            after_confirm(request)
            request.invalidate_recordset()
        for index, (action, state, decidable, notified) in enumerate(
            SCRIPTS[script_name]
        ):
            if action:
                self._act(request, *action)
            with self.subTest(step=index, action=action):
                self.assertEqual(request.state, state)
                self.assertEqual(self._decidable(request), decidable)
                self.assertEqual(self._notified(request), notified)


@tagged("post_install", "-at_install")
class TestFlatRoutingOutcomes(RoutingOutcomesCase):
    def _flat(self, approvers, **vals):
        category = self._make_category(
            "Flat routing",
            approvers=[
                (self.people[key], required, sequence)
                for key, required, sequence in approvers
            ],
            **vals,
        )
        if "approval_minimum" in vals:
            category.approval_minimum = vals["approval_minimum"]
        return category

    def test_any_one_of_two(self):
        self._run(
            self._flat([("a", False, 10), ("b", False, 20)], approval_minimum=1),
            "any_one_of_two",
        )

    def test_two_of_two(self):
        self._run(
            self._flat([("a", False, 10), ("b", False, 20)], approval_minimum=2),
            "two_of_two",
        )

    def test_required_beside_optional(self):
        self._run(
            self._flat([("a", True, 10), ("b", False, 20)], approval_minimum=1),
            "required_beside_optional",
        )

    def test_sequential(self):
        self._run(
            self._flat(
                [("a", True, 10), ("b", True, 20)],
                approval_minimum=2,
                approve_sequentially=True,
            ),
            "sequential",
        )

    def test_sequential_quorum_of_one(self):
        self._run(
            self._flat(
                [("a", False, 10), ("b", False, 20)],
                approval_minimum=1,
                approve_sequentially=True,
            ),
            "sequential_quorum_of_one",
        )

    def test_one_refusal(self):
        self._run(
            self._flat([("a", False, 10), ("b", False, 20)], approval_minimum=1),
            "one_refusal",
        )

    def test_withdrawal(self):
        self._run(
            self._flat([("a", False, 10), ("b", False, 20)], approval_minimum=2),
            "withdrawal",
        )

    def test_group_queue(self):
        self._run(
            self._flat(
                [("a", True, 10)],
                approval_minimum=1,
                group_approval="exclusive",
                approver_group_id=self.pool.id,
            ),
            "group_queue",
        )

    def test_group_two_members(self):
        self._run(
            self._flat(
                [],
                approval_minimum=2,
                group_approval="exclusive",
                approver_group_id=self.pool.id,
            ),
            "group_two_members",
        )

    def test_owner_not_asked(self):
        self._run(
            self._flat([("owner", False, 10), ("a", False, 20)], approval_minimum=1),
            "owner_not_asked",
        )

    def test_owner_allowed(self):
        self._run(
            self._flat(
                [("owner", False, 10), ("a", False, 20)],
                approval_minimum=1,
                allow_self_approval=True,
            ),
            "owner_allowed",
        )

    def _amount_category(self, action_type, rule_users, **rule_vals):
        category = self._flat(
            [("a", False, 10)], approval_minimum=1, has_amount="required"
        )
        self.env["approval.rule"].create(
            {
                "name": "Routing rule",
                "category_id": category.id,
                "condition_type": "threshold",
                "condition_field": "amount",
                "action_type": action_type,
                "approver_ids": [(6, 0, [self.people[k].id for k in rule_users])],
                **rule_vals,
            }
        )
        return category

    def test_rule_adds_a_required_approver(self):
        category = self._amount_category(
            "add_approver", ["c"], operator="gte", threshold=1000
        )
        self._run(
            category, "rule_adds_a_required_approver", request_vals={"amount": 5000}
        )

    def test_rule_below_its_threshold(self):
        category = self._amount_category(
            "add_approver", ["c"], operator="gte", threshold=1000
        )
        self._run(category, "rule_below_its_threshold", request_vals={"amount": 10})

    def test_band_replaces_the_approvers(self):
        category = self._amount_category(
            "set_approvers",
            ["b"],
            operator="between",
            threshold=1000,
            threshold_max=0,
            approval_minimum=1,
        )
        self._run(
            category, "band_replaces_the_approvers", request_vals={"amount": 5000}
        )

    def test_delegated_approver(self):
        category = self._flat([("a", False, 10), ("b", False, 20)], approval_minimum=1)

        def delegate_a_to_d(request):
            row = request.approver_ids.filtered(
                lambda approver: approver.user_id == self.people["a"]
            )
            self._delegate_row(row, self.people["d"])

        self._run(category, "delegated_approver", after_confirm=delegate_a_to_d)


@tagged("post_install", "-at_install")
class TestStepRoutingOutcomes(RoutingOutcomesCase):
    """The same scripts on categories built from steps, the flat list left empty."""

    def _stepped(self, steps, **vals):
        category = self._make_category("Step routing", **vals)
        for index, (keys, minimum, step_vals) in enumerate(steps):
            self.env["approval.category.step"].create(
                {
                    "category_id": category.id,
                    "name": f"Step {index}",
                    "sequence": step_vals.pop("sequence", 10 * (index + 1)),
                    "minimum": minimum,
                    "member_ids": [
                        Command.create({"user_id": self.people[key].id}) for key in keys
                    ],
                    **step_vals,
                }
            )
        return category

    def test_any_one_of_two(self):
        self._run(self._stepped([(("a", "b"), 1, {})]), "any_one_of_two")

    def test_two_of_two(self):
        self._run(self._stepped([(("a", "b"), 2, {})]), "two_of_two")

    def test_required_beside_optional(self):
        # A required approver is a step of their own, open beside the pool.
        self._run(
            self._stepped(
                [(("a",), 1, {"sequence": 10}), (("a", "b"), 1, {"sequence": 10})]
            ),
            "required_beside_optional",
        )

    def test_sequential_has_no_step_form(self):
        # The flat "sequential" and "sequential_quorum_of_one" scripts have no step
        # form yet: steps notify in order but let any member decide early, and a
        # quorum smaller than the chain cannot end it. One routing model needs a
        # step that is decided in order, and a quorum across ordered members,
        # before this reads as the flat scripts do.
        self._run(
            self._stepped([(("a",), 1, {}), (("b",), 1, {})], notify_sequentially=True),
            "sequential_as_steps",
        )

    def test_one_refusal(self):
        self._run(self._stepped([(("a", "b"), 1, {})]), "one_refusal")

    def test_withdrawal(self):
        self._run(self._stepped([(("a", "b"), 2, {})]), "withdrawal")

    def test_group_queue(self):
        self._run(self._stepped([((), 1, {"group_id": self.pool.id})]), "group_queue")

    def test_group_two_members(self):
        self._run(
            self._stepped([((), 2, {"group_id": self.pool.id})]),
            "group_two_members",
        )

    def test_owner_not_asked(self):
        self._run(self._stepped([(("owner", "a"), 1, {})]), "owner_not_asked")

    def test_owner_allowed(self):
        self._run(
            self._stepped([(("owner", "a"), 1, {})], allow_self_approval=True),
            "owner_allowed",
        )

    def _amount_steps(self, steps):
        return self._stepped(steps, has_amount="required")

    def test_rule_adds_a_required_approver(self):
        # The rule's approver is a step of its own, applicable above the threshold.
        category = self._amount_steps(
            [
                (("a",), 1, {"sequence": 10}),
                (
                    ("c",),
                    1,
                    {
                        "sequence": 10,
                        "condition_field": "amount",
                        "operator": "gte",
                        "threshold": 1000,
                    },
                ),
            ]
        )
        self._run(
            category, "rule_adds_a_required_approver", request_vals={"amount": 5000}
        )

    def test_rule_below_its_threshold(self):
        category = self._amount_steps(
            [
                (("a",), 1, {"sequence": 10}),
                (
                    ("c",),
                    1,
                    {
                        "sequence": 10,
                        "condition_field": "amount",
                        "operator": "gte",
                        "threshold": 1000,
                    },
                ),
            ]
        )
        self._run(category, "rule_below_its_threshold", request_vals={"amount": 10})

    def test_band_replaces_the_approvers(self):
        # Each band is a step applicable over its own range.
        category = self._amount_steps(
            [
                (
                    ("a",),
                    1,
                    {"condition_field": "amount", "operator": "lt", "threshold": 1000},
                ),
                (
                    ("b",),
                    1,
                    {
                        "condition_field": "amount",
                        "operator": "between",
                        "threshold": 1000,
                        "threshold_max": 0,
                    },
                ),
            ]
        )
        self._run(
            category, "band_replaces_the_approvers", request_vals={"amount": 5000}
        )

    def test_a_figure_condition_needs_a_comparison(self):
        with self.assertRaises(ValidationError):
            self._amount_steps([(("a",), 1, {"condition_field": "amount"})])
