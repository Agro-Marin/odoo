# -*- coding: utf-8 -*-
import random

from odoo.addons.crm.tests.test_crm_lead_assignment import TestLeadAssignCommon
from odoo.tests.common import tagged
from odoo.tools import mute_logger


@tagged('lead_assign', 'crm_performance', 'post_install', '-at_install')
class TestLeadAssignPerf(TestLeadAssignCommon):
    """ Test performances of lead assignment feature added in saas-14.2

    Assign process is a random process: randomizing teams leads to searching,
    assigning and de-duplicating leads in various order, so the counters below
    would vary from run to run -- which is why every test here fixes the seed.
    They do not vary. Two consecutive runs give character-identical counts, and
    the spread across the three install shapes (no demo / --with-demo / plus the
    six auto-installing enterprise bridges) is 0 to 4 queries.

    So the pins are the measured maximum of those three shapes, not a round
    number above them. They used to sit 38-42% over: 962 against 592, 552
    against 337, 5173 against 2999. A pin with two thousand queries of headroom
    cannot fail on anything, and none of them moved when `9dbee38e649` batched
    the duplicate lookups. Each pin below records what all three shapes measure,
    so the next reader knows which number the integer is.
    """

    def setUp(self):
        super().setUp()
        # patch registry to simulate a ready environment
        self.patch(self.env.registry, 'ready', True)
        # we don't use mock_mail_gateway thus want to mock smtp to test the stack
        self._mock_smtplib_connection()

    @mute_logger('odoo.models.unlink', 'odoo.addons.crm.models.crm_team', 'odoo.addons.crm.models.crm_team_member')
    def test_assign_perf_duplicates(self):
        """ Test assign process with duplicates on partner. Allow to ensure notably
        that de duplication is effectively performed. """
        # fix the seed and avoid randomness
        random.seed(1940)

        leads = self._create_leads_batch(
            lead_type='lead',
            user_ids=[False],
            partner_ids=[self.contact_1.id, self.contact_2.id, False, False, False],
            count=200
        )
        # commit probability and related fields
        leads.flush_recordset()
        self.assertInitialData()

        # assign probability to leads (bypass auto probability as purpose is not to test pls)
        leads = self.env['crm.lead'].search([('id', 'in', leads.ids)])  # ensure order
        for idx in range(0, 5):
            sliced_leads = leads[idx:len(leads):5]
            for lead in sliced_leads:
                lead.probability = (idx + 1) * 10 * ((int(lead.priority) + 1) / 2)
        # commit probability and related fields
        leads.flush_recordset()

        with self.with_user('user_sales_manager'):
            self.env.user._is_internal()  # warmup the cache to avoid inconsistency between community an enterprise
            # no demo 487 / --with-demo 487 / + enterprise bridges 491.
            # +7 over the 480/480/483 this pin was first set to, and all of it is
            # `opportunities_tail.check_access('write')` in `_merge_opportunity`:
            # one query per merge, seven merges here. Measured by deleting that
            # one line, which puts the number back to 480 exactly.
            with self.assertQueryCount(user_sales_manager=491):
                self.env['crm.team'].browse(self.sales_teams.ids)._action_assign_leads()

        # teams assign
        leads = self.env['crm.lead'].search([('id', 'in', leads.ids)])  # ensure order
        leads_st1 = leads.filtered_domain([('team_id', '=', self.sales_team_1.id)])
        leads_stc = leads.filtered_domain([('team_id', '=', self.sales_team_convert.id)])
        self.assertLessEqual(len(leads_st1), 128)
        self.assertLessEqual(len(leads_stc), 96)
        self.assertEqual(len(leads_st1) + len(leads_stc), len(leads))  # Make sure all lead are assigned

        # salespersons assign
        self.members.invalidate_model(['lead_month_count', 'lead_day_count'])
        self.assertMemberAssign(self.sales_team_1_m1, 2)  # 45 max on one month -> 2 daily
        self.assertMemberAssign(self.sales_team_1_m2, 1)  # 15 max on one month -> 1 daily
        self.assertMemberAssign(self.sales_team_1_m3, 1)  # 15 max on one month -> 1 daily
        self.assertMemberAssign(self.sales_team_convert_m1, 1)  # 30 max on one month -> 1 daily
        self.assertMemberAssign(self.sales_team_convert_m2, 2)  # 60 max on one month -> 2 daily

    @mute_logger('odoo.models.unlink', 'odoo.addons.crm.models.crm_team', 'odoo.addons.crm.models.crm_team_member')
    def test_assign_perf_no_duplicates(self):
        # fix the seed and avoid randomness
        random.seed(1945)

        leads = self._create_leads_batch(
            lead_type='lead',
            user_ids=[False],
            partner_ids=[False],
            count=100
        )
        # commit probability and related fields
        leads.flush_recordset()
        self.assertInitialData()

        # assign probability to leads (bypass auto probability as purpose is not to test pls)
        leads = self.env['crm.lead'].search([('id', 'in', leads.ids)])  # ensure order
        for idx in range(0, 5):
            sliced_leads = leads[idx:len(leads):5]
            for lead in sliced_leads:
                lead.probability = (idx + 1) * 10 * ((int(lead.priority) + 1) / 2)
        # commit probability and related fields
        leads.flush_recordset()

        with self.with_user('user_sales_manager'):
            # no demo 241 / --with-demo 242 / + enterprise bridges 241
            with self.assertQueryCount(user_sales_manager=242):
                self.env['crm.team'].browse(self.sales_teams.ids)._action_assign_leads()

        # teams assign
        leads = self.env['crm.lead'].search([('id', 'in', leads.ids)])  # ensure order
        leads_st1 = leads.filtered_domain([('team_id', '=', self.sales_team_1.id)])
        leads_stc = leads.filtered_domain([('team_id', '=', self.sales_team_convert.id)])
        self.assertEqual(len(leads_st1) + len(leads_stc), 100)

        # salespersons assign
        self.members.invalidate_model(['lead_month_count', 'lead_day_count'])
        self.assertMemberAssign(self.sales_team_1_m1, 2)  # 45 max on one month -> 2 daily
        self.assertMemberAssign(self.sales_team_1_m2, 1)  # 15 max on one month -> 1 daily
        self.assertMemberAssign(self.sales_team_1_m3, 1)  # 15 max on one month -> 1 daily
        self.assertMemberAssign(self.sales_team_convert_m1, 1)  # 30 max on one month -> 1 daily
        self.assertMemberAssign(self.sales_team_convert_m2, 2)  # 60 max on one month -> 2 daily

    @mute_logger('odoo.models.unlink', 'odoo.addons.crm.models.crm_team', 'odoo.addons.crm.models.crm_team_member')
    def test_assign_perf_populated(self):
        """ Test assignment on a more high volume oriented test set in order to
        have more insights on query counts. """
        # fix the seed and avoid randomness
        random.seed(1871)

        # create leads enough to have interesting counters
        _lead_count, _email_dup_count, _partner_count = 600, 50, 150
        leads = self._create_leads_batch(
            lead_type='lead',
            user_ids=[False],
            partner_count=_partner_count,
            country_ids=[self.env.ref('base.be').id, self.env.ref('base.fr').id, False],
            count=_lead_count,
            email_dup_count=_email_dup_count)
        # commit probability and related fields
        leads.flush_recordset()
        self.assertInitialData()

        # assign for one month, aka a lot
        self.env.ref('crm.ir_cron_crm_lead_assign').write({'interval_type': 'days', 'interval_number': 30})
        # create a third team
        sales_team_3 = self.env['crm.team'].create({
            'name': 'Sales Team 3',
            'sequence': 15,
            'alias_name': False,
            'use_leads': True,
            'use_opportunities': True,
            'company_id': False,
            'user_id': False,
            'assignment_domain': [('country_id', '!=', False)],
        })
        sales_team_3_m1 = self.env['crm.team.member'].create({
            'user_id': self.user_sales_manager.id,
            'crm_team_id': sales_team_3.id,
            'assignment_max': 60,
            'assignment_domain': False,
        })
        sales_team_3_m2 = self.env['crm.team.member'].create({
            'user_id': self.user_sales_leads.id,
            'crm_team_id': sales_team_3.id,
            'assignment_max': 60,
            'assignment_domain': False,
        })
        sales_team_3_m3 = self.env['crm.team.member'].create({
            'user_id': self.user_sales_salesman.id,
            'crm_team_id': sales_team_3.id,
            'assignment_max': 15,
            'assignment_domain': [('probability', '>=', 10)],
        })
        sales_teams = self.sales_teams | sales_team_3
        self.assertEqual(sum(team.assignment_max for team in sales_teams), 300)
        self.assertEqual(len(leads), 650)

        # assign probability to leads (bypass auto probability as purpose is not to test pls)
        leads = self.env['crm.lead'].search([('id', 'in', leads.ids)])  # ensure order
        for idx in range(0, 5):
            sliced_leads = leads[idx:len(leads):5]
            for lead in sliced_leads:
                lead.probability = (idx + 1) * 10 * ((int(lead.priority) + 1) / 2)
        # commit probability and related fields
        leads.flush_recordset()

        with self.with_user('user_sales_manager'):
            # no demo 2417 / --with-demo 2418 / + enterprise bridges 2421
            with self.assertQueryCount(user_sales_manager=2421):
                self.env['crm.team'].browse(sales_teams.ids)._action_assign_leads()

        # teams assign
        leads = self.env['crm.lead'].search([('id', 'in', leads.ids)])
        self.assertEqual(leads.team_id, sales_teams)
        self.assertEqual(leads.user_id, sales_teams.member_ids)

        # salespersons assign
        self.members.invalidate_model(['lead_month_count', 'lead_day_count'])
        self.assertMemberAssign(self.sales_team_1_m1, 2)  # 45 max on one month -> 2 daily
        self.assertMemberAssign(self.sales_team_1_m2, 1)  # 15 max on one month -> 1 daily
        self.assertMemberAssign(self.sales_team_1_m3, 1)  # 15 max on one month -> 1 daily
        self.assertMemberAssign(self.sales_team_convert_m1, 1)  # 30 max on one month -> 1 daily
        self.assertMemberAssign(self.sales_team_convert_m2, 2)  # 60 max on one month -> 2 daily
        self.assertMemberAssign(sales_team_3_m1, 2)  # 60 max on one month -> 2 daily
        self.assertMemberAssign(sales_team_3_m2, 2)  # 60 max on one month -> 2 daily
        self.assertMemberAssign(sales_team_3_m3, 1)  # 15 max on one month -> 1 daily

    @mute_logger('odoo.models.unlink', 'odoo.addons.crm.models.crm_team', 'odoo.addons.crm.models.crm_team_member')
    def test_allocate_leads_marginal_cost(self):
        """ What `_allocate_leads` costs per EXTRA lead, measured as a slope.

        The three absolute pins above cannot see this class of defect: they
        measure one population each, so a per-iteration query hides inside the
        total. A redundant `.exists()` in the allocation loop lived there
        unnoticed at 2 queries per allocated lead -- 66% of the whole call as
        those pins measure it -- and moved none of them when it was removed.

        Two populations, so cache warmth cannot make the assertion vacuous.

        ONE MODE ONLY, AND IT IS NOT THE ONE PRODUCTION RUNS. `_allocate_leads`
        reads `auto_commit = not modules.module.current_test`, and a
        TransactionCase cannot reach the other branch: committing from inside a
        test raises "Cannot commit or rollback a cursor from inside a test".
        Patching `commit` to a no-op would run the branch without the cache
        invalidation that is most of its cost, which is a worse lie than not
        measuring it. Measured out of band on 200 leads and two teams, the
        committing mode costs 1.7x the mode below (1060 queries against 608), so
        read this bound as a floor on the real one.
        """
        counts = {}
        for index, count in enumerate((2, 20)):
            random.seed(2026 + index)
            team = self.env['crm.team'].create({
                'alias_name': False,
                'assignment_domain': False,
                'assignment_optout': False,
                'name': f'Marginal Team {count}',
                'use_leads': True,
                'use_opportunities': True,
                'user_id': False,
            })
            self.env['crm.team.member'].create({
                'assignment_domain': False,
                'assignment_max': 200,
                'crm_team_id': team.id,
                'user_id': self.user_sales_manager.id,
            })
            self._create_leads_batch(
                lead_type='lead', user_ids=[False], partner_ids=[False],
                count=count, suffix=f'Marginal{count}')
            self.env.flush_all()
            self.env.invalidate_all()

            before = self.cr.sql_log_count
            team._allocate_leads(creation_delta_days=0)
            self.env.flush_all()
            counts[count] = self.cr.sql_log_count - before

        marginal = (counts[20] - counts[2]) / 18.0
        # 0.89 today. Restoring the `.exists()` that used to sit in the loop
        # takes it to 1.89, so the bound is set between the two rather than at a
        # round number: a single query added back per iteration fails here.
        self.assertLess(
            marginal, 1.5,
            f'_allocate_leads costs {marginal:.2f} queries per extra lead; '
            f'{counts}. Something in the per-lead loop is querying again.')
