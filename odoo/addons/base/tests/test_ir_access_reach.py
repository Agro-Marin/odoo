from odoo.tests import BaseCase

from odoo.addons.base.models.ir_access_reach import Part, Proposal, propose, proves


class TestReachRecognizer(BaseCase):
    # the converter turns a domain into rows only when the rows it proposes
    # reach what the domain did, for a principal whose every id is distinct

    def assert_converts(self, domain, *parts, kind="permission"):
        proposal = propose(domain, kind)
        self.assertIsNotNone(proposal, domain)
        self.assertEqual(proposal.parts, list(parts))
        self.assertTrue(proves(domain, proposal), domain)

    def test_the_rungs(self):
        self.assert_converts("[(1, '=', 1)]", Part("all"))
        self.assert_converts("[(0, '=', 1)]", Part("none"))
        self.assert_converts(
            "[('company_id', 'in', company_ids)]",
            Part("company", "company", "company_id"),
        )
        self.assert_converts(
            "['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]",
            Part("company", "company", "company_id", unset=True),
        )
        self.assert_converts(
            "[('company_id', 'in', company_ids + [False])]",
            Part("company", "company", "company_id", unset=True),
        )
        self.assert_converts(
            "[('company_id', 'parent_of', company_ids)]",
            Part("company", "company", "company_id", hierarchy="parent_of"),
        )
        self.assert_converts(
            "[('user_id', 'in', (user.id, False))]",
            Part("own", "owner", "user_id", unset=True),
        )
        self.assert_converts(
            "[('create_uid', '=', user.id)]", Part("own", "creator", "create_uid")
        )
        self.assert_converts(
            "[('employee_id.user_id', '=', user.id)]",
            Part("own", "employee", "employee_id"),
        )
        self.assert_converts(
            "[('partner_id', 'child_of', [user.commercial_partner_id.id])]",
            Part("partner", "partner", "partner_id"),
        )
        self.assert_converts(
            "[('partner_id', '=', user.partner_id.id)]",
            Part("own", "partner", "partner_id"),
        )
        self.assert_converts(
            "[('team_id', 'in', user.sale_team_ids.ids)]",
            Part("team", "team", "team_id", usage="sale"),
        )

    def test_a_fixed_filter_rides_along(self):
        self.assert_converts(
            "[('state', '=', 'draft'), ('user_id', '=', user.id)]",
            Part("own", "owner", "user_id", static="[('state', '=', 'draft')]"),
        )

    def test_a_permission_s_disjuncts_become_rows(self):
        self.assert_converts(
            "['|', ('team_id.user_id', '=', user.id), ('team_id', 'in', user.team_ids.ids)]",
            Part("own", "owner", "team_id.user_id"),
            Part("team", "team", "team_id"),
        )
        self.assert_converts(
            "[('move_type', '=', 'out_invoice'), '|', "
            "('team_id', 'in', user.sale_team_ids.ids), ('invoice_user_id', '=', False)]",
            Part(
                "team",
                "team",
                "team_id",
                usage="sale",
                static="[('move_type', '=', 'out_invoice')]",
            ),
            Part(
                "all",
                static="['&', ('move_type', '=', 'out_invoice'), ('invoice_user_id', '=', False)]",
            ),
        )

    def test_a_guard_is_never_split(self):
        self.assertIsNone(
            propose(
                "['|', ('user_id', '=', user.id), ('create_uid', '=', user.id)]",
                "guard",
            )
        )

    def test_what_is_not_a_rung_stays_a_domain(self):
        for domain in (
            "[('user_id', '!=', user.id)]",
            "[('group_id', 'in', group_ids)]",
            "[('country_id', 'in', user.env.companies.country_id.ids)]",
            "[('user_id', '=', user.id), ('company_id', 'in', company_ids)]",
            "[('group_id', '=', ref('base.group_user'))]",
            "[] if user.has_group('base.group_user') else [('id', '=', 1)]",
        ):
            with self.subTest(domain=domain):
                self.assertIsNone(propose(domain, "permission"))

    def test_the_proof_refuses_a_misreading(self):
        domain = "[('user_id', '=', user.id)]"
        for wrong in (
            Part("own", "owner", "create_uid"),
            Part("own", "owner", "user_id", unset=True),
            Part("own", "partner", "user_id"),
            Part("company", "company", "user_id"),
            Part("all"),
        ):
            with self.subTest(part=wrong):
                self.assertFalse(proves(domain, Proposal([wrong])))
        self.assertFalse(
            proves(
                "[('company_id', 'in', company_ids)]",
                Proposal([Part("company", "company", "company_id", unset=True)]),
            )
        )

    def test_a_field_whose_search_reads_the_user_is_a_named_predicate(self):
        self.assert_converts(
            "[('project_id.user_has_access', '=', True)]",
            Part(
                "predicate",
                predicate="base.user_has_access",
                args=(("at", "project_id."),),
            ),
        )
        self.assert_converts(
            "[('state', '=', 'open'), ('user_has_access', '=', True)]",
            Part(
                "predicate",
                static="[('state', '=', 'open')]",
                predicate="base.user_has_access",
                args=(("at", ""),),
            ),
        )
        self.assert_converts(
            "[('sign_request_id.message_partner_ids', 'in', user.partner_id.ids)]",
            Part(
                "predicate",
                predicate="mail.follows",
                args=(("at", "sign_request_id."),),
            ),
        )

    def test_member_or_follower_splits_into_predicates(self):
        self.assert_converts(
            "['|', ('is_member', '=', True), ('parent_channel_id.is_member', '=', True)]",
            Part("predicate", predicate="base.is_member", args=(("at", ""),)),
            Part(
                "predicate",
                predicate="base.is_member",
                args=(("at", "parent_channel_id."),),
            ),
        )

    def test_a_field_reading_the_user_is_never_a_fixed_filter(self):
        self.assertIsNone(
            propose("[('is_self', '=', True), ('state', '=', 'x')]", "permission")
        )
        self.assertIsNone(
            propose(
                "[('user_id', '=', user.id), ('message_is_follower', '=', True)]",
                "permission",
            )
        )
