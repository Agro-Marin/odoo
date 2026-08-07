import random

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.misc import str2bool


class CrmTeam(models.Model):
    _name = "crm.team"
    _inherit = ["mail.thread"]
    _description = "Sales Team"
    _order = "sequence ASC, create_date DESC, id DESC"
    _check_company_auto = True

    def _get_default_color(self):
        return random.randint(1, 11)

    def _get_default_team_id(self, user_id=False, domain=False):
        """Compute default team id for sales related documents. Note that this
        method is not called by default_get as it takes some additional
        parameters and is meant to be called by other default methods.

        Heuristic (when multiple match: take from default context value or first
        sequence ordered)

          1- any of my teams (member OR responsible) matching domain, either from
             context or based on _order;
          2- any of my teams (member OR responsible), either from context or based
             on _order;
          3- default from context
          4- any team matching my company and domain (based on company rule)
          5- any team matching my company (based on company rule)

        :param user_id: salesperson to target, fallback on env.uid;
        :param domain: optional domain to filter teams (like use_lead = True);
        """
        if not user_id:
            user = self.env.user
        else:
            user = self.env["res.users"].sudo().browse(user_id)
        default_team = self.env["crm.team"]
        if context_team_id := self.env.context.get("default_team_id"):
            # Existence and `active` are checked, nothing else: a bare browse
            # accepted a stale action context or saved filter naming a team that
            # has since been archived or deleted, and handed it back as the
            # default for a brand new sales document. crm.team.member already
            # refuses to point a live row at an archived team; a fresh document
            # has no more business doing so.
            #
            # sudo, and the active leaf spelled out, both deliberately. The
            # record rules must NOT filter this: a context default is an explicit
            # server-side instruction (sale_crm carries the lead's team over to
            # its quotation, website_sale names the website's team) and the actor
            # is not always allowed to read the team they are legitimately being
            # put on. Rule-filtering it here would silently swap those teams for
            # the reader's own -- a behaviour change, not a fix.
            default_team = self.browse(
                self.env["crm.team"]
                .sudo()
                .search(
                    [
                        ("id", "=", context_team_id),
                        ("active", "=", True),
                    ]
                )
                .ids
            )
        valid_cids = [False] + [
            c for c in user.company_ids.ids if c in self.env.companies.ids
        ]

        # 1- find in user memberships - note that if current user in C1 searches
        # for team belonging to a user in C1/C2 -> only results for C1 will be returned
        team = self.env["crm.team"]
        teams = self.env["crm.team"].search(
            [
                ("company_id", "in", valid_cids),
                "|",
                ("user_id", "=", user.id),
                ("member_ids", "in", [user.id]),
            ]
        )
        if teams and domain:
            filtered_teams = teams.filtered_domain(domain)
            if default_team and default_team in filtered_teams:
                team = default_team
            else:
                team = filtered_teams[:1]

        # 2- any of my teams
        if not team:
            if default_team and default_team in teams:
                team = default_team
            else:
                team = teams[:1]

        # 3- default: context
        if not team and default_team:
            team = default_team

        if not team:
            # 4/5- default: based on company rule, the first team matching the
            # domain if one is given, else simply the first. _order already ranks
            # them, so both are one row from the database.
            #
            # `domain` is AND-ed into the search instead of being applied in
            # memory afterwards: filtered_domain had to load every team of the
            # company to pick a single row, and this step is reached exactly for
            # the users who have no team of their own -- so it runs per
            # salesperson over a mass import, table scan and all. The trade is
            # that `domain` must now be a searchable domain; every caller in the
            # workspace passes one over stored fields (crm's use_leads /
            # use_opportunities, sale's _check_company_domain).
            company_domain = [("company_id", "in", valid_cids)]
            if domain:
                team = self.search(company_domain + list(domain), limit=1)
            if not team:
                team = self.search(company_domain, limit=1)

        return team

    def _get_default_favorite_user_ids(self):
        return [(6, 0, [self.env.uid])]

    # description
    name = fields.Char("Sales Team", required=True, translate=True)
    sequence = fields.Integer("Sequence", default=10)
    active = fields.Boolean(
        default=True,
        help="If the active field is set to false, it will allow you to hide the Sales Team without removing it.",
    )
    company_id = fields.Many2one("res.company", string="Company", index=True)
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="company_id.currency_id",
        readonly=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Team Leader",
        check_company=True,
        domain=[("share", "!=", True)],
    )
    # memberships
    is_membership_multi = fields.Boolean(
        "Multiple Memberships Allowed",
        compute="_compute_is_membership_multi",
        help="If True, users may belong to several sales teams. Otherwise membership is limited to a single sales team.",
    )
    member_ids = fields.Many2many(
        "res.users",
        string="Salespersons",
        domain="['&', ('share', '=', False), ('company_ids', 'in', member_company_ids)]",
        compute="_compute_member_ids",
        inverse="_inverse_member_ids",
        search="_search_member_ids",
        help="Users assigned to this team.",
    )
    member_company_ids = fields.Many2many(
        "res.company",
        compute="_compute_member_company_ids",
        help="UX: Limit to team company or all if no company",
    )
    member_warning = fields.Text(
        "Membership Issue Warning", compute="_compute_member_warning"
    )
    crm_team_member_ids = fields.One2many(
        "crm.team.member",
        "crm_team_id",
        string="Sales Team Members",
        context={"active_test": True},
        help="Add members to automatically assign their documents to this sales team.",
    )
    crm_team_member_all_ids = fields.One2many(
        "crm.team.member",
        "crm_team_id",
        string="Sales Team Members (incl. inactive)",
        context={"active_test": False},
    )
    # UX options
    color = fields.Integer(
        string="Color Index",
        help="The color of the channel",
        default=_get_default_color,
    )
    favorite_user_ids = fields.Many2many(
        "res.users",
        "team_favorite_user_rel",
        "team_id",
        "user_id",
        string="Favorite Members",
        default=_get_default_favorite_user_ids,
    )
    is_favorite = fields.Boolean(
        string="Show on dashboard",
        compute="_compute_is_favorite",
        inverse="_inverse_is_favorite",
        help="Favorite teams to display them in the dashboard and access them easily.",
    )
    dashboard_button_name = fields.Char(
        string="Dashboard Button", compute="_compute_dashboard_button_name"
    )

    @api.model
    def _is_membership_multi(self):
        """Whether a salesperson may belong to several sales teams.

        ``ir.config_parameter`` stores strings, so the raw parameter must never
        be used as a boolean: unticking "Multi Teams" in the settings writes the
        literal ``'False'`` (``res.config.settings.set_values`` calls
        ``str(bool(value))``), which is truthy in Python. Reading it raw made the
        toggle one-way -- the settings page reported "off" while every mono-mode
        code path stayed disabled.
        """
        return str2bool(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("sales_team.membership_multi", ""),
            default=False,
        )

    @api.constrains("company_id")
    def _constrains_company_members(self):
        for team in self.filtered("company_id"):
            invalid_members = team.crm_team_member_ids.filtered(
                lambda m, team=team: team.company_id not in m.user_id.company_ids
            )
            if invalid_members:
                # ValidationError, like every other @api.constrains here; it
                # subclasses UserError, so callers catching that still catch this
                raise ValidationError(
                    _(
                        "The following team members are not allowed in company '%(company)s' of the Sales Team '%(team)s': %(users)s",
                        company=team.company_id.display_name,
                        team=team.name,
                        users=", ".join(invalid_members.mapped("user_id.name")),
                    )
                )

    @api.depends("sequence")  # TDE FIXME: force compute in new mode
    def _compute_is_membership_multi(self):
        self.is_membership_multi = self._is_membership_multi()

    # 'user_id' belongs in the trigger: reassigning a membership to another
    # salesperson changes who is on the team, and without it member_ids stayed
    # stale until something unrelated invalidated the cache
    @api.depends("crm_team_member_ids.active", "crm_team_member_ids.user_id")
    def _compute_member_ids(self):
        for team in self:
            team.member_ids = team.crm_team_member_ids.user_id

    def _inverse_member_ids(self):
        to_create, to_archive = [], self.env["crm.team.member"]
        for team in self:
            # pre-save value to avoid having _compute_member_ids interfering
            # while building membership status
            memberships = team.crm_team_member_ids  # active only, see field context
            users_current = team.member_ids

            to_create += [
                {"crm_team_id": team.id, "user_id": user.id}
                for user in users_current - memberships.user_id
            ]
            to_archive += memberships.filtered(
                lambda m, users_current=users_current: m.user_id not in users_current
            )

        # batched: one create and one archive for the whole recordset, instead of
        # a create per team and a write per membership
        if to_create:
            self.env["crm.team.member"].create(to_create)
        if to_archive:
            to_archive.action_archive()

    @api.depends("is_membership_multi", "member_ids")
    def _compute_member_warning(self):
        """Display a warning message to warn user they are about to archive
        other memberships. Only valid in mono-membership mode and take into
        account only active memberships as we may keep several archived
        memberships."""
        self.member_warning = False
        teams = self.filtered(
            lambda team: not team.is_membership_multi and team.member_ids
        )
        if not teams:
            return

        # One query for the whole recordset, and the same query the membership's
        # own warning asks -- see crm.team.member._get_live_teams_by_user for why
        # the active leaf is explicit and why this must not be sudoed.
        teams_by_user = self.env["crm.team.member"]._get_live_teams_by_user(
            teams.member_ids
        )

        for team in teams:
            user_names, other_teams = [], self.env["crm.team"]
            for user in team.member_ids:
                elsewhere = teams_by_user.get(user, self.env["crm.team"]) - team._origin
                if elsewhere:
                    user_names.append(user.name)
                    other_teams |= elsewhere
            if user_names:
                team.member_warning = _(
                    "%(user_names)s already in other teams (%(team_names)s).",
                    user_names=", ".join(user_names),
                    team_names=", ".join(other_teams.mapped("name")),
                )

    def _search_member_ids(self, operator, value):
        # Mirror of res.users._search_crm_team_ids, built from the same helper.
        # The dotted path this replaces expanded to an 'any' carrying the raw
        # operator, so 'not in' asked "has SOME member who is not X" instead of
        # "has NO member X" -- a team keeping one other salesperson matched --
        # and '= False' asked for a membership whose required user_id was False,
        # which no row can satisfy, so teams with no member were unfindable.
        # Both spellings are reachable from the team search view's 'member_ids'.
        return self.env["crm.team.member"]._search_live_projection(
            "crm_team_member_ids", "user_id", operator, value
        )

    # 'name' should not be in the trigger, but as 'company_id' is possibly not present in the view
    # because it depends on the multi-company group, we use it as fake trigger to force computation
    @api.depends("company_id", "name")
    def _compute_member_company_ids(self):
        """Available companies for members. Either team company if set, either
        any company if not set on team."""
        all_companies = self.env["res.company"].search([])
        for team in self:
            team.member_company_ids = team.company_id or all_companies

    @api.depends("favorite_user_ids")
    @api.depends_context("uid")
    def _compute_is_favorite(self):
        # depends_context('uid'): the value is per-reader, and without it the
        # first reader's answer is cached and served to everyone else
        for team in self:
            team.is_favorite = self.env.user in team.favorite_user_ids

    def _inverse_is_favorite(self):
        sudoed_self = self.sudo()
        to_fav = sudoed_self.filtered(
            lambda team: self.env.user not in team.favorite_user_ids
        )
        to_fav.write({"favorite_user_ids": [(4, self.env.uid)]})
        (sudoed_self - to_fav).write({"favorite_user_ids": [(3, self.env.uid)]})
        return True

    def _compute_dashboard_button_name(self):
        """Sets the adequate dashboard button name depending on the Sales Team's options"""
        self.dashboard_button_name = _("Dashboard")

    # ------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        teams = super(CrmTeam, self.with_context(mail_create_nosubscribe=True)).create(
            vals_list
        )
        # crm.team.member.create already grants the favourite, but when a team is
        # created together with its memberships the default for 'favorite_user_ids'
        # is applied after the one2many and replaces what the memberships added.
        # Re-granting here, once creation is over, is the only point that cannot
        # be overwritten.
        teams.crm_team_member_ids._add_to_team_favorites()
        return teams

    def write(self, vals):
        """Archiving a team cascades the archive to its memberships.

        Team-side mirror of :meth:`res.users.write`: a live membership pointing
        at an archived team is the state ``crm_team_ids`` reads and searches
        disagree about, and the one that pins the stored ``sale_team_id`` to a
        dead team. Archiving frees both to settle on live teams only.

        In ``write`` rather than ``action_archive``: the action is only the UI
        path, so ``team.write({'active': False})`` used to leave the memberships
        live. Restoring the team does not resurrect them, exactly like the
        user-side counterpart.
        """
        res = super().write(vals)
        if vals.get("active") is False:
            self.crm_team_member_ids.action_archive()
        return res

    @api.ondelete(at_uninstall=False)
    def _unlink_except_default(self):
        """Protect the teams other modules reference by XML id.

        ``env.ref`` is tolerant here: a database where one of these records was
        removed must still be able to delete *any* team, and the main Sales team
        is protected alongside the Website and POS ones because sale, crm and
        their dependants resolve it by XML id.
        """
        default_teams = self.browse()
        for xmlid in (
            "sales_team.team_sales_department",
            "sales_team.salesteam_website_sales",
            "sales_team.pos_sales_team",
        ):
            default_teams |= (
                self.env.ref(xmlid, raise_if_not_found=False) or self.browse()
            )

        if protected := (self & default_teams):
            raise UserError(
                _('Cannot delete default team "%(name)s"', name=protected[0].name)
            )

    # ------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------

    def action_primary_channel_button(self):
        """Skeleton function to be overloaded It will return the adequate action
        depending on the Sales Team's options."""
        return False

    @api.model
    def action_activate_multi_membership(self):
        """Allow salespersons to belong to several teams, from the warning banner.

        Multi-membership is a Sales setting, but it lives in an
        ``ir.config_parameter``, which only Settings administrators may write.
        Calling ``set_param`` straight from the client therefore failed for the
        Sales Administrators the banner is addressed to, and succeeded only for
        Settings administrators. The permission check belongs here, server-side,
        where it is authoritative and can grant exactly the intended group.
        """
        if not self.env.user.has_group("sales_team.group_sale_manager"):
            raise AccessError(
                _(
                    "Only a Sales Administrator can allow multiple sales team memberships."
                )
            )
        self.env["ir.config_parameter"].sudo().set_param(
            "sales_team.membership_multi", True
        )
