# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import _, api, exceptions, fields, models


class CrmTeamMember(models.Model):
    _name = 'crm.team.member'
    _inherit = ['mail.thread']
    _description = 'Sales Team Member'
    _rec_name = 'user_id'
    _order = 'create_date ASC, id'
    # No _check_company_auto: 'company_id' is related to 'user_id.company_id', so
    # a check_company field on 'user_id' would compare the salesperson's company
    # to itself and could never fail. The real cross-company rule -- the team's
    # company must be one of the salesperson's -- lives in
    # _constrains_company_membership.

    crm_team_id = fields.Many2one(
        'crm.team', string='Sales Team',
        group_expand='_read_group_expand_full',  # Always display all the teams
        default=False,  # TDE: temporary fix to activate depending computed fields
        check_company=False, index=True, ondelete="cascade", required=True)
    user_id = fields.Many2one(
        'res.users', string='Salesperson',  # TDE FIXME check responsible field
        index=True, ondelete='cascade', required=True,
        # The exclusion is expressed against the stored one2many instead of a
        # computed 'user_in_teams_ids' m2m: that field listed every salesperson
        # holding a membership anywhere, so opening one form shipped one id per
        # salesperson to the browser, and its value depended on how many records
        # happened to be computed alongside it. It also excluded, in mono mode,
        # exactly the users the team form's 'member_ids' happily accepted.
        # A blank crm_team_id matches no membership, so nobody is excluded.
        domain="""[
            ('share', '=', False),
            ('crm_team_member_ids', 'not any', [('active', '=', True), ('crm_team_id', '=', crm_team_id)]),
            ('company_ids', 'in', user_company_ids),
        ]""")
    user_company_ids = fields.Many2many(
        'res.company', compute='_compute_user_company_ids',
        help='UX: Limit to team company or all if no company')
    active = fields.Boolean(string='Active', default=True)
    is_membership_multi = fields.Boolean(
        'Multiple Memberships Allowed', compute='_compute_is_membership_multi',
        help='If True, users may belong to several sales teams. Otherwise membership is limited to a single sales team.')
    member_warning = fields.Text(compute='_compute_member_warning')
    # salesman information
    image_1920 = fields.Image("Image", related="user_id.image_1920", max_width=1920, max_height=1920)
    image_128 = fields.Image("Image (128)", related="user_id.image_128", max_width=128, max_height=128)
    name = fields.Char(string='Name', related='user_id.display_name')
    email = fields.Char(string='Email', related='user_id.email')
    phone = fields.Char(string='Phone', related='user_id.phone')
    company_id = fields.Many2one('res.company', string='Company', related='user_id.company_id')

    @api.constrains('crm_team_id', 'user_id', 'active')
    def _constrains_membership(self):
        """Forbid two active memberships for the same (team, salesperson) pair.

        Archived memberships may duplicate freely -- they are history -- which is
        why this cannot be a partial unique index: PostgreSQL cannot defer one,
        and the ORM flushes the INSERT of a re-added member before the matching
        ``active = False`` UPDATE, so ordinary "remove then re-add" flows hold
        two active rows for the span of a single flush. Checking in Python, once
        all changes are applied, is the only correct place.
        """
        active = self.filtered('active')
        if not active:
            return
        # sudo: a record rule hiding a membership must not let a duplicate slip through
        existing = self.sudo().search([
            ('crm_team_id', 'in', active.crm_team_id.ids),
            ('user_id', 'in', active.user_id.ids),
            ('active', '=', True),
        ])
        # the search is a cross product of the teams and users involved; only the
        # pairs this recordset actually touches are ours to validate
        touched = {(member.crm_team_id.id, member.user_id.id) for member in active}
        seen, duplicates = set(), self.browse()
        for membership in existing:
            key = (membership.crm_team_id.id, membership.user_id.id)
            if key not in touched:
                continue
            if key in seen:
                duplicates |= membership
            seen.add(key)

        if duplicates:
            raise exceptions.ValidationError(
                _("You are trying to create duplicate membership(s). We found that %(duplicates)s already exist(s).",
                  duplicates=", ".join("%s (%s)" % (m.user_id.name, m.crm_team_id.name) for m in duplicates)
                 ))

    @api.constrains('crm_team_id', 'user_id', 'active')
    def _constrains_company_membership(self):
        """The team's company, when set, must be one of the salesperson's.

        ``active`` is part of the trigger: a membership archived while the team
        still matched can otherwise be unarchived long after the team moved to
        another company, reinstating a combination that create would reject.
        """
        for membership in self.filtered(lambda m: m.active and m.crm_team_id.company_id):
            if membership.crm_team_id.company_id not in membership.user_id.company_ids:
                raise exceptions.ValidationError(_("User '%(user)s' is not allowed in the company '%(company)s' of the Sales Team '%(team)s'.",
                    user=membership.user_id.name,
                    company=membership.crm_team_id.company_id.display_name,
                    team=membership.crm_team_id.name
                ))

    @api.constrains('crm_team_id', 'active')
    def _constrains_team_active(self):
        """A live membership must point at a live team.

        Without it, joining -- or unarchiving onto -- an archived team produced a
        row that ``user.crm_team_ids`` does not report (a many2many read drops
        archived corecords) but ``search([('crm_team_ids', ...)])`` still matches,
        and that pinned the *stored* ``res_users.sale_team_id`` column to a dead
        team, which crm's pipeline action and sale_commission both consume.
        ``crm.team.write`` closes the other route by cascading the archive.
        """
        for membership in self.filtered('active'):
            if not membership.crm_team_id.active:
                raise exceptions.ValidationError(_(
                    "Sales Team '%(team)s' is archived and cannot take new members.",
                    team=membership.crm_team_id.name))

    @api.depends('crm_team_id')
    def _compute_user_company_ids(self):
        all_companies = self.env['res.company'].search([])
        for member in self:
            member.user_company_ids = member.crm_team_id.company_id or all_companies

    @api.depends('crm_team_id')
    def _compute_is_membership_multi(self):
        self.is_membership_multi = self.env['crm.team']._is_membership_multi()

    @api.depends('is_membership_multi', 'active', 'user_id', 'crm_team_id')
    def _compute_member_warning(self):
        """ Display a warning message to warn user they are about to archive
        other memberships. Only valid in mono-membership mode and take into
        account only active memberships as we may keep several archived
        memberships. """
        if self.env['crm.team']._is_membership_multi():
            # a single global parameter: no need to ask each record for it
            self.member_warning = False
        else:
            active = self.filtered('active')
            (self - active).member_warning = False
            if not active:
                return
            # The active leaf is explicit: relying on active_test would make the
            # warning depend on the caller's context and count archived history.
            # No sudo: crm_team_member_comp_rule scopes this to the reader's
            # companies, where reading as superuser then naming the teams raised
            # AccessError for anyone outside them -- and leaked the name otherwise.
            existing = self.env['crm.team.member'].search([
                ('active', '=', True),
                ('user_id', 'in', active.user_id.ids),
            ])
            user_mapping = dict.fromkeys(existing.user_id, self.env['crm.team'])
            for membership in existing:
                user_mapping[membership.user_id] |= membership.crm_team_id

            for member in active:
                teams = user_mapping.get(member.user_id, self.env['crm.team'])
                remaining = teams - (member.crm_team_id | member._origin.crm_team_id)
                if remaining:
                    member.member_warning = _("%(user_name)s already in other teams (%(team_names)s).",
                                              user_name=member.user_id.name,
                                              team_names=", ".join(remaining.mapped('name'))
                                             )
                else:
                    member.member_warning = False

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """ Specific behavior implemented on create

          * mono membership mode: other user memberships are automatically
            archived (a warning already told it in form view);
          * creating a membership already existing as archived: do nothing as
            people can manage them from specific menu "Members";

        Also remove autofollow on create. No need to follow team members
        when creating them as chatter is mainly used for information purpose
        (tracked fields).
        """
        memberships = super(CrmTeamMember, self.with_context(
            mail_create_nosubscribe=True
        )).create(vals_list)
        memberships._enforce_mono_membership()
        memberships._add_to_team_favorites()
        return memberships

    def write(self, vals):
        """ Specific behavior about active. If you change user_id / team_id user
        get warnings in form view and a raise in constraint check. We support
        archive / activation of memberships that toggles other memberships. But
        we do not support manual creation or update of user_id / team_id. This
        either works, either crashes). Indeed supporting it would lead to complex
        code with low added value. Users should create or remove members, and
        maybe archive / activate them. Updating manually memberships by
        modifying user_id or team_id is advanced and does not benefit from our
        support. """
        res = super().write(vals)
        if vals.get('active'):
            self._enforce_mono_membership()
        return res

    def _add_to_team_favorites(self):
        """Show the team on the dashboard of the salespersons who just joined it.

        Every way of putting someone on a team funnels through ``create`` --
        ``crm.team.member_ids``, ``crm_team_member_ids``, or a membership created
        directly -- so granting the favourite here covers all of them, where
        hanging it off ``crm.team`` watching ``member_ids`` covered only some.

        The users come from the memberships themselves rather than from
        ``crm_team_id.member_ids``: that field is computed from the very
        one2many being written, and does not yet see these rows when a team is
        created together with its members.
        """
        users_by_team = {}
        for membership in self:
            users_by_team.setdefault(membership.crm_team_id, []).append(membership.user_id.id)
        for team, user_ids in users_by_team.items():
            team.favorite_user_ids = [(4, user_id) for user_id in user_ids]

    def _enforce_mono_membership(self):
        """Keep a single active membership per salesperson (mono-membership mode).

        ``self`` holds the memberships just created or just activated: they win,
        and every other active membership of those salespersons is archived. When
        ``self`` itself carries several teams for one salesperson -- a batched
        create, or an "Unarchive" on a multi-record selection -- the last one wins,
        so a batch can no longer leave a user sitting on two teams the way
        repeated single writes never would.

        Memberships of the *same* team are deliberately left alone: those are
        genuine duplicates and must reach _constrains_membership.

        :return: the memberships that were archived
        """
        if self.env['crm.team']._is_membership_multi():
            return self.browse()
        winners = {member.user_id.id: member for member in self.filtered('active')}
        if not winners:
            return self.browse()

        obsolete = self.sudo().search([
            ('active', '=', True),
            ('user_id', 'in', list(winners)),
            ('id', 'not in', [member.id for member in winners.values()]),
        ]).filtered(
            lambda m: m.crm_team_id != winners[m.user_id.id].crm_team_id
        )
        if obsolete:
            obsolete.action_archive()
        return obsolete
