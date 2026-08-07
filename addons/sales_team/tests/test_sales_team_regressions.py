# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Regression tests for defects the rest of the suite did not cover.

Each test here failed before the fix it is named after; they are grouped by the
surface they guard rather than by model.
"""

from odoo import exceptions
from odoo.tests.common import users

from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.sales_team.tests.common import TestSalesCommon


class TestMembershipMultiParameter(TestSalesCommon):
    """`sales_team.membership_multi` is a string parameter, not a boolean."""

    def test_parameter_string_false_is_false(self):
        """'False' is what the settings screen writes when the box is unticked.

        ``res.config.settings.set_values`` stores ``str(bool(value))``, so an
        unticked box persists the literal ``'False'`` -- truthy in Python. Reading
        the parameter raw made the toggle one-way: the settings page reported
        "off" while every mono-membership code path stayed disabled.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        for raw, expected in (('False', False), ('0', False), ('off', False),
                              ('True', True), ('1', True)):
            ICP.search([('key', '=', 'sales_team.membership_multi')]).unlink()
            ICP.create({'key': 'sales_team.membership_multi', 'value': raw})
            self.env.invalidate_all()
            self.assertEqual(
                self.env['crm.team']._is_membership_multi(), expected,
                f"parameter {raw!r} should read as {expected}")
            team = self.env['crm.team'].create({'name': f'P {raw}', 'company_id': False})
            self.assertEqual(team.is_membership_multi, expected)

    def test_parameter_absent_defaults_to_mono(self):
        self.env['ir.config_parameter'].sudo().search(
            [('key', '=', 'sales_team.membership_multi')]).unlink()
        self.env.invalidate_all()
        self.assertFalse(self.env['crm.team']._is_membership_multi())


class TestArchivedMembershipVisibility(TestSalesCommon):
    """An archived membership must not survive anywhere as a live one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        cls.other_team = cls.env['crm.team'].create({'name': 'Other', 'company_id': False})
        cls.other_membership = cls.env['crm.team.member'].create({
            'user_id': cls.user_sales_leads.id, 'crm_team_id': cls.other_team.id,
        })

    def test_search_crm_team_ids_matches_compute(self):
        """search() and the compute must agree, in every context.

        sale's "Team Documents" record rules are written on the search side
        (``user_id.crm_team_ids``): while these disagreed, a salesperson who had
        left a team kept exposing their orders and invoices to it forever.
        """
        self.sales_team_1_m1.action_archive()
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertNotIn(self.sales_team_1, self.user_sales_leads.crm_team_ids)
        matched = self.env['res.users'].search([('crm_team_ids', 'in', self.sales_team_1.ids)])
        self.assertNotIn(self.user_sales_leads, matched)
        # the live membership is untouched
        self.assertIn(self.other_team, self.user_sales_leads.crm_team_ids)
        self.assertIn(
            self.user_sales_leads,
            self.env['res.users'].search([('crm_team_ids', 'in', self.other_team.ids)]))

    def test_search_crm_team_ids_keeps_archived_users(self):
        """The active_test override is about archived *users*; keep that.

        This used to build the state in two steps -- archive the user, then
        unarchive one of their memberships -- because the cascade had closed the
        one-step version. ``_constrains_live_endpoints`` now closes that one too:
        a live membership on an archived salesperson is precisely the row the
        many2many reads and the searches disagree about. What is still reachable,
        and still worth guarding, is the other half: an archived user remains
        searchable through ``crm_team_ids`` under ``active_test=False``.
        """
        self.user_sales_leads.with_context(active_test=False).write({'active': False})
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertFalse(self.user_sales_leads.with_context(active_test=False).active)
        matched = self.env['res.users'].with_context(active_test=False).search(
            [('crm_team_ids', '=', False)])
        self.assertIn(self.user_sales_leads, matched,
                      "an archived user must stay searchable by team")
        self.assertNotIn(
            self.user_sales_leads, self.env['res.users'].search([('crm_team_ids', '=', False)]),
            "and must not leak into a default-context search")

    def test_an_archived_user_cannot_keep_a_live_membership(self):
        """The state the test above used to build, now structurally refused."""
        self.user_sales_leads.with_context(active_test=False).write({'active': False})
        self.env.flush_all()
        self.assertFalse(self.other_membership.active, "the cascade archived it")
        with self.assertRaises(exceptions.ValidationError):
            self.other_membership.action_unarchive()
            self.env.flush_all()

    def test_sale_team_id_ignores_archived_membership(self):
        """The stored field must not depend on the caller's active_test.

        ``sale_team_id`` is stored, so a recompute triggered from a context with
        ``active_test=False`` used to persist an archived team.
        """
        self.assertEqual(self.user_sales_leads.sale_team_id, self.sales_team_1)
        archiving_env = self.env(context=dict(self.env.context, active_test=False))
        self.sales_team_1_m1.with_env(archiving_env).action_archive()
        archiving_env.flush_all()

        self.env.cr.execute("SELECT sale_team_id FROM res_users WHERE id = %s",
                            (self.user_sales_leads.id,))
        self.assertEqual(self.env.cr.fetchone()[0], self.other_team.id)
        self.env.invalidate_all()
        self.assertEqual(self.user_sales_leads.sale_team_id, self.other_team)

    def test_member_warning_ignores_archived_membership(self):
        """The warning counts live memberships whatever the context."""
        self.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', False)
        self.other_membership.action_archive()
        self.env.flush_all()
        self.env.invalidate_all()

        for context_label, team in (('default', self.sales_team_1),
                                    ('active_test=False',
                                     self.sales_team_1.with_context(active_test=False))):
            self.env.invalidate_all()
            self.assertNotIn(
                self.other_team.name, team.member_warning or '',
                f"{context_label}: an archived membership must not raise a warning")


class TestMonoMembership(TestSalesCommon):
    """A salesperson belongs to exactly one team in mono-membership mode."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', False)
        cls.team_a = cls.env['crm.team'].create({'name': 'A', 'company_id': False})
        cls.team_b = cls.env['crm.team'].create({'name': 'B', 'company_id': False})
        cls.salesperson = mail_new_test_user(
            cls.env, login='mono_user', name='Mono User',
            groups='sales_team.group_sale_salesman')

    def _active_memberships(self):
        return self.env['crm.team.member'].search([
            ('user_id', '=', self.salesperson.id), ('active', '=', True)])

    def test_creating_archived_membership_keeps_the_active_one(self):
        """Recording history must not evict the salesperson's live team."""
        live = self.env['crm.team.member'].create({
            'user_id': self.salesperson.id, 'crm_team_id': self.team_a.id})
        self.env.flush_all()

        self.env['crm.team.member'].create({
            'user_id': self.salesperson.id, 'crm_team_id': self.team_b.id, 'active': False})
        self.env.flush_all()

        self.assertTrue(live.active, "an archived membership must not archive the live one")
        self.assertEqual(self._active_memberships(), live)
        self.assertEqual(self.salesperson.sale_team_id, self.team_a)

    def test_batch_unarchive_keeps_a_single_team(self):
        """A multi-record Unarchive must end like repeated single writes."""
        member_a = self.env['crm.team.member'].create({
            'user_id': self.salesperson.id, 'crm_team_id': self.team_a.id})
        member_b = self.env['crm.team.member'].create({
            'user_id': self.salesperson.id, 'crm_team_id': self.team_b.id})
        (member_a | member_b).action_archive()
        self.env.flush_all()

        (member_a | member_b).action_unarchive()
        self.env.flush_all()

        self.assertEqual(len(self._active_memberships()), 1)
        self.assertEqual(self._active_memberships(), member_b, "the last one wins")

    def test_batch_create_keeps_a_single_team(self):
        self.env['crm.team.member'].create([
            {'user_id': self.salesperson.id, 'crm_team_id': self.team_a.id},
            {'user_id': self.salesperson.id, 'crm_team_id': self.team_b.id},
        ])
        self.env.flush_all()
        self.assertEqual(len(self._active_memberships()), 1)

    def test_same_team_duplicate_still_raises(self):
        """Evicting other teams must not silently swallow a real duplicate."""
        self.env['crm.team.member'].create({
            'user_id': self.salesperson.id, 'crm_team_id': self.team_a.id})
        self.env.flush_all()
        with self.assertRaises(exceptions.ValidationError):
            self.env['crm.team.member'].create({
                'user_id': self.salesperson.id, 'crm_team_id': self.team_a.id})


