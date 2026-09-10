from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import common, tagged


@tagged("post_install", "-at_install")
class TestApprovalStudioParity(common.TransactionCase):
    """What a Studio approval rule did, held by the steps and bindings that replace it.

    Each test names the Studio test whose behaviour it keeps.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Binding = cls.env["approval.binding"]
        cls.Step = cls.env["approval.category.step"]
        cls.Request = cls.env["approval.request"]
        cls.plain = cls._user("parity_plain")
        cls.member = cls._user("parity_member")
        cls.manager = cls._user("parity_manager", "base.group_system")
        cls.partner = cls.env["res.partner"].create({"name": "Parity Partner"})

    @classmethod
    def _user(cls, login, *groups):
        return cls.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "email": f"{login}@test.com",
                "group_ids": [
                    Command.link(cls.env.ref(xmlid).id)
                    for xmlid in (
                        "base.group_user",
                        "base.group_partner_manager",
                        *groups,
                    )
                ],
            }
        )

    def tearDown(self):
        self.Binding._unregister_hook()
        super().tearDown()

    def _member_step(self, method, **vals):
        step = self.Step.browse(
            self.Binding.create_step_for_button("res.partner", method, False)
        )
        step.write(
            {"group_id": False, "user_ids": [Command.set(self.member.ids)], **vals}
        )
        return step

    def _request(self, *steps_vals):
        category = self.env["approval.category"].create({"name": "Parity Category"})
        steps = self.Step.create(
            [{"category_id": category.id, **vals} for vals in steps_vals]
        )
        request = self.Request.create(
            {
                "name": "Parity",
                "category_id": category.id,
                "request_owner_id": self.plain.id,
                "res_model": "res.partner",
                "res_id": self.partner.id,
            }
        )
        request.action_confirm()
        return request, steps

    def test_a_record_no_step_applies_to_is_not_gated(self):
        """test_03_single_rule_with_domain."""
        self._member_step(
            "action_archive", subject_domain="[('is_company', '=', True)]"
        )
        person = self.env["res.partner"].create({"name": "A person"})
        person.with_user(self.plain).action_archive()
        self.assertFalse(person.active, "no step applies, so nothing is asked")
        company = self.env["res.partner"].create(
            {"name": "A company", "is_company": True}
        )
        company.with_user(self.plain).action_archive()
        self.assertTrue(
            company.active, "the step applies to a company, so the call waits"
        )

    def test_an_exclusive_approval_counts_toward_the_exclusive_step_first(self):
        """test_05_different_users."""
        request, (_base, strict) = self._request(
            {
                "name": "Base",
                "sequence": 1,
                "group_id": self.env.ref("base.group_user").id,
            },
            {
                "name": "Strict",
                "sequence": 1,
                "group_id": self.env.ref("base.group_system").id,
                "exclusive": True,
            },
        )
        request.with_user(self.manager).action_approve()
        self.assertEqual(request._get_step_counts()[strict.id], 1)
        self.assertEqual(request.state, "pending")
        request.with_user(self.plain).action_approve()
        self.assertEqual(request.state, "approved")

    def test_an_archived_step_is_ignored_whatever_the_context(self):
        """test_08_archive and test_09_archive_reverse."""
        request, (_first, second) = self._request(
            {
                "name": "First",
                "sequence": 1,
                "user_ids": [Command.set(self.member.ids)],
            },
            {
                "name": "Second",
                "sequence": 2,
                "user_ids": [Command.set(self.plain.ids)],
            },
        )
        request.with_user(self.member).action_approve()
        self.assertEqual(request.state, "pending")
        second.active = False
        self.assertEqual(request.state, "approved")
        self.assertFalse(request.with_context(active_test=False)._get_unmet_steps())

    def test_a_group_member_decides_but_only_listed_members_are_asked(self):
        """test_no_responsible."""
        request, (_step,) = self._request(
            {
                "name": "Mixed",
                "user_ids": [Command.set(self.member.ids)],
                "group_id": self.env.ref("base.group_system").id,
            },
        )
        activity_type = self.env.ref("approval.mail_activity_data_approval")
        asked = request.activity_ids.filtered(
            lambda a: a.activity_type_id == activity_type
        ).user_id
        self.assertEqual(asked, self.member)
        request.with_user(self.manager).action_approve()
        self.assertEqual(request.state, "approved")

    def test_a_step_holding_decisions_is_archived_not_deleted(self):
        """test_00_constraints."""
        request, (step,) = self._request(
            {"name": "Held", "user_ids": [Command.set(self.member.ids)]},
        )
        request.with_user(self.member).action_approve()
        with self.assertRaises(UserError):
            step.unlink()
        step.active = False
        self.assertFalse(step.active)

    def test_what_a_binding_gates_is_fixed_once_it_has_requests(self):
        """test_00_constraints."""
        step = self._member_step("action_archive")
        binding = self.Binding.search([("category_id", "=", step.category_id.id)])
        self.partner.with_user(self.plain).action_archive()
        self.assertTrue(
            self.Request.search_count([("binding_id", "=", binding.id)]),
            "the call raised a request",
        )
        with self.assertRaises(UserError):
            binding.write({"method": "action_unarchive"})
        binding.write({"sequence": 5})
        unused_step = self._member_step("toggle_active")
        unused = self.Binding.search([("category_id", "=", unused_step.category_id.id)])
        unused.write({"method": "action_unarchive"})
        self.assertEqual(unused.method, "action_unarchive")
