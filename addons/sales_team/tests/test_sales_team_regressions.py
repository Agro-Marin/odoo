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
        """The active_test override exists for archived *users*; keep that.

        The state has to be built in two steps now that archiving a user
        cascades to its memberships whichever way it is written: the override
        this guards is about an archived *user* staying searchable, not about
        the cascade leaving memberships alone, and conflating the two made the
        test pass only for as long as ``write`` skipped the cascade.
        """
        self.user_sales_leads.with_context(active_test=False).write({'active': False})
        self.env.flush_all()
        self.other_membership.action_unarchive()
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertFalse(self.user_sales_leads.with_context(active_test=False).active)
        self.assertTrue(self.other_membership.active)
        matched = self.env['res.users'].with_context(active_test=False).search(
            [('crm_team_ids', 'in', self.other_team.ids)])
        self.assertIn(self.user_sales_leads, matched)

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