class TestMembershipCompanyChecks(TestSalesCommon):

    def test_unarchive_rechecks_company(self):
        """A team may change company while a membership sits archived."""
        company_2 = self.env['res.company'].create({'name': 'Regression Co2'})
        team = self.env['crm.team'].create({'name': 'Movable', 'company_id': False})
        membership = self.env['crm.team.member'].create({
            'user_id': self.user_sales_leads.id, 'crm_team_id': team.id})
        membership.action_archive()
        self.env.flush_all()

        team.company_id = company_2.id  # allowed: no active member left
        self.env.flush_all()

        with self.assertRaises(exceptions.UserError):
            membership.action_unarchive()


class TestMembershipMultiCompany(TestSalesCommon):
    """Memberships are company-scoped like the teams they belong to.

    ``crm.team`` had a multi-company rule and ``crm.team.member`` did not, so the
    membership rows of another company's teams stayed readable to every internal
    user even though the team itself was hidden.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_2 = cls.env['res.company'].create({'name': 'Foreign Co'})
        cls.foreign_user = mail_new_test_user(
            cls.env, login='foreign_user', name='Foreign User',
            company_id=cls.company_2.id, company_ids=[(6, 0, [cls.company_2.id])],
            groups='base.group_user')
        cls.foreign_team = cls.env['crm.team'].create({
            'name': 'Foreign Team', 'company_id': cls.company_2.id})
        cls.foreign_membership = cls.env['crm.team.member'].create({
            'crm_team_id': cls.foreign_team.id, 'user_id': cls.foreign_user.id})
        cls.shared_team = cls.env['crm.team'].create({
            'name': 'Shared Team', 'company_id': False})
        cls.shared_membership = cls.env['crm.team.member'].create({
            'crm_team_id': cls.shared_team.id, 'user_id': cls.user_sales_leads.id})

    def test_rule_exists(self):
        self.assertTrue(self.env.ref('sales_team.crm_team_member_comp_rule'))

    def test_foreign_membership_is_hidden(self):
        reader = self.user_sales_leads
        self.assertNotIn(self.company_2, reader.company_ids)
        with self.assertRaises(exceptions.AccessError):
            self.foreign_team.with_user(reader).read(['name'])
        with self.assertRaises(exceptions.AccessError):
            self.foreign_membership.with_user(reader).read(['name'])
        self.assertNotIn(
            self.foreign_membership,
            self.env['crm.team.member'].with_user(reader).search([]))

    def test_company_less_and_own_memberships_stay_readable(self):
        reader = self.user_sales_leads
        self.assertTrue(self.shared_membership.with_user(reader).read(['name']))
        self.assertIn(
            self.shared_membership,
            self.env['crm.team.member'].with_user(reader).search([]))
        # and the owning company still sees its own
        self.assertTrue(self.foreign_membership.with_user(self.foreign_user).read(['name']))


class TestDefaultTeamProtection(TestSalesCommon):

    def test_default_teams_cannot_be_deleted(self):
        for xmlid in ('sales_team.team_sales_department',
                      'sales_team.salesteam_website_sales',
                      'sales_team.pos_sales_team'):
            with self.assertRaises(exceptions.UserError), self.env.cr.savepoint():
                self.env.ref(xmlid).unlink()

    def test_unlink_survives_a_missing_default_xmlid(self):
        """A database missing one of the XML ids must still delete other teams."""
        self.env['ir.model.data'].search([
            ('module', '=', 'sales_team'), ('name', '=', 'pos_sales_team')]).unlink()
        self.env.flush_all()
        self.env.registry.clear_cache()

        disposable = self.env['crm.team'].create({'name': 'Disposable', 'company_id': False})
        self.env.flush_all()
        disposable.unlink()
        self.assertFalse(disposable.exists())


class TestUserArchiving(TestSalesCommon):

    def test_settings_admin_can_archive_a_salesperson(self):
        """Deactivating a user is a Settings job, not a Sales one.

        Only Sales administrators may write on crm.team.member, so cascading the
        archive without sudo made a plain Settings administrator unable to
        deactivate any user who happened to be on a sales team.
        """
        settings_admin = mail_new_test_user(
            self.env, login='settings_admin', name='Settings Admin',
            groups='base.group_user,base.group_system')
        self.assertFalse(settings_admin.has_group('sales_team.group_sale_manager'))

        self.user_sales_leads.with_user(settings_admin).action_archive()
        self.env.flush_all()

        self.assertFalse(self.user_sales_leads.active)
        self.assertFalse(self.sales_team_1_m1.active, "the membership follows the user")


class TestCompanyRevocation(TestSalesCommon):
    """Taking a company away from a salesperson must not leave a live membership.

    ``crm.team.member`` requires the team's company to be one of the
    salesperson's, but no constraint can trigger on a write to
    ``res.users.company_ids`` -- so this route left behind a membership that
    both constraints reject and that ``action_unarchive`` refuses to re-create,
    while ``crm_team_ids`` went on reporting the team to sale's record rules.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        cls.company_2 = cls.env['res.company'].create({'name': 'Revoked Co'})
        cls.salesperson = mail_new_test_user(
            cls.env, login='revoked_user', name='Revoked User',
            company_id=cls.company_main.id,
            company_ids=[(6, 0, [cls.company_main.id, cls.company_2.id])],
            groups='base.group_user')
        cls.team_c2 = cls.env['crm.team'].create(
            {'name': 'Revoked Team', 'company_id': cls.company_2.id})
        cls.team_shared = cls.env['crm.team'].create(
            {'name': 'Shared Team', 'company_id': False})
        cls.member_c2 = cls.env['crm.team.member'].create(
            {'crm_team_id': cls.team_c2.id, 'user_id': cls.salesperson.id})
        cls.member_shared = cls.env['crm.team.member'].create(
            {'crm_team_id': cls.team_shared.id, 'user_id': cls.salesperson.id})
        cls.env.flush_all()

    def test_revoking_a_company_archives_its_memberships(self):
        self.salesperson.write({'company_ids': [(6, 0, [self.company_main.id])]})
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertFalse(self.member_c2.active,
                         "the membership on the revoked company's team is archived")
        self.assertTrue(self.member_shared.active,
                        "a company-less team is unaffected")
        self.assertEqual(self.salesperson.crm_team_ids, self.team_shared)
        self.assertEqual(self.salesperson.sale_team_id, self.team_shared)

    def test_the_surviving_state_passes_the_constraints(self):
        """The state left behind must be one the model would accept."""
        self.salesperson.write({'company_ids': [(6, 0, [self.company_main.id])]})
        self.env.flush_all()
        # both constraints agreed this state was invalid; now nothing violates them
        self.team_c2._constrains_company_members()
        self.env['crm.team.member'].search(
            [('user_id', '=', self.salesperson.id)])._constrains_company_membership()

    def test_granting_a_company_changes_nothing(self):
        extra = self.env['res.company'].create({'name': 'Extra Co'})
        self.salesperson.write({'company_ids': [(4, extra.id)]})
        self.env.flush_all()
        self.assertTrue(self.member_c2.active, "granting a company evicts nobody")
        self.assertTrue(self.member_shared.active)

    def test_a_settings_admin_can_revoke(self):
        """Managing companies is a Settings job, not a Sales one."""
        settings_admin = mail_new_test_user(
            self.env, login='rev_settings_admin', name='Rev Settings Admin',
            groups='base.group_user,base.group_system,base.group_partner_manager')
        self.assertFalse(settings_admin.has_group('sales_team.group_sale_manager'))

        self.salesperson.with_user(settings_admin).write(
            {'company_ids': [(6, 0, [self.company_main.id])]})
        self.env.flush_all()
        self.assertFalse(self.member_c2.active)


