"""Predictive lead scoring: the naive-Bayes model behind ``crm.lead.probability``.

Seven hundred lines of one subsystem, extracted from ``crm_lead.py`` where they
were 25% of the file and the source of its only ``c901`` offender and its two
longest functions. It reaches into the lead for ``team_id``, ``tag_ids`` and
``is_automated_probability`` and nothing else; everything it owns -- the
frequency table, the live-increment and full-rebuild paths, the cron and the
form tooltip -- is here. Splitting one model across concern files is the shape
``mail.message``, ``documents.document`` and ``approval.request`` already use.

The coupling that the split makes visible rather than fixes:
``_compute_probabilities``' ``@api.depends`` is computed from the
``crm.pls_fields`` config parameter, which is why
``models/ir_config_parameter.py`` calls ``registry._setup_models__`` from inside
a user request whenever that parameter is written.
"""

import logging
from collections import OrderedDict, defaultdict
from datetime import datetime
from itertools import batched

from odoo import fields, models, modules, tools
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

# Those values have been determined based on benchmark to minimise
# computation time, number of transaction and transaction time.
PLS_COMPUTE_BATCH_STEP = 50000  # PREFETCH_MAX = 1000 but larger cluster can speed up global computation
PLS_UPDATE_BATCH_STEP = 5000


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # ------------------------------------------------------------
    # PLS
    # ------------------------------------------------------------
    # Predictive lead scoring is computing the lead probability, based on won and lost leads from the past
    # Each won/lost lead increments a frequency table, where we store, for each field/value couple, the number of
    # won and lost leads.
    #   E.g. : A won lead from Belgium will increase the won count of the frequency country_id='Belgium' by 1.
    # The frequencies are split by team_id, so each team has its own frequencies environment. (Team A doesn't impact B)
    # There are two main ways to build the frequency table:
    #   - Live Increment: At each Won/lost, we increment directly the frequencies based on the lead values.
    #       Done right BEFORE writing the lead as won or lost.
    #       We consider a lead that will be marked as won or lost.
    #       Used each time a lead is won or lost, to ensure frequency table is always up to date
    #   - One shot Rebuild: empty the frequency table and rebuild it from scratch, based on every already won/lost leads
    #       Done during cron process.
    #       We consider all the leads that have been already won or lost.
    #       Used in one shot, when modifying the criteria to take into account (fields or reference date)

    # ---------------------------------
    # PLS: Probability Computation
    # ---------------------------------
    def _pls_get_naive_bayes_probabilities(self, batch_mode=False, is_tooltip=False):
        """
        In machine learning, naive Bayes classifiers (NBC) are a family of simple "probabilistic classifiers" based on
        applying Bayes theorem with strong (naive) independence assumptions between the variables taken into account.
        E.g: will TDE eat m&m's depending on his sleep status, the amount of work he has and the fullness of his stomach?
        As we use experience to compute the statistics, every day, we will register the variables state + the result.
        As the days pass, we will be able to determine, with more and more precision, if TDE will eat m&m's
        for a specific combination :
            - did sleep very well, a lot of work and stomach full > Will never happen !
            - didn't sleep at all, no work at all and empty stomach > for sure !
        Following Bayes' Theorem: the probability that an event occurs (to win) under certain conditions is proportional
        to the probability to win under each condition separately and the probability to win. We compute a 'Win score'
        -> P(Won | A∩B) ∝ P(A∩B | Won)*P(Won) OR S(Won | A∩B) = P(A∩B | Won)*P(Won)
        To compute a percentage of probability to win, we also compute the 'Lost score' that is proportional to the
        probability to lose under each condition separately and the probability to lose.
        -> Probability =  S(Won | A∩B) / ( S(Won | A∩B) + S(Lost | A∩B) )
        See https://www.youtube.com/watch?v=CPqOCI0ahss can help to get a quick and simple example.
        One issue about NBC is when a event occurence is never observed.
        E.g: if when TDE has an empty stomach, he always eat m&m's, than the "not eating m&m's when empty stomach' event
        will never be observed.
        This is called 'zero frequency' and that leads to division (or at least multiplication) by zero.
        To avoid this, we add 0.1 in each frequency. With few data, the computation is than not really realistic.
        The more we have records to analyse, the more the estimation will be precise.

        :param bool is_tooltip: If true, method recomputes the probability of self, that should be a singleton, and
            also returns a dict containing probability, and a list of all (score, field, value) triplets for all value of
            PLS fields that impact the computation of the probability. Score is a simple value that indicates whether the
            impact is positive (>.5) or negative (<.5). See method update_and_get_pls_tooltip_data, or test_pls_tooltip_data for
            more details

        :return: 2-tuple ``(probabilities_by_lead_id, tooltip_data)``. Both early
          exits below return the pair too: they used to hand back the bare dict,
          and every caller unpacks two values, so an empty recordset raised
          ``ValueError: not enough values to unpack``.
        """
        lead_probabilities = {}
        if not self:
            return lead_probabilities, {}

        # Initialize tooltip data. A returned 0.00 probability means computation was not possible.
        tooltip_data = {}
        if is_tooltip:
            self.ensure_one()
            tooltip_data = {
                'probability': 0.0,
                'scores': [],
            }

        # Get all leads values, no matter the team_id
        domain = []
        if batch_mode:
            domain = [
                ('active', '=', True),
                ('id', 'in', self.ids),
                ('won_status', '=', 'pending'),
            ]
        leads_values_dict = self._pls_get_lead_pls_values(domain=domain)

        if not leads_values_dict:
            return lead_probabilities, tooltip_data

        # Get unique couples to search in frequency table and won leads.
        leads_fields = set()  # keep unique fields, as a lead can have multiple tag_ids
        won_leads = set()
        won_stage_ids = self.env['crm.stage'].search([('is_won', '=', True)]).ids
        for lead_id, values in leads_values_dict.items():
            for field, value in values['values']:
                if field == 'stage_id' and value in won_stage_ids:
                    won_leads.add(lead_id)
                leads_fields.add(field)
        leads_fields = sorted(leads_fields)
        # get all variable related records from frequency table, no matter the team_id
        frequencies = self.env['crm.lead.scoring.frequency'].search([('variable', 'in', list(leads_fields))], order="team_id asc, id")

        # get all team_ids from frequencies
        frequency_teams = frequencies.mapped('team_id')
        frequency_team_ids = [team.id for team in frequency_teams]

        # restrict to frequencies of lead team if any exist.
        if is_tooltip and self.team_id & frequency_teams:
            frequency_team_ids = [self.team_id.id]
            frequencies = frequencies.filtered(
                lambda frequency: frequency.team_id & self.team_id
            )

        # 1. Compute each variable value count individually
        # regroup each variable to be able to compute their own probabilities
        # As all the variable does not enter into account (as we reject unset values in the process)
        # each value probability must be computed only with their own variable related total count
        # special case: for lead for which team_id is not in frequency table or lead with no team_id,
        # we consider all the records, independently from team_id (this is why we add a result[-1])
        result = dict((team_id, dict((field, dict(won_total=0, lost_total=0)) for field in leads_fields)) for team_id in frequency_team_ids)
        result[-1] = dict((field, dict(won_total=0, lost_total=0)) for field in leads_fields)
        for frequency in frequencies:
            field = frequency['variable']
            value = frequency['value']  # This is always a string

            # To avoid that a tag take too much importance if its subset is too small,
            # we ignore the tag frequencies if we have less than 50 won or lost for this tag.
            if field == 'tag_id' and (frequency['won_count'] + frequency['lost_count']) < 50:
                continue

            if frequency.team_id:
                team_result = result[frequency.team_id.id]
                team_result[field][value] = {'won': frequency['won_count'], 'lost': frequency['lost_count']}
                team_result[field]['won_total'] += frequency['won_count']
                team_result[field]['lost_total'] += frequency['lost_count']

            if value not in result[-1][field]:
                result[-1][field][value] = {'won': 0, 'lost': 0}
            result[-1][field][value]['won'] += frequency['won_count']
            result[-1][field][value]['lost'] += frequency['lost_count']
            result[-1][field]['won_total'] += frequency['won_count']
            result[-1][field]['lost_total'] += frequency['lost_count']

        # Get all won, lost and total count for all records in frequencies per team_id.
        # The reference stage does not depend on the team, so it is resolved once
        # here rather than re-searched for every team in the loop.
        first_stage_id = self._pls_first_stage()
        for team_id in result:
            result[team_id]['team_won'], \
            result[team_id]['team_lost'], \
            result[team_id]['team_total'] = self._pls_get_won_lost_total_count(
                result[team_id], first_stage_id=first_stage_id)

        # Priors per team, resolved before the loop rather than cached across its
        # iterations. The cache this replaces advanced its key BEFORE the guard
        # below and then `continue`d, so the next lead of an unscoreable team
        # took the `same team` fast path and multiplied the PREVIOUS team's
        # priors: a team with four lost leads and no won one scored 98.39%.
        # See `test_pls_unscoreable_team_does_not_inherit_another_team_prior`.
        team_priors = {}
        for team_id, team_result in result.items():
            team_won, team_lost = team_result['team_won'], team_result['team_lost']
            # if one count = 0, we cannot compute lead probability for that team
            if team_won and team_lost:
                team_total = team_result['team_total']
                team_priors[team_id] = (
                    team_won, team_lost, team_won / team_total, team_lost / team_total)

        for lead_id, lead_values in leads_values_dict.items():
            # if stage_id is null, return 0 and bypass computation
            lead_fields = [value[0] for value in lead_values.get('values', [])]
            if not 'stage_id' in lead_fields:
                lead_probabilities[lead_id] = 0
                continue
            # if lead stage is won, return 100
            elif lead_id in won_leads:
                lead_probabilities[lead_id] = 100
                continue

            # team_id not in frequency Table -> convert to -1
            lead_team_id = lead_values['team_id'] if lead_values['team_id'] in result else -1
            prior = team_priors.get(lead_team_id)
            if prior is None:
                continue
            team_won, team_lost, p_won, p_lost = prior

            # 2. Compute won and lost score using each variable's individual probability
            s_lead_won, s_lead_lost = p_won, p_lost
            for field, value in lead_values['values']:
                field_result = result[lead_team_id].get(field)
                value = value.origin if hasattr(value, 'origin') else value
                value_result = field_result.get(str(value)) if field_result else False
                if value_result:
                    total_won = team_won if field == 'stage_id' else field_result['won_total']
                    total_lost = team_lost if field == 'stage_id' else field_result['lost_total']
                    # if one count = 0, we cannot compute lead probability
                    if not total_won or not total_lost:
                        continue
                    p_field_value_won = value_result['won'] / total_won
                    p_field_value_lost = value_result['lost'] / total_lost
                    s_lead_won *= p_field_value_won
                    s_lead_lost *= p_field_value_lost

                    if is_tooltip:
                        score = (
                            1 - p_field_value_lost if field == 'stage_id'
                            else p_field_value_won / (p_field_value_won + p_field_value_lost)
                        )
                        tooltip_data['scores'].append((score, field, value))
            # 3. Compute Probability to win
            probability = s_lead_won / (s_lead_won + s_lead_lost)
            lead_probabilities[lead_id] = min(max(round(100 * probability, 2), 0.01), 99.99)

        if tooltip_data and self.id in lead_probabilities:
            tooltip_data['probability'] = lead_probabilities[self.id]

        return lead_probabilities, tooltip_data

    # ---------------------------------
    # PLS: Live Increment
    # ---------------------------------
    def _pls_increment_frequencies(self, from_state=None, to_state=None):
        """
        When losing or winning a lead, this method is called to increment each PLS parameter related to the lead
        in won_count (if won) or in lost_count (if lost).

        This method is also used when reactivating a mistakenly lost lead (using the decrement argument).
        In this case, the lost count should be de-increment by 1 for each PLS parameter linked to the lead.

        Live increment must be done before writing the new values because we need to know the state change (from and to).
        This would not be an issue for the reach won or reach lost as we just need to increment the frequencies with the
        final state of the lead.
        This issue is when the lead leaves a closed state because once the new values have been writen, we do not know
        what was the previous state that we need to decrement.
        This is why 'is_won' and 'decrement' parameters are used to describe the from / to change of its state.
        """
        new_frequencies_by_team, existing_frequencies_by_team = self._pls_prepare_update_frequency_table(target_state=from_state or to_state)

        # update frequency table
        self._pls_update_frequency_table(new_frequencies_by_team, 1 if to_state else -1,
                                         existing_frequencies_by_team=existing_frequencies_by_team)

    # ---------------------------------
    # PLS: One shot rebuild
    # ---------------------------------
    def _cron_update_automated_probabilities(self):
        """ This cron will :
          - rebuild the lead scoring frequency table
          - recompute all the automated_probability and align probability if both were aligned
        """
        cron_start_date = datetime.now()
        self._rebuild_pls_frequency_table()
        self._update_automated_probabilities()
        _logger.info("Predictive Lead Scoring : Cron duration = %d seconds" % ((datetime.now() - cron_start_date).total_seconds()))

    def _rebuild_pls_frequency_table(self):
        # Clear the frequencies table (in sql to speed up the cron)
        try:
            self.browse().check_access('unlink')
        except AccessError:
            raise UserError(_("You don't have the access needed to run this cron."))
        else:
            self.env.cr.execute('TRUNCATE TABLE crm_lead_scoring_frequency')

        new_frequencies_by_team, unused = self._pls_prepare_update_frequency_table(rebuild=True)
        # update frequency table
        self._pls_update_frequency_table(new_frequencies_by_team, 1)

        _logger.info("Predictive Lead Scoring : crm.lead.scoring.frequency table rebuilt")

    def _update_automated_probabilities(self):
        """ Recompute all the automated_probability (and align probability if both were aligned) for all the leads
        that are active (not won, nor lost).

        For performance matter, as there can be a huge amount of leads to recompute, this cron proceed by batch.
        Each batch is performed into its own transaction, in order to minimise the lock time on the lead table
        (and to avoid complete lock if there was only 1 transaction that would last for too long -> several minutes).
        If a concurrent update occurs, it will simply be put in the queue to get the lock.
        """
        pls_start_date = self._pls_get_safe_start_date()
        if not pls_start_date:
            return

        # 1. Get all the leads to recompute created after pls_start_date that are nor won nor lost
        pending_lead_domain = [
            ('stage_id', '!=', False),
            ('create_date', '>=', pls_start_date),
            ('won_status', '=', 'pending'),
        ]
        leads_to_update = self.env['crm.lead'].search(pending_lead_domain)
        leads_to_update_count = len(leads_to_update)

        # 2. Compute by batch to avoid memory error
        lead_probabilities = {}
        for i in range(0, leads_to_update_count, PLS_COMPUTE_BATCH_STEP):
            leads_to_update_part = leads_to_update[i:i + PLS_COMPUTE_BATCH_STEP]
            batch_probabilites, _unused = leads_to_update_part._pls_get_naive_bayes_probabilities(batch_mode=True)
            lead_probabilities.update(batch_probabilites)
        _logger.info("Predictive Lead Scoring : New automated probabilities computed")

        # 3. Group by new probability to reduce server roundtrips when executing the update
        probability_leads = defaultdict(list)
        for lead_id, probability in sorted(lead_probabilities.items()):
            probability_leads[probability].append(lead_id)

        # 4. Update automated_probability (+ probability if both were equal)
        update_sql = """UPDATE crm_lead
                        SET automated_probability = %s,
                            probability = CASE WHEN (probability = automated_probability OR probability is null)
                                               THEN (%s)
                                               ELSE (probability)
                                          END
                        WHERE id = ANY(%s)"""

        # Update by a maximum number of leads at the same time, one batch by transaction :
        # - avoid memory errors
        # - avoid blocking the table for too long with a too big transaction
        transactions_count, transactions_failed_count = 0, 0
        cron_update_lead_start_date = datetime.now()
        auto_commit = not modules.module.current_test
        self.flush_model()
        for probability, probability_lead_ids in probability_leads.items():
            for lead_ids_current in batched(probability_lead_ids, PLS_UPDATE_BATCH_STEP):
                transactions_count += 1
                try:
                    self.env.cr.execute(update_sql, (probability, probability, list(lead_ids_current)))
                    # auto-commit except in testing mode
                    if auto_commit:
                        self.env.cr.commit()
                except Exception as e:
                    _logger.warning("Predictive Lead Scoring : update transaction failed. Error: %s" % e)
                    transactions_failed_count += 1
        self.invalidate_model()

        _logger.info(
            "Predictive Lead Scoring : All automated probabilities updated (%d leads / %d transactions (%d failed) / %d seconds)" % (
                leads_to_update_count,
                transactions_count,
                transactions_failed_count,
                (datetime.now() - cron_update_lead_start_date).total_seconds(),
            )
        )

    # ---------------------------------
    # PLS: Common parts for both mode
    # ---------------------------------
    def _pls_prepare_update_frequency_table(self, rebuild=False, target_state=False):
        """
        This method is common to Live Increment or Full Rebuild mode, as it shares the main steps.
        This method will prepare the frequency dict needed to update the frequency table:
            - New frequencies: frequencies that we need to add in the frequency table.
            - Existing frequencies: frequencies that are already in the frequency table.
        In rebuild mode, only the new frequencies are needed as existing frequencies are truncated.
        For each team, each dict contains the frequency in won and lost for each field/value couple
        of the target leads.
        Target leads are :
            - in Live increment mode : given ongoing leads (self)
            - in Full rebuild mode : all the closed (won and lost) leads in the DB.
        During the frequencies update, with both new and existing frequencies, we can split frequencies to update
        and frequencies to add. If a field/value couple already exists in the frequency table, we just update it.
        Otherwise, we need to insert a new one.
        """
        # Keep eligible leads
        pls_start_date = self._pls_get_safe_start_date()
        if not pls_start_date:
            return {}, {}

        if rebuild:  # rebuild will treat every closed lead in DB, increment will treat current ongoing leads
            pls_leads = self
        else:
            # Only treat leads created after the PLS start Date
            pls_leads = self.filtered(
                lambda lead: fields.Date.to_date(pls_start_date) <= fields.Date.to_date(lead.create_date))
            if not pls_leads:
                return {}, {}

        # Extract target leads values
        if rebuild:  # rebuild is ok
            domain = [
                ('create_date', '>=', pls_start_date),
                ('won_status', 'in', ['lost', 'won']),
              ]
            team_ids = self.env['crm.team'].with_context(active_test=False).search([]).ids + [0]  # If team_id is unset, consider it as team 0
        else:  # increment
            domain = [('id', 'in', pls_leads.ids)]
            team_ids = pls_leads.mapped('team_id').ids + [0]

        leads_values_dict = pls_leads._pls_get_lead_pls_values(domain=domain)

        # split leads values by team_id
        # get current frequencies related to the target leads
        leads_frequency_values_by_team = dict((team_id, []) for team_id in team_ids)
        leads_pls_fields = set()  # ensure to keep each field unique (can have multiple tag_id leads_values_dict)
        for values in leads_values_dict.values():
            team_id = values.get('team_id', 0)  # If team_id is unset, consider it as team 0
            lead_frequency_values = {'count': 1}
            for field, value in values['values']:
                if field != "probability":  # was added to lead values in batch mode to know won/lost state, but is not a pls fields.
                    leads_pls_fields.add(field)
                else:  # extract lead probability - needed to increment tag_id frequency. (proba always before tag_id)
                    lead_probability = value
                if field == 'tag_id':  # handle tag_id separatelly (as in One Shot rebuild mode)
                    leads_frequency_values_by_team[team_id].append({field: value, 'count': 1, 'probability': lead_probability})
                else:
                    lead_frequency_values[field] = value
            leads_frequency_values_by_team[team_id].append(lead_frequency_values)
        leads_pls_fields = sorted(leads_pls_fields)

        # get new frequencies
        new_frequencies_by_team = {}
        for team_id in team_ids:
            # prepare fields and tag values for leads by team
            new_frequencies_by_team[team_id] = self._pls_prepare_frequencies(
                leads_frequency_values_by_team[team_id], leads_pls_fields, target_state=target_state)

        # get existing frequencies
        existing_frequencies_by_team = {}
        if not rebuild:  # there is no existing frequency in rebuild mode as they were all deleted.
            # read all fields to get everything in memory in one query (instead of having query + prefetch)
            existing_frequencies = self.env['crm.lead.scoring.frequency'].search_read(
                ['&', ('variable', 'in', leads_pls_fields),
                      '|', ('team_id', 'in', pls_leads.mapped('team_id').ids), ('team_id', '=', False)])
            for frequency in existing_frequencies:
                team_id = frequency['team_id'][0] if frequency.get('team_id') else 0
                if team_id not in existing_frequencies_by_team:
                    existing_frequencies_by_team[team_id] = dict((field, {}) for field in leads_pls_fields)

                existing_frequencies_by_team[team_id][frequency['variable']][frequency['value']] = {
                    'frequency_id': frequency['id'],
                    'won': frequency['won_count'],
                    'lost': frequency['lost_count']
                }

        return new_frequencies_by_team, existing_frequencies_by_team

    def _pls_update_frequency_table(self, new_frequencies_by_team, step, existing_frequencies_by_team=None):
        """ Create / update the frequency table in a cross company way, per team_id"""
        values_to_update = {}
        values_to_create = []
        if not existing_frequencies_by_team:
            existing_frequencies_by_team = {}
        # build the create multi + frequencies to update
        for team_id, new_frequencies in new_frequencies_by_team.items():
            for field, value in new_frequencies.items():
                # frequency already present ?
                current_frequencies = existing_frequencies_by_team.get(team_id, {})
                for param, result in value.items():
                    current_frequency_for_couple = current_frequencies.get(field, {}).get(param, {})
                    # If frequency already present : UPDATE IT
                    if current_frequency_for_couple:
                        new_won = current_frequency_for_couple['won'] + (result['won'] * step)
                        new_lost = current_frequency_for_couple['lost'] + (result['lost'] * step)
                        # ensure to have always positive frequencies
                        values_to_update[current_frequency_for_couple['frequency_id']] = {
                            'won_count': new_won if new_won > 0 else 0.1,
                            'lost_count': new_lost if new_lost > 0 else 0.1
                        }
                        continue

                    # Else, CREATE a new frequency record.
                    # We add + 0.1 in won and lost counts to avoid zero frequency issues
                    # should be +1 but it weights too much on small recordset.
                    values_to_create.append({
                        'variable': field,
                        'value': param,
                        'won_count': result['won'] + 0.1,
                        'lost_count': result['lost'] + 0.1,
                        'team_id': team_id if team_id else None  # team_id = 0 means no team_id
                    })

        LeadScoringFrequency = self.env['crm.lead.scoring.frequency'].sudo()
        for frequency_id, values in values_to_update.items():
            LeadScoringFrequency.browse(frequency_id).write(values)

        if values_to_create:
            LeadScoringFrequency.create(values_to_create)

    # ---------------------------------
    # Utility Tools for PLS
    # ---------------------------------

    # PLS:  Config Parameters
    # ---------------------
    def _pls_get_safe_start_date(self):
        """ As config_parameters does not accept Date field,
            we get directly the date formated string stored into the Char config field,
            as we directly use this string in the sql queries.
            To avoid sql injections when using this config param,
            we ensure the date string can be effectively a date."""
        str_date = self.env['ir.config_parameter'].sudo().get_param('crm.pls_start_date')
        if not fields.Date.to_date(str_date):
            return False
        return str_date

    def _pls_get_safe_fields(self):
        """ As config_parameters does not accept M2M field,
            we the fields from the formated string stored into the Char config field.
            To avoid sql injections when using that list, we return only the fields
            that are defined on the model. """
        pls_fields_config = self.env['ir.config_parameter'].sudo().get_param('crm.pls_fields')
        pls_fields = pls_fields_config.split(',') if pls_fields_config else []
        pls_safe_fields = [field for field in pls_fields if field in self._fields.keys()]
        return pls_safe_fields

    # Compute Automated Probability Tools
    # -----------------------------------
    def _pls_first_stage(self):
        """ The first team-agnostic stage, used as the reference point for won /
        lost counts. It is the same for every team, so callers looping over teams
        must resolve it once and pass it to ``_pls_get_won_lost_total_count``. """
        return self.env['crm.stage'].search([('team_ids', '=', False)], order='sequence, id', limit=1)

    def _pls_get_won_lost_total_count(self, team_results, first_stage_id=None):
        """ Get all won and all lost + total :
               first stage can be used to know how many lost and won there is
               as won count are equals for all stage
               and first stage is always incremented in lost_count
        :param team_results:
        :param first_stage_id: reference stage, see ``_pls_first_stage``; resolved
          on demand when not given, so single-team callers keep working unchanged
        :return: won count, lost count and total count for all records in frequencies
        """
        # TODO : check if we need to handle specific team_id stages [for lost count] (if first stage in sequence is team_specific)
        if first_stage_id is None:
            first_stage_id = self._pls_first_stage()
        if str(first_stage_id.id) not in team_results.get('stage_id', []):
            return 0, 0, 0
        stage_result = team_results['stage_id'][str(first_stage_id.id)]
        return stage_result['won'], stage_result['lost'], stage_result['won'] + stage_result['lost']

    # PLS: Rebuild Frequency Table Tools
    # ----------------------------------
    def _pls_prepare_frequencies(self, lead_values, leads_pls_fields, target_state=None):
        """new state is used when getting frequencies for leads that are changing to lost or won.
        Stays none if we are checking frequencies for leads already won or lost."""
        pls_fields = leads_pls_fields.copy()
        frequencies = dict((field, {}) for field in pls_fields)

        stage_ids = self.env['crm.stage'].search_read([], ['sequence', 'name', 'id'], order='sequence, id')
        stage_sequences = {stage['id']: stage['sequence'] for stage in stage_ids}

        # Increment won / lost frequencies by criteria (field / value couple)
        for values in lead_values:
            if target_state:  # ignore probability values if target state (as probability is the old value)
                won_count = values['count'] if target_state == 'won' else 0
                lost_count = values['count'] if target_state == 'lost' else 0
            else:
                won_count = values['count'] if values.get('probability', 0) == 100 else 0
                lost_count = values['count'] if values.get('probability', 1) == 0  else 0

            if 'tag_id' in values:
                frequencies = self._pls_increment_frequency_dict(frequencies, 'tag_id', values['tag_id'], won_count, lost_count)
                continue

            # Else, treat other fields
            if 'tag_id' in pls_fields:  # tag_id already treated here above.
                pls_fields.remove('tag_id')
            for field in pls_fields:
                if field not in values:
                    continue
                value = values[field]
                if value or field in ('email_state', 'phone_state'):
                    if field == 'stage_id':
                        if won_count:  # increment all stages if won
                            stages_to_increment = [stage['id'] for stage in stage_ids]
                        else:  # increment only current + previous stages if lost
                            current_stage_sequence = stage_sequences[value]
                            stages_to_increment = [stage['id'] for stage in stage_ids if stage['sequence'] <= current_stage_sequence]
                        for stage_id in stages_to_increment:
                            frequencies = self._pls_increment_frequency_dict(frequencies, field, stage_id, won_count, lost_count)
                    else:
                        frequencies = self._pls_increment_frequency_dict(frequencies, field, value, won_count, lost_count)

        return frequencies

    def _pls_increment_frequency_dict(self, frequencies, field, value, won, lost):
        value = str(value)  # Ensure we will always compare strings.
        if value not in frequencies[field]:
            frequencies[field][value] = {'won': won, 'lost': lost}
        else:
            frequencies[field][value]['won'] += won
            frequencies[field][value]['lost'] += lost
        return frequencies

    # Common PLS Tools
    # ----------------
    def _pls_get_lead_pls_values(self, domain=None):
        """
        This methods builds a dict where, for each lead in self or matching the given domain,
        we will get a list of field/value couple.
        Due to onchange and create, we don't always have the id of the lead to recompute.
        When we update few records (one, typically) with onchanges, we build the lead_values (= couple field/value)
        using the ORM.
        To speed up the computation and avoid making too much DB read inside loops,
        we can give a domain to make sql queries to bypass the ORM.
        This domain will be used in sql queries to get the values for every lead matching the domain.
        :param domain: If set, we get all the leads values via unique sql queries (one for tags, one for other fields),
                            using the given domain on leads.
                       If not set, get lead values lead by lead using the ORM.
        :return: {lead_id: [(field1: value1), (field2: value2), ...], ...}
        """
        leads_values_dict = OrderedDict()
        pls_fields = ["stage_id", "team_id"] + self._pls_get_safe_fields()

        # Check if tag_ids is in the pls_fields and removed it from the list. The tags will be managed separately.
        use_tags = 'tag_ids' in pls_fields
        if use_tags:
            pls_fields.remove('tag_ids')

        if domain:
            # Get leads values
            self.flush_model()
            # active_test = False as domain should take active into 'active' field it self
            query = self.env['crm.lead'].with_context(active_test=False)._search(domain, bypass_access=True)
            table = query.table
            query.order = SQL("%(table)s.team_id asc, %(table)s.id desc", table=SQL.identifier(table))
            sql_fields = [SQL.identifier(field) for field in pls_fields]
            self.env.cr.execute(query.select(
                SQL("id"),
                SQL("probability"),
                *sql_fields,
            ))
            lead_results = self.env.cr.dictfetchall()

            if use_tags:
                # Get tags values
                tag_rel_alias = query.left_join(table, 'id', 'crm_tag_rel', 'lead_id', 'crm_tag_rel')
                tag_alias = query.left_join(tag_rel_alias, 'tag_id', 'crm_tag', 'id', 'crm_tag')
                self.env.cr.execute(query.select(
                    SQL("%s AS lead_id", SQL.identifier(table, "id")),
                    SQL("%s AS tag_id", SQL.identifier(tag_alias, "id")),
                ))
                tag_results = self.env.cr.dictfetchall()
            else:
                tag_results = []

            # get all (variable, value) couple for all in self
            for lead in lead_results:
                lead_values = []
                for field in pls_fields + ['probability']:  # add probability as used in _pls_prepare_frequencies (needed in rebuild mode)
                    value = lead[field]
                    if field == 'team_id':  # ignore team_id as stored separately in leads_values_dict[lead_id][team_id]
                        continue
                    if value or field == 'probability':  # 0 is a correct value for probability
                        lead_values.append((field, value))
                    elif field in ('email_state', 'phone_state'):  # As ORM reads 'None' as 'False', do the same here
                        lead_values.append((field, False))
                    leads_values_dict[lead['id']] = {'values': lead_values, 'team_id': lead['team_id'] or 0}

            for tag in tag_results:
                if tag['tag_id']:
                    leads_values_dict[tag['lead_id']]['values'].append(('tag_id', tag['tag_id']))
            return leads_values_dict
        else:
            for lead in self:
                lead_values = []
                for field in pls_fields:
                    if field == 'team_id':  # ignore team_id as stored separately in leads_values_dict[lead_id][team_id]
                        continue
                    value = lead[field].id if isinstance(lead[field], models.BaseModel) else lead[field]
                    if value or field in ('email_state', 'phone_state'):
                        lead_values.append((field, value))
                if use_tags:
                    for tag in lead.tag_ids:
                        lead_values.append(('tag_id', tag.id))
                leads_values_dict[lead.id] = {'values': lead_values, 'team_id': lead['team_id'].id}
            return leads_values_dict

    # PLS Backend Tooltip
    # -------------------
    def update_and_get_pls_tooltip_data(self):
        """
        Compute and return all necessary information to render CrmPlsTooltip, displayed when
        pressing the small AI button, located next to the label of probability when automated,
        in the crm.lead form view. This method first replaces ids with display names of relational
        fields before returning data, then also recomputes probabilities and writes them on self.

        :returns:

            ::
                {
                    low_3_data: list of field-value couples for lowest 3 criterions, lowest first
                    probability: numerical value, used for display on tooltip
                    team_name: string, name of lead team if any
                    top_3_data: list of field-value couples for top 3 criterions, highest first
                }

        :rtype: dict
        """
        self.ensure_one()
        _unused, tooltip_data = self._pls_get_naive_bayes_probabilities(is_tooltip=True)
        sorted_scores_with_name = []

        # We want to display names in the tooltip, not ids.
        # The last element in tuple is only used for tags to ensure same color in tooltip.
        for score, field, value in sorted(tooltip_data['scores']):
            # Skip nonsense results for phone and email states. May happen in a db having a few leads.
            if field in ['phone_state', 'email_state']:
                if value in [False, 'incorrect'] and tools.float_compare(score, 0.50, 2) > 0:
                    continue
                if value == 'correct' and tools.float_compare(score, 0.50, 2) < 0:
                    continue
            if field == 'tag_id':
                tag = self.tag_ids.filtered(lambda tag: tag.id == value)
                sorted_scores_with_name.append((score, field, tag.display_name, tag.color))
            elif isinstance(self[field], models.BaseModel):
                sorted_scores_with_name.append((score, field, self[field].display_name, False))
            else:
                sorted_scores_with_name.append((score, field, str(value), False))

        # Update automated probability, as it may have changed since last computation
        # -> avoids differences in display between tooltip and record. A 0.00 probability implies
        # that the computation was not possible. Sample data will be used instead.
        probability_values = {'automated_probability': tooltip_data['probability']}
        if self.is_automated_probability:
            probability_values['probability'] = tooltip_data['probability']
        self.write(probability_values)

        # Sample values if probability could not be computed. If it was, but if all scores
        # were excluded above, a placeholder will be used instead in the tooltip.
        if tools.float_is_zero(tooltip_data['probability'], 2):
            sorted_scores_with_name = [
                (.1, 'email_state', False, False),
                (.2, 'tag_id', _('Exploration'), 4),
                (.3, 'stage_id', _('New'), False),
                (.7, 'phone_state', 'correct', False),
                (.8, 'country_id', _('Belgium'), False),
                (.9, 'tag_id', _('Consulting'), 3),
            ]

        return {
            'low_3_data': [
                {
                    'field': element[1],
                    'value': element[2],
                    'color': element[3]
                } for element in sorted_scores_with_name[:3] if tools.float_compare(element[0], 0.50, 2) < 0
            ],
            'probability': tooltip_data['probability'],
            'team_name': self.team_id.display_name,
            'top_3_data': [
                {
                    'field': element[1],
                    'value': element[2],
                    'color': element[3]
                } for element in sorted_scores_with_name[::-1][:3] if tools.float_compare(element[0], 0.50, 2) > 0
            ],
        }
