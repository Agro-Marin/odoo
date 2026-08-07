# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.fields import NEGATIVE_CONDITION_OPERATORS


class ResUsers(models.Model):
    _inherit = 'res.users'

    crm_team_ids = fields.Many2many(
        'crm.team', string='Sales Teams', copy=False, readonly=True,
        compute='_compute_crm_team_ids', search='_search_crm_team_ids')
    crm_team_member_ids = fields.One2many('crm.team.member', 'user_id', string='Sales Team Members')
    sale_team_id = fields.Many2one(
        'crm.team', string='User Sales Team', compute='_compute_sale_team_id',
        readonly=True, store=True,
        help="Main user sales team. Used notably for pipeline, or to set sales team in invoicing or subscription.")

    @api.depends('crm_team_member_ids.active', 'crm_team_member_ids.crm_team_id')
    def _compute_crm_team_ids(self):
        for user in self:
            # filtered() rather than the o2m alone: whether the o2m hides archived
            # memberships follows the caller's active_test, and this field feeds
            # record rules, so it must mean the same thing in every context
            user.crm_team_ids = user.crm_team_member_ids.filtered('active').crm_team_id

    def _search_crm_team_ids(self, operator, value):
        # Equivalent to `[('crm_team_member_ids.crm_team_id', operator, value)]`,
        # but we inline the ids directly to simplify final queries and improve performance,
        # as it's part of a few ir.rules.
        # If we're going to inject too many `ids`, we fall back on the default behavior
        # to avoid a performance regression.
        # The active leaf is explicit: `active_test=False` is meant to keep archived
        # *users* searchable, but it also reached the traversed memberships, so a
        # salesperson who had left a team still matched it -- and sale's team record
        # rules are written on this side of the relation, which handed their orders
        # and invoices to their former teammates for good.
        IN_MAX = 10_000
        live = [('active', '=', True)]

        if operator in NEGATIVE_CONDITION_OPERATORS:
            # Hand the negation back to the ORM, which negates the whole positive
            # domain. Pushing the operator inside the 'any' instead asks "has SOME
            # live membership whose team is not X", where the field means "has NO
            # live membership whose team is X" -- so a salesperson on teams A and B
            # matched `crm_team_ids not in [A]`.
            return NotImplemented

        if value is False or (operator == 'in' and not [v for v in value if v is not False]):
            # "no sales team" is the absence of any live membership; asking for a
            # membership whose (required) team is False matched nobody, ever.
            return [('crm_team_member_ids', 'not any', live)]

        domain = [('crm_team_member_ids', 'any', live + [('crm_team_id', operator, value)])]
        user_ids = self.env['res.users'].with_context(active_test=False)._search(domain, limit=IN_MAX).get_result_ids()
        if len(user_ids) < IN_MAX:
            return [('id', 'in', user_ids)]

        return domain

    @api.depends('crm_team_member_ids.crm_team_id', 'crm_team_member_ids.create_date', 'crm_team_member_ids.active')
    def _compute_sale_team_id(self):
        for user in self:
            # memberships are ordered by create_date, so the oldest live one is the
            # main team; filtered() keeps this stored field independent of the
            # active_test of whichever context happened to trigger the recompute
            memberships = user.crm_team_member_ids.filtered('active')
            user.sale_team_id = memberships[:1].crm_team_id

    def write(self, vals):
        """Cascade the archive to the memberships, whatever route archived the user.

        This lives in ``write`` rather than in ``action_archive``: the latter is
        only the UI path, so ``user.write({'active': False})`` -- a data import, a
        server action, any code -- left the memberships live and the salesperson
        on their teams. Restoring the user does not resurrect them, as before.

        sudo: archiving a user belongs to base.group_system, but writing on
        memberships is reserved to Sales administrators -- without it a Settings
        administrator could not deactivate a user who happens to be a salesperson.
        """
        res = super().write(vals)
        if vals.get('active') is False:
            self.env['crm.team.member'].sudo().search([('user_id', 'in', self.ids)]).action_archive()
        return res