class TestFavorite(TestSalesCommon):

    def test_is_favorite_is_per_user(self):
        team = self.env['crm.team'].create({'name': 'Favourite', 'company_id': False})
        team.favorite_user_ids = [(6, 0, [self.user_sales_manager.id])]
        self.env.flush_all()

        for first, second in ((self.user_sales_manager, self.user_sales_leads),
                              (self.user_sales_leads, self.user_sales_manager)):
            # order matters: without depends_context('uid') the first reader's
            # answer is cached under a uid-less key and served to the second
            self.env.invalidate_all()
            expected_first = first == self.user_sales_manager
            self.assertEqual(team.with_user(first).is_favorite, expected_first)
            self.assertEqual(team.with_user(second).is_favorite, not expected_first)

    def test_is_favorite_follows_favorite_user_ids(self):
        """Without @api.depends the flag goes stale as soon as members are added."""
        team = self.env['crm.team'].create({'name': 'Favourite 2', 'company_id': False})
        as_leads = team.with_user(self.user_sales_leads)
        self.assertFalse(as_leads.is_favorite)

        team.favorite_user_ids = [(4, self.user_sales_leads.id)]
        self.assertTrue(as_leads.is_favorite)

        team.favorite_user_ids = [(3, self.user_sales_leads.id)]
        self.assertFalse(as_leads.is_favorite)

    def test_adding_members_refreshes_the_flag(self):
        """crm.team.create/write add members to favourites behind the field."""
        team = self.env['crm.team'].create({
            'name': 'Favourite 3', 'company_id': False,
            'member_ids': [(4, self.user_sales_leads.id)]})
        self.env.flush_all()
        self.assertTrue(team.with_user(self.user_sales_leads).is_favorite)

    def test_every_way_of_joining_a_team_grants_the_favourite(self):
        """Joining a team must reach the dashboard however it was done.

        Favouriting hung off crm.team.create/write watching ``member_ids``, so
        the very same act -- putting a salesperson on a team -- landed on their
        dashboard or not depending on which side of the relation was written.
        """
        # multi mode: otherwise each new team would legitimately evict the last
        self.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        leads = self.user_sales_leads
        teams = {}

        teams['member_ids on create'] = self.env['crm.team'].create({
            'name': 'Join A', 'company_id': False, 'member_ids': [(4, leads.id)]})

        teams['member_ids on write'] = team = self.env['crm.team'].create({
            'name': 'Join B', 'company_id': False})
        team.write({'member_ids': [(4, leads.id)]})

        teams['crm_team_member_ids on create'] = self.env['crm.team'].create({
            'name': 'Join C', 'company_id': False,
            'crm_team_member_ids': [(0, 0, {'user_id': leads.id})]})

        teams['crm_team_member_ids on write'] = team = self.env['crm.team'].create({
            'name': 'Join D', 'company_id': False})
        team.write({'crm_team_member_ids': [(0, 0, {'user_id': leads.id})]})

        teams['crm.team.member.create'] = team = self.env['crm.team'].create({
            'name': 'Join E', 'company_id': False})
        self.env['crm.team.member'].create({'crm_team_id': team.id, 'user_id': leads.id})

        self.env.flush_all()
        for label, team in teams.items():
            self.assertIn(leads, team.member_ids, f"{label}: membership")
            self.assertIn(leads, team.favorite_user_ids, f"{label}: favourite")


