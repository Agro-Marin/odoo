from odoo.exceptions import UserError, ValidationError
from odoo.tests import common, tagged


@tagged("post_install", "-at_install")
class TestApprovalBinding(common.TransactionCase):
    """Gating a method rather than waiting for a document to ask.

    The binding wraps the method at registry load, so the gate holds for every
    caller. These cover the wrapping itself, the three modes, and the two
    defects the incumbent implementation in `web_studio` has: an unconditional
    `sudo()` bypass, and patches that do not compose.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env["ir.model"]._get("res.partner")
        cls.Binding = cls.env["approval.binding"]
        cls.approver = cls.env["res.users"].create(
            {
                "name": "Binding Approver",
                "login": "binding_approver",
                "email": "binding_approver@test.com",
                "group_ids": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, cls.env.ref("base.group_partner_manager").id),
                ],
            }
        )
        cls.category = cls.env["approval.category"].create(
            {"name": "Binding Category", "approval_minimum": 1}
        )
        cls.env["approval.category.approver"].create(
            {
                "category_id": cls.category.id,
                "user_id": cls.approver.id,
                "required": True,
                "sequence": 10,
            }
        )

    def tearDown(self):
        # the wrappers live on the registry, not in the transaction
        self.Binding._unregister_hook()
        super().tearDown()

    def _bind(self, **kwargs):
        vals = {
            "model_id": self.partner_model.id,
            "method": "action_archive",
            "mode": "advise",
        }
        vals.update(kwargs)
        binding = self.Binding.create(vals)
        self.Binding._unregister_hook()
        self.Binding._register_hook()
        return binding

    def _partner(self, **kwargs):
        vals = {"name": "Binding Partner"}
        vals.update(kwargs)
        return self.env["res.partner"].create(vals)

    # -- the wrapping itself ----------------------------------------------

    def test_registering_wraps_the_method_and_unregistering_restores_it(self):
        Partner = self.env.registry["res.partner"]
        self.assertFalse(hasattr(Partner.action_archive, "approval_binding_origin"))
        self._bind()
        Partner = self.env.registry["res.partner"]
        self.assertTrue(hasattr(Partner.action_archive, "approval_binding_origin"))
        self.Binding._unregister_hook()
        Partner = self.env.registry["res.partner"]
        self.assertFalse(hasattr(Partner.action_archive, "approval_binding_origin"))

    def test_two_bindings_on_one_method_share_a_single_wrapper(self):
        """Composition, not stacking: a second patch would make removal
        order-dependent, which is how `automation` loses other people's."""
        self._bind(subject_domain="[('is_company', '=', True)]")
        self._bind(subject_domain="[('is_company', '=', False)]")
        Partner = self.env.registry["res.partner"]
        wrapper = Partner.action_archive
        origin = wrapper.approval_binding_origin
        self.assertFalse(
            hasattr(origin, "approval_binding_origin"),
            "the wrapper wrapped another wrapper",
        )

    # -- observe mode ------------------------------------------------------

    def test_observe_mode_lets_the_call_through_and_records_it(self):
        binding = self._bind(mode="advise")
        partner = self._partner()
        partner.action_archive()
        self.assertFalse(partner.active, "observe mode must not block")
        self.assertEqual(binding.observation_count, 1)
        observation = binding.observation_ids
        self.assertEqual(observation.res_id, partner.id)
        self.assertTrue(observation.would_block)

    def test_observe_mode_separates_superuser_from_sudo_elevation(self):
        """The count that decides whether switching to Block is cheap."""
        binding = self._bind(mode="advise")
        self._partner().action_archive()
        self._partner().with_user(self.approver).sudo().action_archive()
        elevations = binding.observation_ids.mapped("elevation")
        self.assertIn("superuser", elevations)
        self.assertIn("self_elevated", elevations)
        self.assertEqual(binding.self_elevated_count, 1)

    def _plain_user(self):
        return self.env["res.users"].create(
            {
                "name": "Plain Caller",
                "login": "binding_plain",
                "email": "binding_plain@test.com",
                "group_ids": [
                    (4, self.env.ref("base.group_user").id),
                    (4, self.env.ref("base.group_partner_manager").id),
                ],
            }
        )

    def test_an_ordinary_caller_is_recorded_as_not_elevated(self):
        """Elevation is the caller's, not the binding's.

        The binding is read through `sudo()`. Measured on its own env, every
        caller looked elevated, so this row read `self_elevated` for a user who
        never called `sudo()` at all.
        """
        binding = self._bind(mode="advise")
        self._partner().with_user(self._plain_user()).action_archive()
        self.assertEqual(binding.observation_ids.elevation, "none")
        self.assertEqual(binding.self_elevated_count, 0)

    def test_the_bypass_policy_does_not_wave_an_ordinary_caller_through(self):
        """The defect that made the elevation bug a security bug.

        "Any elevated caller passes" is meant for callers that ARE elevated.
        With elevation measured on the sudo()ed binding, an ordinary user
        counted as elevated and passed a Block gate untouched.
        """
        self._bind(mode="block", category_id=self.category.id, sudo_policy="bypass")
        partner = self._partner()
        with self.assertRaises(UserError):
            partner.with_user(self._plain_user()).action_archive()
        self.assertTrue(partner.active, "the gate must not have been bypassed")

    def test_a_call_on_many_records_observes_each_of_them(self):
        binding = self._bind(mode="advise")
        partners = self._partner() | self._partner() | self._partner()
        partners.action_archive()
        self.assertEqual(binding.observation_count, 3)
        self.assertEqual(
            set(binding.observation_ids.mapped("res_id")), set(partners.ids)
        )

    def test_a_binding_only_fires_on_records_its_domain_selects(self):
        binding = self._bind(subject_domain="[('is_company', '=', True)]")
        self._partner(is_company=False).action_archive()
        self.assertEqual(binding.observation_count, 0)
        self._partner(is_company=True).action_archive()
        self.assertEqual(binding.observation_count, 1)

    # -- block mode --------------------------------------------------------

    def test_block_mode_refuses_an_unapproved_record(self):
        self._bind(mode="block", category_id=self.category.id, sudo_policy="enforce")
        partner = self._partner()
        with self.assertRaises(UserError):
            partner.action_archive()
        self.assertTrue(partner.active, "the operation must not have run")

    def test_block_mode_is_bypassed_by_the_superuser_under_the_default_policy(self):
        self._bind(mode="block", category_id=self.category.id)
        partner = self._partner()
        partner.action_archive()
        self.assertFalse(partner.active)

    def test_block_mode_does_not_let_an_ordinary_user_self_elevate(self):
        """`sudo()` keeps `uid`, so this is exactly what web_studio lets past."""
        self._bind(mode="block", category_id=self.category.id)
        partner = self._partner()
        with self.assertRaises(UserError):
            partner.with_user(self.approver).sudo().action_archive()
        self.assertTrue(partner.active)

    def test_the_kill_switch_disables_every_binding(self):
        self._bind(mode="block", category_id=self.category.id, sudo_policy="enforce")
        self.env["ir.config_parameter"].sudo().set_param(
            "approval.binding_enabled", "False"
        )
        partner = self._partner()
        partner.action_archive()
        self.assertFalse(partner.active)

    # -- configuration-time validation -------------------------------------

    def test_a_binding_on_a_method_automation_claims_is_refused(self):
        """`automation._unregister_hook` delattrs these registry-wide."""
        for method in ("create", "write", "unlink", "message_post"):
            with self.assertRaises(ValidationError):
                self.Binding.create(
                    {"model_id": self.partner_model.id, "method": method}
                )

    def test_a_binding_on_a_method_that_does_not_exist_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Binding.create(
                {"model_id": self.partner_model.id, "method": "no_such_method"}
            )

    def test_block_and_request_modes_need_a_category(self):
        with self.assertRaises(ValidationError):
            self.Binding.create(
                {
                    "model_id": self.partner_model.id,
                    "method": "action_archive",
                    "mode": "block",
                }
            )

    def test_request_mode_refuses_a_method_it_could_not_replay(self):
        """Storing arbitrary call arguments to replay later is where this
        design would start guessing, so the limit is enforced up front."""
        with self.assertRaises(ValidationError):
            self.Binding.create(
                {
                    "model_id": self.partner_model.id,
                    "method": "filtered_domain",
                    "mode": "request",
                    "category_id": self.category.id,
                }
            )

    def test_a_domain_naming_an_unknown_field_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Binding.create(
                {
                    "model_id": self.partner_model.id,
                    "method": "action_archive",
                    "subject_domain": "[('is_compayn', '=', True)]",
                }
            )

    def test_a_binding_cannot_gate_the_binding_machinery(self):
        with self.assertRaises(ValidationError):
            self.Binding.create(
                {
                    "model_id": self.env["ir.model"]._get("approval.binding").id,
                    "method": "action_archive",
                }
            )

    # -- request mode ------------------------------------------------------

    def _user(self, login, *groups):
        return self.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "email": f"{login}@test.com",
                "group_ids": [
                    (4, self.env.ref(xmlid).id)
                    for xmlid in ("base.group_user", *groups)
                ],
            }
        )

    def _request_binding(self, **kwargs):
        return self._bind(mode="request", category_id=self.category.id, **kwargs)

    def _requests_for(self, binding, partner):
        return self.env["approval.request"].search(
            [
                ("binding_id", "=", binding.id),
                ("res_model", "=", "res.partner"),
                ("res_id", "=", partner.id),
            ]
        )

    def _approve(self, request):
        request.approver_ids.filtered(lambda a: a.user_id == self.approver).with_user(
            self.approver
        ).action_approve()

    def test_request_mode_asks_for_approval_instead_of_running(self):
        binding = self._request_binding()
        requester = self._user("binding_req_a", "base.group_partner_manager")
        partner = self._partner()
        action = partner.with_user(requester).action_archive()
        self.assertTrue(partner.active, "the operation must not have run yet")
        request = self._requests_for(binding, partner)
        self.assertEqual(len(request), 1)
        self.assertEqual(request.state, "pending")
        self.assertEqual(request.request_owner_id, requester)
        self.assertEqual(action["res_model"], "approval.request")

    def test_calling_again_while_pending_does_not_raise_a_second_request(self):
        binding = self._request_binding()
        requester = self._user("binding_req_b", "base.group_partner_manager")
        partner = self._partner()
        partner.with_user(requester).action_archive()
        partner.with_user(requester).action_archive()
        self.assertEqual(len(self._requests_for(binding, partner)), 1)

    def test_approval_runs_the_operation_once_as_the_requester(self):
        binding = self._request_binding()
        requester = self._user("binding_req_c", "base.group_partner_manager")
        partner = self._partner()
        partner.with_user(requester).action_archive()
        request = self._requests_for(binding, partner)
        self._approve(request)
        self.assertFalse(partner.active, "approval must run the operation")
        self.assertEqual(partner.write_uid, requester, "as the requester")
        self.assertTrue(request.date_binding_replayed)
        self.assertFalse(request.binding_replay_error)

    def test_a_second_approval_after_a_withdrawal_does_not_run_it_again(self):
        binding = self._request_binding()
        requester = self._user("binding_req_d", "base.group_partner_manager")
        partner = self._partner()
        partner.with_user(requester).action_archive()
        request = self._requests_for(binding, partner)
        self._approve(request)
        replayed = request.date_binding_replayed
        partner.action_unarchive()
        request.with_user(self.approver).action_withdraw()
        self._approve(request)
        self.assertTrue(partner.active, "a second approval must not replay")
        self.assertEqual(request.date_binding_replayed, replayed)

    def test_an_approval_does_not_lend_the_approver_their_rights(self):
        """The requester could not archive; the approver could.

        Replaying as the approver would archive the partner with rights the
        requester never had. It must not run, and the decision must stand.
        """
        binding = self._request_binding()
        requester = self._user("binding_req_e")
        partner = self._partner()
        partner.with_user(requester).action_archive()
        request = self._requests_for(binding, partner)
        self._approve(request)
        self.assertTrue(partner.active, "it ran with somebody else's rights")
        self.assertEqual(request.state, "approved", "the decision itself stands")
        self.assertTrue(request.binding_replay_error)
        self.assertFalse(request.date_binding_replayed)

    def test_a_record_changed_since_the_request_is_not_run(self):
        binding = self._request_binding(subject_domain="[('city', '!=', 'Nowhere')]")
        requester = self._user("binding_req_f", "base.group_partner_manager")
        partner = self._partner(city="Before")
        partner.with_user(requester).action_archive()
        request = self._requests_for(binding, partner)
        self.assertEqual(request.binding_snapshot, {"city": ["Before"]})
        partner.city = "After"
        self._approve(request)
        self.assertTrue(partner.active, "approved values moved, so it must not run")
        self.assertEqual(request.state, "approved")
        self.assertTrue(request.binding_replay_error)
        self.assertEqual(
            len(self._requests_for(binding, partner)),
            1,
            "and the replay must not raise another request",
        )

    def test_block_mode_passes_once_an_approved_request_points_at_the_record(self):
        self._bind(mode="block", category_id=self.category.id, sudo_policy="enforce")
        partner = self._partner()
        request = self.env["approval.request"].create(
            {
                "name": "Approved separately",
                "category_id": self.category.id,
                "request_owner_id": self.env.user.id,
                "res_model": "res.partner",
                "res_id": partner.id,
            }
        )
        request.action_confirm()
        self._approve(request)
        partner.action_archive()
        self.assertFalse(partner.active)
