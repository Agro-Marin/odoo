# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.fields import DomainCondition


class ResUsers(models.Model):
    _inherit = 'res.users'

    crm_team_ids = fields.Many2many(
        'crm.team', string='Sales Teams', copy=False, readonly=True,
        compute='_compute_crm_team_ids', search='_search_crm_team_ids',
        # compute_sudo: this field is the membership graph that the record rules
        # are computed *from* -- sales_team's own two, and every team rule in
        # sale -- so it must not itself depend on what the reader may see. It is
        # also literally re-entrant: crm_team_member_rule_personal evaluates
        # `user.crm_team_ids`, so computing it under that rule re-enters this
        # very compute, which then answers with the empty in-progress value and
        # silently reports that the salesperson belongs to no team at all.
        # (Stored computed fields get compute_sudo for free -- see Field.__set_name__
        # -- which is why sale_team_id never had the problem. This one is not stored.)
        compute_sudo=True)
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
        # The domain itself is built by crm.team.member, which builds the mirror
        # domain behind crm.team.member_ids from the same code: the two used to
        # carry private copies, and only this one ever got its operator and
        # `= False` semantics repaired. The active leaf it inserts matters here
        # in particular: `active_test=False` is meant to keep archived *users*
        # searchable, but it also reached the traversed memberships, so a
        # salesperson who had left a team still matched it -- and sale's team
        # record rules are written on this side of the relation, which handed
        # their orders and invoices to their former teammates for good.
        domain = self.env['crm.team.member']._search_live_projection(
            'crm_team_member_ids', 'crm_team_id', operator, value)
        if domain is NotImplemented:
            return NotImplemented

        # Only a plain positive membership match is worth materialising: it is
        # the shape sale's record rules use and it resolves to few users, so
        # inlining the ids simplifies the final queries. The other shapes ("no
        # team at all", or that OR-ed with a team) can match most of the table,
        # so they stay a subquery.
        if not (isinstance(domain, DomainCondition) and domain.operator == 'any!'):
            return domain

        # Past this many ids the inlining is the slower option; fall back on the
        # subquery rather than regress.
        IN_MAX = 10_000
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
        """Keep the memberships consistent with the user, whatever route wrote it.

        Both cascades live in ``write`` rather than in ``action_archive`` or a
        constraint: the action is only the UI path, so
        ``user.write({'active': False})`` -- a data import, a server action, any
        code -- left the memberships live and the salesperson on their teams.
        Restoring the user does not resurrect them, as before.

        Revoking a company is the same story seen from the other side.
        ``crm.team.member`` requires the team's company to be one of the
        salesperson's, and both ``_constrains_company_membership`` and
        ``crm.team._constrains_company_members`` enforce it -- but neither can
        trigger on a write to ``res.users.company_ids``, so dropping a company
        from a salesperson left a live membership that those very constraints
        reject, and that ``action_unarchive`` refuses to re-create. It was not
        inert: ``crm_team_ids`` still reported the team, so sale's team record
        rules kept trading documents between the ex-member and a company they no
        longer belong to -- the leak ``crm_team_member_comp_rule`` closes on the
        reading side, left open on the writing one.

        Archiving rather than raising, deliberately and like the cascade above:
        managing companies is a Settings job and must not be blocked by a
        Sales-side invariant. Archiving is also what lets ``crm_team_ids`` and
        the stored ``sale_team_id`` settle back on teams that are still valid.

        sudo: both writes belong to base.group_system, but writing on
        memberships is reserved to Sales administrators -- without it a Settings
        administrator could not deactivate a user who happens to be a
        salesperson, nor take a company away from one.
        """
        res = super().write(vals)
        if vals.get('active') is False:
            self.env['crm.team.member'].sudo().search([('user_id', 'in', self.ids)]).action_archive()
        elif 'company_ids' in vals:
            # 'elif': the archive above already covers every membership of these
            # users, so there is nothing left for this branch to find.
            memberships = self.env['crm.team.member'].sudo().search([('user_id', 'in', self.ids)])
            stale = memberships.filtered(
                lambda m: m.crm_team_id.company_id
                and m.crm_team_id.company_id not in m.user_id.company_ids
            )
            if stale:
                stale.action_archive()
        return res