class TestMultiMembershipActivation(TestSalesCommon):
    """The "Activate Multi-team" banner button.

    The permission check used to sit in the form controller, guarding on the
    *async* ``user.hasGroup`` without awaiting it -- so it never fired -- and the
    client then wrote the ``ir.config_parameter`` itself. Writing that model needs
    Settings rights, so the button was broken for the Sales Administrators the
    banner addresses and worked only for Settings administrators.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', False)

    def test_sales_administrator_can_activate(self):
        self.assertFalse(self.env['crm.team']._is_membership_multi())
        self.env['crm.team'].with_user(self.user_sales_manager).action_activate_multi_membership()
        self.env.invalidate_all()
        self.assertTrue(self.env['crm.team']._is_membership_multi())

    def test_salesman_cannot_activate(self):
        salesman = self.user_sales_salesman
        self.assertFalse(salesman.has_group('sales_team.group_sale_manager'))
        with self.assertRaises(exceptions.AccessError):
            self.env['crm.team'].with_user(salesman).action_activate_multi_membership()
        self.env.invalidate_all()
        self.assertFalse(self.env['crm.team']._is_membership_multi())

    def test_activation_does_not_require_settings_rights(self):
        """A Sales Administrator has no rights on ir.config_parameter."""
        manager = self.user_sales_manager
        self.assertFalse(manager.has_group('base.group_system'))
        with self.assertRaises(exceptions.AccessError), self.env.cr.savepoint():
            self.env['ir.config_parameter'].with_user(manager).set_param(
                'sales_team.membership_multi', True)
        # ... yet the sales-side action works, because it sudoes the write
        self.env['crm.team'].with_user(manager).action_activate_multi_membership()
        self.env.invalidate_all()
        self.assertTrue(self.env['crm.team']._is_membership_multi())


class TestMembershipQueries(TestSalesCommon):
    """The computes used by list and kanban views must not scale with the table."""

    @users('user_sales_manager')
    def test_member_warning_is_batched(self):
        """One query for the whole recordset, not one per team.

        Every team must actually have members: with an empty ``member_ids`` the
        domain collapses to a false leaf and no query is emitted at all, which
        hides the per-team search this guards against.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('sales_team.membership_multi', True)  # so the setup keeps them all
        salespersons = self.env['res.users'].sudo().create([
            {'name': f'Batch member {i}', 'login': f'batch_member_{i}',
             'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]}
            for i in range(3)])
        teams = self.env['crm.team'].sudo().create(
            [{'name': f'Batch {i}', 'company_id': False} for i in range(20)])
        self.env['crm.team.member'].sudo().create([
            {'crm_team_id': team.id, 'user_id': salesperson.id}
            for team in teams for salesperson in salespersons])
        self.env.flush_all()
        ICP.set_param('sales_team.membership_multi', False)
        self.env.invalidate_all()

        with self.assertQueryCount(user_sales_manager=10):
            teams.mapped('member_warning')



class TestSearchCrmTeamIds(TestSalesCommon):
    """``res.users.crm_team_ids`` must search like the many2many it presents.

    The search method pushed the operator inside the ``any``, so a negative
    operator asked "has SOME live membership whose team is not X" where the
    field means "has NO live membership whose team is X". ``= False`` asked for
    a membership whose (required) team was False and so matched nobody.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        cls.team_a = cls.env['crm.team'].create({'name': 'SA', 'company_id': False})
        cls.team_b = cls.env['crm.team'].create({'name': 'SB', 'company_id': False})
        cls.user_ab = mail_new_test_user(
            cls.env, login='search_ab', name='Search AB', groups='base.group_user')
        cls.user_none = mail_new_test_user(
            cls.env, login='search_none', name='Search None', groups='base.group_user')
        cls.env['crm.team.member'].create([
            {'user_id': cls.user_ab.id, 'crm_team_id': cls.team_a.id},
            {'user_id': cls.user_ab.id, 'crm_team_id': cls.team_b.id},
        ])
        # an archived membership must read as "not in that team"
        cls.env['crm.team.member'].create({
            'user_id': cls.user_none.id, 'crm_team_id': cls.team_a.id}).action_archive()
        cls.env.flush_all()

    def _search(self, operator, value):
        return self.env['res.users'].search([
            ('id', 'in', (self.user_ab | self.user_none).ids),
            ('crm_team_ids', operator, value),
        ])

    def test_negative_operators(self):
        """A member of A must not match "not in A", whichever spelling is used."""
        for operator, value in (('not in', self.team_a.ids), ('!=', self.team_a.id)):
            found = self._search(operator, value)
            self.assertNotIn(self.user_ab, found,
                             f"{operator}: a member of A must not match")
            self.assertIn(self.user_none, found,
                          f"{operator}: a user with no live team must match")

    def test_positive_operators_are_unchanged(self):
        for operator, value in (('in', self.team_a.ids), ('=', self.team_a.id)):
            found = self._search(operator, value)
            self.assertIn(self.user_ab, found)
            self.assertNotIn(self.user_none, found,
                             f"{operator}: an archived membership must not match")

    def test_empty_relation(self):
        found = self._search('=', False)
        self.assertIn(self.user_none, found, "a user with no live team must be findable")
        self.assertNotIn(self.user_ab, found)
        self.assertEqual(self._search('!=', False), self.user_ab)

    def test_matches_a_stored_many2many(self):
        """Pin the semantics to a real stored m2m on mirrored data."""
        cat_a, cat_b = self.env['res.partner.category'].create([{'name': 'MA'}, {'name': 'MB'}])
        p_ab = self.env['res.partner'].create(
            {'name': 'P AB', 'category_id': [(6, 0, (cat_a | cat_b).ids)]})
        p_none = self.env['res.partner'].create({'name': 'P None'})
        pairs = {self.user_ab: p_ab, self.user_none: p_none}
        for operator, team_value, cat_value in (
            ('in', self.team_a.ids, cat_a.ids), ('not in', self.team_a.ids, cat_a.ids),
            ('=', self.team_a.id, cat_a.id), ('!=', self.team_a.id, cat_a.id),
            ('=', False, False), ('!=', False, False),
        ):
            reference = self.env['res.partner'].search(
                [('id', 'in', (p_ab | p_none).ids), ('category_id', operator, cat_value)])
            self.assertEqual(
                set(self._search(operator, team_value)),
                {user for user, partner in pairs.items() if partner in reference},
                f"crm_team_ids {operator} {team_value!r} disagrees with a stored m2m")


class TestSearchMemberIds(TestSalesCommon):
    """``crm.team.member_ids`` must search like the many2many it presents.

    Same defects as ``res.users.crm_team_ids``, seen from the other end of the
    join and left behind when that side was repaired: the dotted path carried
    the raw operator into the traversal, so ``not in`` asked "has SOME member
    who is not X" where the field means "has NO member X", and ``= False``
    asked for a membership whose required ``user_id`` was False. Both spellings
    are reachable from ``crm_team_view_search``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        cls.team_a = cls.env['crm.team'].create({'name': 'MA', 'company_id': False})
        cls.team_b = cls.env['crm.team'].create({'name': 'MB', 'company_id': False})
        cls.team_empty = cls.env['crm.team'].create({'name': 'MEmpty', 'company_id': False})
        cls.member_a = mail_new_test_user(
            cls.env, login='mi_a', name='Mi A', groups='base.group_user')
        cls.member_b = mail_new_test_user(
            cls.env, login='mi_b', name='Mi B', groups='base.group_user')
        cls.env['crm.team.member'].create([
            {'user_id': cls.member_a.id, 'crm_team_id': cls.team_a.id},
            {'user_id': cls.member_b.id, 'crm_team_id': cls.team_b.id},
        ])
        # a former member of A: archived, so it must read as "not a member"
        cls.env['crm.team.member'].create({
            'user_id': cls.member_b.id, 'crm_team_id': cls.team_a.id}).action_archive()
        cls.teams = cls.team_a | cls.team_b | cls.team_empty
        cls.env.flush_all()

    def _search(self, operator, value):
        return self.env['crm.team'].search([
            ('id', 'in', self.teams.ids), ('member_ids', operator, value)])

    def test_negative_operators(self):
        """A team keeping another member must not match "not in [that member]"."""
        for operator, value in (('not in', self.member_a.ids), ('!=', self.member_a.id)):
            found = self._search(operator, value)
            self.assertNotIn(self.team_a, found, f"{operator}: A has that member")
            self.assertIn(self.team_b, found, f"{operator}: B has another member")
            self.assertIn(self.team_empty, found, f"{operator}: an empty team matches")

    def test_positive_operators_ignore_archived_memberships(self):
        for operator, value in (('in', self.member_b.ids), ('=', self.member_b.id)):
            found = self._search(operator, value)
            self.assertIn(self.team_b, found)
            self.assertNotIn(self.team_a, found,
                             f"{operator}: a former member must not match")

    def test_empty_relation(self):
        self.assertEqual(self._search('=', False), self.team_empty,
                         "a team with no member must be findable")
        self.assertEqual(self._search('!=', False), self.team_a | self.team_b)

    def test_mixed_false_and_ids(self):
        self.assertEqual(
            self._search('in', [False] + self.member_a.ids), self.team_a | self.team_empty,
            "a list mixing False with ids reads as 'empty OR one of these'")

    def test_matches_a_stored_many2many(self):
        """Pin the semantics to a real stored m2m on mirrored data."""
        cat_a, cat_b = self.env['res.partner.category'].create([{'name': 'TA'}, {'name': 'TB'}])
        p_a = self.env['res.partner'].create(
            {'name': 'T PA', 'category_id': [(6, 0, cat_a.ids)]})
        p_b = self.env['res.partner'].create(
            {'name': 'T PB', 'category_id': [(6, 0, cat_b.ids)]})
        p_empty = self.env['res.partner'].create({'name': 'T PEmpty'})
        pairs = {self.team_a: p_a, self.team_b: p_b, self.team_empty: p_empty}
        partners = p_a | p_b | p_empty
        for operator, member_value, cat_value in (
            ('in', self.member_a.ids, cat_a.ids), ('not in', self.member_a.ids, cat_a.ids),
            ('=', self.member_a.id, cat_a.id), ('!=', self.member_a.id, cat_a.id),
            ('=', False, False), ('!=', False, False),
            ('in', [False] + self.member_a.ids, [False] + cat_a.ids),
        ):
            reference = self.env['res.partner'].search(
                [('id', 'in', partners.ids), ('category_id', operator, cat_value)])
            self.assertEqual(
                set(self._search(operator, member_value)),
                {team for team, partner in pairs.items() if partner in reference},
                f"member_ids {operator} {member_value!r} disagrees with a stored m2m")


class TestSearchCrmTeamIdsMixedFalse(TestSalesCommon):
    """The other end of the join had one shape left: ``in [False, <id>]``.

    The guard only recognised a list of *nothing but* False, so a list mixing
    False with real ids silently dropped the "no team at all" half and returned
    only the members of those teams.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        cls.team = cls.env['crm.team'].create({'name': 'MF', 'company_id': False})
        cls.on_team = mail_new_test_user(
            cls.env, login='mf_on', name='MF On', groups='base.group_user')
        cls.teamless = mail_new_test_user(
            cls.env, login='mf_off', name='MF Off', groups='base.group_user')
        cls.env['crm.team.member'].create(
            {'user_id': cls.on_team.id, 'crm_team_id': cls.team.id})
        cls.env.flush_all()

    def test_mixed_false_and_ids(self):
        found = self.env['res.users'].search([
            ('id', 'in', (self.on_team | self.teamless).ids),
            ('crm_team_ids', 'in', [False] + self.team.ids),
        ])
        self.assertEqual(found, self.on_team | self.teamless,
                         "'no team OR that team' must return both")


class TestMonoMembershipReassignment(TestSalesCommon):
    """Mono mode is about which (team, salesperson) pairs are live.

    Repointing a live membership at another salesperson mints a new pair just
    as activating one does, so it has to evict that salesperson's other teams.
    Enforcement hung off ``vals.get('active')`` alone, so this route left them
    on two teams -- the very state mono mode exists to prevent.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', False)
        cls.team_a = cls.env['crm.team'].create({'name': 'RA', 'company_id': False})
        cls.team_b = cls.env['crm.team'].create({'name': 'RB', 'company_id': False})
        cls.alice = mail_new_test_user(
            cls.env, login='reass_alice', name='Alice', groups='base.group_user')
        cls.bob = mail_new_test_user(
            cls.env, login='reass_bob', name='Bob', groups='base.group_user')

    def _live_teams(self, user):
        return self.env['crm.team.member'].search([
            ('user_id', '=', user.id), ('active', '=', True)]).crm_team_id

    def test_reassigning_user_id_evicts_the_other_team(self):
        on_a = self.env['crm.team.member'].create(
            {'crm_team_id': self.team_a.id, 'user_id': self.alice.id})
        self.env['crm.team.member'].create(
            {'crm_team_id': self.team_b.id, 'user_id': self.bob.id})
        self.env.flush_all()

        on_a.write({'user_id': self.bob.id})
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(self._live_teams(self.bob), self.team_a,
                         "the membership just handed over wins")
        self.assertEqual(self.bob.crm_team_ids, self.team_a)
        self.assertEqual(self.bob.sale_team_id, self.team_a)
        self.assertFalse(self._live_teams(self.alice))

    def test_multi_mode_keeps_both(self):
        """The eviction is mono-mode only; multi mode must be untouched."""
        self.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        self.env.invalidate_all()
        on_a = self.env['crm.team.member'].create(
            {'crm_team_id': self.team_a.id, 'user_id': self.alice.id})
        self.env['crm.team.member'].create(
            {'crm_team_id': self.team_b.id, 'user_id': self.bob.id})
        self.env.flush_all()

        on_a.write({'user_id': self.bob.id})
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(self._live_teams(self.bob), self.team_a | self.team_b)


class TestDefaultTeamFromContext(TestSalesCommon):
    """``default_team_id`` was browsed straight from the context.

    A bare browse honours neither ``active`` nor the record rules, so a stale
    action context or saved filter naming a dead -- or foreign -- team handed it
    back as the default for a brand new sales document.
    """

    def test_archived_context_team_is_not_proposed(self):
        live = self.env['crm.team'].create({'name': 'Live', 'company_id': False})
        dead = self.env['crm.team'].create({'name': 'Dead', 'company_id': False})
        dead.action_archive()
        self.env.flush_all()

        team = self.env['crm.team'].with_context(
            default_team_id=dead.id)._get_default_team_id()
        self.assertNotEqual(team, dead, "an archived team must not be proposed")
        self.assertTrue(not team or team.active)
        # the fallbacks still work
        self.assertTrue(
            self.env['crm.team'].with_context(default_team_id=live.id)._get_default_team_id())

    def test_deleted_context_team_is_not_proposed(self):
        dangling = self.env['crm.team'].create({'name': 'Dangling', 'company_id': False})
        dangling_id = dangling.id
        dangling.unlink()
        self.env.flush_all()

        team = self.env['crm.team'].with_context(
            default_team_id=dangling_id)._get_default_team_id()
        self.assertNotEqual(team.id, dangling_id)

    def test_unreadable_context_team_is_still_honoured(self):
        """A context default is an instruction, not a suggestion.

        Deliberately *not* filtered by the record rules: sale_crm carries a
        lead's team over to its quotation and website_sale names the website's
        team, and the actor is not always allowed to read the team they are
        legitimately being put on. Rule-filtering here would silently swap those
        for the reader's own team.
        """
        salesman = self.user_sales_salesman  # sees only the teams they lead or join
        hidden = self.env['crm.team'].create({'name': 'Hidden', 'company_id': False})
        self.env.flush_all()
        self.assertFalse(self.env['crm.team'].with_user(salesman).search_count(
            [('id', '=', hidden.id)]), "test setup: the team must be invisible")

        team = self.env['crm.team'].with_user(salesman).with_context(
            default_team_id=hidden.id)._get_default_team_id()
        self.assertEqual(team, hidden)
        self.assertFalse(team.env.su, "and it must not come back sudoed")

    def test_readable_context_team_still_wins(self):
        """Guard against validating the default into oblivion."""
        own = self.env['crm.team'].create({
            'name': 'Own', 'company_id': False, 'sequence': 99,
            'member_ids': [(4, self.user_sales_leads.id)]})
        self.env.flush_all()
        team = self.env['crm.team'].with_user(self.user_sales_leads).with_context(
            default_team_id=own.id)._get_default_team_id()
        self.assertEqual(team, own)


class TestMembershipVisibility(TestSalesCommon):
    """A membership is visible exactly when its team is.

    crm.team is restricted to the teams a salesperson leads or belongs to, but
    its membership rows carried no matching rule, so a salesperson could search
    up the roster of a team they cannot open. The team's *name* stayed hidden --
    reading crm_team_id's display name needs read on crm.team -- but the rows,
    their user_id and the size of the team did not.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        cls.my_team = cls.env['crm.team'].create({'name': 'My Team', 'company_id': False})
        cls.led_team = cls.env['crm.team'].create({'name': 'Led Team', 'company_id': False})
        cls.foreign_team = cls.env['crm.team'].create({'name': 'Foreign', 'company_id': False})
        cls.salesman = mail_new_test_user(
            cls.env, login='vis_salesman', name='Vis Salesman',
            groups='sales_team.group_sale_salesman')
        cls.teammate = mail_new_test_user(
            cls.env, login='vis_teammate', name='Vis Teammate', groups='base.group_user')
        cls.stranger = mail_new_test_user(
            cls.env, login='vis_stranger', name='Vis Stranger', groups='base.group_user')
        cls.led_team.user_id = cls.salesman.id
        cls.mine, cls.mates, cls.theirs = cls.env['crm.team.member'].create([
            {'crm_team_id': cls.my_team.id, 'user_id': cls.salesman.id},
            {'crm_team_id': cls.my_team.id, 'user_id': cls.teammate.id},
            {'crm_team_id': cls.foreign_team.id, 'user_id': cls.stranger.id},
        ])
        cls.led = cls.env['crm.team.member'].create(
            {'crm_team_id': cls.led_team.id, 'user_id': cls.teammate.id})
        cls.env.flush_all()

    def test_foreign_membership_is_not_searchable(self):
        visible = self.env['crm.team.member'].with_user(self.salesman).search([])
        self.assertNotIn(self.theirs, visible,
                         "the roster of an unreadable team must not be searchable")
        self.assertIn(self.mine, visible)
        self.assertIn(self.mates, visible, "a teammate's row on my own team stays visible")
        self.assertIn(self.led, visible, "so does the roster of a team I lead")

    def test_visibility_matches_the_team_rule_exactly(self):
        """The invariant, asserted rather than assumed."""
        as_salesman = self.env['crm.team.member'].with_user(self.salesman)
        readable_teams = self.env['crm.team'].with_user(self.salesman).search([])
        for membership in self.env['crm.team.member'].search([]):
            expected = membership.crm_team_id in readable_teams
            found = bool(as_salesman.search_count([('id', '=', membership.id)]))
            self.assertEqual(
                found, expected,
                f"membership {membership.id}: visible={found} but team readable={expected}")

    def test_the_team_roster_still_renders(self):
        """Guard against locking a salesperson out of their own team's members."""
        team = self.my_team.with_user(self.salesman)
        self.assertEqual(team.member_ids, self.salesman | self.teammate)
        self.assertEqual(team.crm_team_member_ids, self.mine | self.mates)

    def test_all_documents_and_managers_are_unaffected(self):
        for user in (self.user_sales_leads,        # group_sale_salesman_all_leads
                     self.user_sales_manager):     # group_sale_manager
            visible = self.env['crm.team.member'].with_user(user).search([])
            self.assertIn(self.theirs, visible, f"{user.login} must still see everything")

    def test_own_teams_still_resolve(self):
        """The rule reads user.crm_team_ids, which reads memberships: no cycle."""
        as_self = self.salesman.with_user(self.salesman)
        self.assertEqual(as_self.crm_team_ids, self.my_team)
        self.assertEqual(as_self.sale_team_id, self.my_team)


class TestDefaultTeamFallbackQueries(TestSalesCommon):
    """Steps 4/5 must not load the whole team table to return one row.

    They are reached exactly for the salespeople who have no team of their own,
    so over a mass import they ran per salesperson -- and the old code searched
    every team of the company just to hand the first match to filtered_domain.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['crm.team'].search([]).write({'sequence': 50})
        cls.wanted = cls.env['crm.team'].create({
            'name': 'Wanted', 'company_id': False, 'sequence': 1, 'user_id': False})
        cls.filler = cls.env['crm.team'].create([
            {'name': f'Filler {i}', 'company_id': False, 'sequence': 10, 'user_id': False}
            for i in range(30)])
        cls.loner = mail_new_test_user(
            cls.env, login='fallback_loner', name='Fallback Loner',
            groups='sales_team.group_sale_salesman_all_leads')
        cls.env.flush_all()

    def test_domain_fallback_picks_the_same_team_as_filtered_domain(self):
        """Pin the new searched domain against the in-memory semantics."""
        domain = [('name', '=', 'Wanted')]
        team = self.env['crm.team'].with_user(self.loner)._get_default_team_id(domain=domain)
        reference = self.env['crm.team'].with_user(self.loner).search([])
        self.assertEqual(team, reference.filtered_domain(domain)[:1])
        self.assertEqual(team, self.wanted)

    def test_domain_fallback_falls_back_to_the_first_team(self):
        """A domain matching nothing still yields the first team, as before."""
        domain = [('name', '=', 'No Such Team')]
        team = self.env['crm.team'].with_user(self.loner)._get_default_team_id(domain=domain)
        reference = self.env['crm.team'].with_user(self.loner).search([])
        self.assertEqual(team, reference[:1])
        self.assertEqual(team, self.wanted, "sequence 1 ranks first")

    def _rows_fetched_by_fallback(self):
        """Rows the fallback pulls out of Postgres, not queries it issues.

        Query *count* is the wrong probe here -- the old code also got there in
        a couple of statements. What it did was select every team of the company
        and fetch the domain's field for all of them so filtered_domain could
        run in memory, so the cost shows up in rows, and only rows.
        """
        # No invalidate_all(): the first call of the transaction also loads the
        # rules, the user and the companies, and those hundred-odd rows would
        # swamp the figure being compared. The searches themselves always hit
        # the database, so a warm cache does not hide them.
        rows = [0]
        cursor_cls = type(self.env.cr)
        original = cursor_cls.execute

        def counting(cr, query, params=None, **kwargs):
            result = original(cr, query, params, **kwargs)
            rows[0] += max(cr.rowcount, 0)
            return result

        cursor_cls.execute = counting
        try:
            self.env['crm.team'].with_user(self.loner)._get_default_team_id(
                domain=[('name', '=', 'Wanted')])
        finally:
            cursor_cls.execute = original
        return rows[0]

    def test_fallback_does_not_scale_with_the_table(self):
        """The claim is "constant", so assert it against two table sizes.

        Pinning one absolute number would only re-measure whatever the rest of
        the stack costs today; growing the table five-fold and demanding the
        same figure is the actual property.
        """
        self._rows_fetched_by_fallback()          # warm the rules and the user
        small = self._rows_fetched_by_fallback()
        self.env['crm.team'].create([
            {'name': f'Bulk {i}', 'company_id': False, 'sequence': 10, 'user_id': False}
            for i in range(120)])
        self.env.flush_all()
        large = self._rows_fetched_by_fallback()
        self.assertEqual(
            small, large,
            f"{small} rows fetched with 31 teams but {large} with 151: the "
            "fallback still scales with the table")


class TestArchivedTeamMembership(TestSalesCommon):
    """A live membership must never point at an archived team."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        cls.team = cls.env['crm.team'].create({'name': 'Doomed', 'company_id': False})
        cls.member = cls.env['crm.team.member'].create({
            'crm_team_id': cls.team.id, 'user_id': cls.user_sales_leads.id})
        cls.env.flush_all()

    def test_write_active_false_cascades_like_the_action(self):
        """The action is only the UI path; the cascade belongs to write."""
        self.team.write({'active': False})
        self.env.flush_all()
        self.assertFalse(self.member.active)

    def test_archiving_a_user_by_write_cascades(self):
        self.user_sales_leads.with_context(active_test=False).write({'active': False})
        self.env.flush_all()
        self.assertFalse(self.member.active)

    def test_cannot_join_an_archived_team(self):
        self.team.action_archive()
        self.env.flush_all()
        other = mail_new_test_user(
            self.env, login='joins_dead', name='Joins Dead', groups='base.group_user')
        with self.assertRaises(exceptions.ValidationError):
            self.env['crm.team.member'].create(
                {'crm_team_id': self.team.id, 'user_id': other.id})
            self.env.flush_all()

    def test_cannot_unarchive_onto_an_archived_team(self):
        self.team.action_archive()
        self.env.flush_all()
        self.assertFalse(self.member.active)
        with self.assertRaises(exceptions.ValidationError):
            self.member.action_unarchive()
            self.env.flush_all()

    def test_cannot_join_a_team_as_an_archived_user(self):
        """The salesperson end of the same invariant, which had no guard.

        A live membership on a dead user is the state the many2many reads and
        the searches disagree about, seen from the other side of the join.
        """
        ghost = mail_new_test_user(
            self.env, login='ghost_user', name='Ghost User', groups='base.group_user')
        ghost.action_archive()
        self.env.flush_all()
        with self.assertRaises(exceptions.ValidationError):
            self.env['crm.team.member'].create(
                {'crm_team_id': self.team.id, 'user_id': ghost.id})
            self.env.flush_all()

    def test_cannot_unarchive_a_membership_of_an_archived_user(self):
        self.user_sales_leads.action_archive()   # cascades the archive
        self.env.flush_all()
        self.assertFalse(self.member.active)
        with self.assertRaises(exceptions.ValidationError):
            self.member.action_unarchive()
            self.env.flush_all()

    def test_reads_and_searches_agree_on_an_archived_user(self):
        """The three symptoms the guard exists to prevent, asserted together."""
        self.user_sales_leads.action_archive()
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(self.team.member_ids.ids, self.team.crm_team_member_ids.user_id.ids,
                         "the many2many and the one2many must report the same people")
        self.assertNotIn(
            self.team,
            self.env['crm.team'].search([('member_ids', 'in', [self.user_sales_leads.id])]),
            "search must agree with the many2many read")
        self.env.cr.execute("SELECT sale_team_id FROM res_users WHERE id = %s",
                            (self.user_sales_leads.id,))
        self.assertNotEqual(self.env.cr.fetchone()[0], self.team.id,
                            "the stored column must not stay pinned to the team")

    def test_stored_sale_team_id_never_holds_an_archived_team(self):
        """crm's pipeline action and sale_commission both read this column."""
        self.team.write({'active': False})
        self.env.flush_all()
        self.env.cr.execute("SELECT sale_team_id FROM res_users WHERE id = %s",
                            (self.user_sales_leads.id,))
        self.assertNotEqual(self.env.cr.fetchone()[0], self.team.id)


class TestMemberWarningVisibility(TestSalesCommon):
    """The warning must not name -- or crash on -- a team the reader cannot see."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_2 = cls.env['res.company'].create({'name': 'Warning Co2'})
        cls.local_manager = mail_new_test_user(
            cls.env, login='warn_mgr', name='Warn Mgr',
            company_id=cls.company_main.id, company_ids=[(6, 0, [cls.company_main.id])],
            groups='sales_team.group_sale_manager')
        cls.shared_user = mail_new_test_user(
            cls.env, login='warn_shared', name='Warn Shared',
            company_id=cls.company_main.id,
            company_ids=[(6, 0, [cls.company_main.id, cls.company_2.id])],
            groups='base.group_user')
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        cls.foreign_team = cls.env['crm.team'].create(
            {'name': 'FOREIGN TEAM', 'company_id': cls.company_2.id})
        cls.local_team = cls.env['crm.team'].create(
            {'name': 'Local Team', 'company_id': cls.company_main.id})
        cls.env['crm.team.member'].create([
            {'crm_team_id': cls.foreign_team.id, 'user_id': cls.shared_user.id},
            {'crm_team_id': cls.local_team.id, 'user_id': cls.shared_user.id},
        ])
        cls.env.flush_all()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', False)

    def test_team_warning_hides_the_foreign_team(self):
        self.env.invalidate_all()
        warning = self.local_team.with_user(self.local_manager).member_warning
        self.assertNotIn('FOREIGN TEAM', warning or '')

    def test_membership_warning_hides_the_foreign_team(self):
        self.env.invalidate_all()
        membership = self.env['crm.team.member'].search([
            ('crm_team_id', '=', self.local_team.id),
            ('user_id', '=', self.shared_user.id)])
        self.assertNotIn('FOREIGN TEAM', membership.with_user(self.local_manager).member_warning or '')

    def test_a_visible_team_is_still_reported(self):
        """Guard against silencing the warning altogether."""
        self.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        self.env.invalidate_all()
        third = self.env['crm.team'].create(
            {'name': 'Third Local', 'company_id': self.company_main.id})
        self.env['crm.team.member'].create(
            {'crm_team_id': third.id, 'user_id': self.shared_user.id})
        self.env.flush_all()
        self.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', False)
        self.env.invalidate_all()
        warning = self.local_team.with_user(self.local_manager).member_warning
        self.assertIn('Third Local', warning or '')


class TestMemberIdsDependencies(TestSalesCommon):

    def test_member_ids_follows_a_membership_reassignment(self):
        """Moving a membership to another salesperson changes who is on the team."""
        self.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        self.env.invalidate_all()
        team = self.env['crm.team'].create({'name': 'Reassign', 'company_id': False})
        first = mail_new_test_user(
            self.env, login='reassign_1', name='Reassign One', groups='base.group_user')
        second = mail_new_test_user(
            self.env, login='reassign_2', name='Reassign Two', groups='base.group_user')
        membership = self.env['crm.team.member'].create(
            {'crm_team_id': team.id, 'user_id': first.id})
        self.env.flush_all()
        self.assertEqual(team.member_ids, first)

        membership.write({'user_id': second.id})
        self.assertEqual(team.member_ids, second)


class TestSalespersonDomain(TestSalesCommon):
    """The domain behind crm.team.member.user_id, which replaced a computed m2m.

    It excludes exactly the live members of the targeted team -- no more (mono
    mode used to hide every salesperson holding a membership anywhere, which the
    team form's own member_ids accepted) and no fewer.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', True)
        cls.team_a = cls.env['crm.team'].create({'name': 'DA', 'company_id': False})
        cls.team_b = cls.env['crm.team'].create({'name': 'DB', 'company_id': False})
        cls.in_a = mail_new_test_user(
            cls.env, login='dom_in_a', name='Dom In A', groups='base.group_user')
        cls.in_b = mail_new_test_user(
            cls.env, login='dom_in_b', name='Dom In B', groups='base.group_user')
        cls.free = mail_new_test_user(
            cls.env, login='dom_free', name='Dom Free', groups='base.group_user')
        cls.former = mail_new_test_user(
            cls.env, login='dom_former', name='Dom Former', groups='base.group_user')
        cls.env['crm.team.member'].create([
            {'user_id': cls.in_a.id, 'crm_team_id': cls.team_a.id},
            {'user_id': cls.in_b.id, 'crm_team_id': cls.team_b.id},
        ])
        cls.env['crm.team.member'].create({
            'user_id': cls.former.id, 'crm_team_id': cls.team_a.id}).action_archive()
        cls.env.flush_all()

    def _selectable(self, team_id):
        return self.env['res.users'].search([
            ('id', 'in', (self.in_a | self.in_b | self.free | self.former).ids),
            ('crm_team_member_ids', 'not any',
             [('active', '=', True), ('crm_team_id', '=', team_id)]),
        ])

    def test_excludes_only_live_members_of_the_target_team(self):
        selectable = self._selectable(self.team_a.id)
        self.assertNotIn(self.in_a, selectable)
        self.assertIn(self.in_b, selectable, "a member of another team stays selectable")
        self.assertIn(self.free, selectable)
        self.assertIn(self.former, selectable, "an archived membership does not exclude")

    def test_blank_team_excludes_nobody(self):
        selectable = self._selectable(False)
        for user in (self.in_a, self.in_b, self.free, self.former):
            self.assertIn(user, selectable)

    def test_is_the_same_in_both_membership_modes(self):
        multi = self._selectable(self.team_a.id)
        self.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', False)
        self.env.invalidate_all()
        self.assertEqual(self._selectable(self.team_a.id), multi)

    def test_mono_mode_transfer_goes_through(self):
        """The users this domain newly offers in mono mode must transfer cleanly.

        The old computed field hid, in mono mode, every salesperson already on a
        team -- so the Members form could not move anyone, while the team form's
        'member_ids' did it happily. Now that both offer the same people, the
        move has to end where _enforce_mono_membership says: one live membership.
        """
        self.env['ir.config_parameter'].sudo().set_param('sales_team.membership_multi', False)
        self.env.invalidate_all()
        self.assertIn(self.in_a, self._selectable(self.team_b.id),
                      "mono mode must offer a salesperson from another team")

        moved = self.env['crm.team.member'].create(
            {'crm_team_id': self.team_b.id, 'user_id': self.in_a.id})
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertTrue(moved.active)
        self.assertEqual(self.in_a.crm_team_ids, self.team_b,
                         "the salesperson ends on exactly one team")
        self.assertEqual(self.in_a.sale_team_id, self.team_b)

    def test_agrees_with_the_constraint_it_anticipates(self):
        """Everyone offered can be added; the one hidden cannot."""
        for user in self._selectable(self.team_a.id):
            with self.env.cr.savepoint():
                self.env['crm.team.member'].create(
                    {'crm_team_id': self.team_a.id, 'user_id': user.id})
                self.env.flush_all()
        with self.assertRaises(exceptions.ValidationError), self.env.cr.savepoint():
            self.env['crm.team.member'].create(
                {'crm_team_id': self.team_a.id, 'user_id': self.in_a.id})
            self.env.flush_all()
