import base64
import functools
from typing import Any, Self

from odoo import api, fields, models, modules, tools
from odoo.api import SUPERUSER_ID, ValuesType
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.tools import file_open, html2plaintext, ormcache
from odoo.tools.image import image_process


@functools.cache
def _get_default_logo():
    """Return the default company logo as base64.

    Cached because the static PNG never changes at runtime.
    """
    with file_open("base/static/img/res_company_logo.png", "rb") as file:
        return base64.b64encode(file.read())


class ResCompany(models.Model):
    _name = "res.company"
    _description = "Companies"
    _order = "sequence, name"
    _inherit = ["format.address.mixin", "format.vat.label.mixin"]
    _parent_store = True

    def copy(self, default: ValuesType | None = None) -> Self:
        raise UserError(
            self.env._(
                "Duplicating a company is not allowed. Please create a new company instead."
            )
        )

    def _get_logo(self) -> bytes:
        return _get_default_logo()

    def _default_currency_id(self) -> models.Model:
        return self.env.user.company_id.currency_id

    name = fields.Char(
        related="partner_id.name",
        string="Company Name",
        required=True,
        store=True,
        readonly=False,
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        help="Used to order Companies in the company switcher",
        default=10,
    )
    parent_id = fields.Many2one(
        "res.company",
        string="Parent Company",
        index=True,
        ondelete="restrict",
    )
    child_ids = fields.One2many(
        "res.company",
        "parent_id",
        string="Branches",
    )
    all_child_ids = fields.One2many(
        "res.company",
        "parent_id",
        context={"active_test": False},
    )
    parent_path = fields.Char(index=True)
    parent_ids = fields.Many2many(
        "res.company",
        compute="_compute_parent_ids",
        compute_sudo=True,
    )
    root_id = fields.Many2one(
        "res.company",
        compute="_compute_parent_ids",
        compute_sudo=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self._default_currency_id(),
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        required=True,
        index=True,
    )
    user_ids = fields.Many2many(
        "res.users",
        "res_company_users_rel",
        "cid",
        "user_id",
        string="Accepted Users",
    )
    street = fields.Char(compute="_compute_address", inverse="_inverse_street")
    street2 = fields.Char(compute="_compute_address", inverse="_inverse_street2")
    zip = fields.Char(compute="_compute_address", inverse="_inverse_zip")
    city = fields.Char(compute="_compute_address", inverse="_inverse_city")
    state_id = fields.Many2one(
        "res.country.state",
        compute="_compute_address",
        inverse="_inverse_state",
        string="Fed. State",
        domain="[('country_id', '=?', country_id)]",
    )
    country_id = fields.Many2one(
        "res.country",
        compute="_compute_address",
        inverse="_inverse_country",
        string="Country",
    )
    # Technical field to hide country specific fields in company form view
    country_code = fields.Char(related="country_id.code", depends=["country_id"])
    email = fields.Char(related="partner_id.email", store=True, readonly=False)
    phone = fields.Char(related="partner_id.phone", store=True, readonly=False)
    website = fields.Char(related="partner_id.website", readonly=False)
    vat = fields.Char(related="partner_id.vat", string="Tax ID", readonly=False)
    company_registry = fields.Char(
        related="partner_id.company_registry",
        string="Company ID",
        readonly=False,
    )
    company_registry_placeholder = fields.Char(
        related="partner_id.company_registry_placeholder"
    )
    logo = fields.Binary(
        related="partner_id.image_1920",
        default=_get_logo,
        string="Company Logo",
        readonly=False,
    )
    # logo_web: do not store in attachments, since the image is retrieved in SQL for
    # performance reasons (see addons/web/controllers/main.py, Binary.company_logo)
    logo_web = fields.Binary(
        compute="_compute_logo_web",
        store=True,
        attachment=False,
    )
    uses_default_logo = fields.Boolean(
        compute="_compute_uses_default_logo",
        store=True,
    )
    report_header = fields.Html(
        string="Company Tagline",
        translate=True,
        help="Company tagline, which is included in a printed document's header or footer (depending on the selected layout).",
    )
    report_footer = fields.Html(
        string="Report Footer",
        translate=True,
        help="Footer text displayed at the bottom of all reports.",
    )
    company_details = fields.Html(
        string="Company Details",
        translate=True,
        help="Header text displayed at the top of all reports.",
    )
    is_company_details_empty = fields.Boolean(
        compute="_compute_empty_company_details",
    )
    paperformat_id = fields.Many2one(
        "report.paperformat",
        "Paper format",
        default=lambda self: self.env.ref(
            "base.paperformat_euro",
            raise_if_not_found=False,
        ),
    )
    external_report_layout_id = fields.Many2one("ir.ui.view", "Document Template")
    font = fields.Selection(
        [
            ("Lato", "Lato"),
            ("Roboto", "Roboto"),
            ("Open_Sans", "Open Sans"),
            ("Montserrat", "Montserrat"),
            ("Oswald", "Oswald"),
            ("Raleway", "Raleway"),
            ("Tajawal", "Tajawal"),
            ("Fira_Mono", "Fira Mono"),
        ],
        default="Lato",
    )
    primary_color = fields.Char()
    secondary_color = fields.Char()
    color = fields.Integer(
        compute="_compute_color",
        inverse="_inverse_color",
        recursive=True,
    )
    layout_background = fields.Selection(
        [
            ("Blank", "Blank"),
            ("Demo logo", "Demo logo"),
            ("Custom", "Custom"),
        ],
        default="Blank",
        required=True,
    )
    layout_background_image = fields.Binary("Background Image")
    uninstalled_l10n_module_ids = fields.Many2many(
        "ir.module.module",
        compute="_compute_uninstalled_l10n_module_ids",
    )
    bank_ids = fields.One2many(
        related="partner_id.bank_ids",
        readonly=False,
    )

    def init(self) -> None:
        """Set default paperformat on companies missing one."""
        paperformat_euro = self.env.ref("base.paperformat_euro", False)
        if paperformat_euro:
            companies_without = self.search([("paperformat_id", "=", False)])
            if companies_without:
                companies_without.write({"paperformat_id": paperformat_euro.id})
        super().init()

    _name_uniq = models.Constraint(
        "unique (name)",
        "The company name must be unique!",
    )

    @api.constrains("parent_id")
    def _check_parent_id(self) -> None:
        if self._has_cycle():
            raise ValidationError(self.env._("You cannot create recursive companies."))

    @api.constrains("active")
    def _check_active(self) -> None:
        inactive_companies = self.filtered(lambda c: not c.active)
        if not inactive_companies:
            return
        # _read_group only returns non-empty groups, so every returned company
        # is an offender (count >= 1) — no per-group `if count` filter needed.
        offenders = self.env["res.users"]._read_group(
            [
                ("company_id", "in", inactive_companies.ids),
                ("active", "=", True),
            ],
            groupby=["company_id"],
            aggregates=["__count"],
        )
        if offenders:
            raise ValidationError(
                self.env._(
                    "The following companies cannot be archived because they are still "
                    "used as the default company of active users:\n%(details)s",
                    details="\n".join(
                        self.env._(
                            "- %(company_name)s (%(active_users)s users)",
                            company_name=company.name,
                            active_users=count,
                        )
                        for company, count in offenders
                    ),
                )
            )

    @api.constrains(
        lambda self: self._get_company_root_delegated_field_names() + ["parent_id"]
    )
    def _check_root_delegated_fields(self) -> None:
        for company in self:
            if company.parent_id:
                for fname in company._get_company_root_delegated_field_names():
                    if company[fname] != company.parent_id[fname]:
                        description = (
                            self.env["ir.model.fields"]
                            ._get("res.company", fname)
                            .field_description
                        )
                        raise ValidationError(
                            self.env._(
                                "The %s of a subsidiary must be the same as its root company.",
                                description,
                            )
                        )

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:

        # create missing partners
        no_partner_vals_list = [
            vals
            for vals in vals_list
            if vals.get("name") and not vals.get("partner_id")
        ]
        if no_partner_vals_list:
            partners = (
                self.env["res.partner"]
                .with_context(default_parent_id=False)
                .create(
                    [
                        {
                            "name": vals["name"],
                            "is_company": True,
                            "image_1920": vals.get("logo"),
                            "email": vals.get("email"),
                            "phone": vals.get("phone"),
                            "website": vals.get("website"),
                            "vat": vals.get("vat"),
                            "country_id": vals.get("country_id"),
                        }
                        for vals in no_partner_vals_list
                    ]
                )
            )
            # compute stored fields, for example address dependent fields
            partners.flush_model()
            for vals, partner in zip(no_partner_vals_list, partners, strict=True):
                vals["partner_id"] = partner.id

        for vals in vals_list:
            # Copy delegated fields from root to branches
            if parent := self.browse(vals.get("parent_id")):
                for fname in self._get_company_root_delegated_field_names():
                    vals.setdefault(
                        fname,
                        self._fields[fname].convert_to_write(parent[fname], parent),
                    )

        self.env.registry.clear_cache()
        companies = super().create(vals_list)

        # The write is made on the user to set it automatically in the multi company group.
        if companies:
            (self.env.user | self.env["res.users"].browse(SUPERUSER_ID)).write(
                {
                    "company_ids": [Command.link(company.id) for company in companies],
                }
            )

        # Sudo required: writing res.currency.active is restricted to group_system;
        # company creation can happen under group_erp_manager which lacks write access.
        companies.currency_id.sudo().filtered(lambda c: not c.active).active = True

        companies_needs_l10n = companies.filtered("country_id")
        if companies_needs_l10n:
            companies_needs_l10n.install_l10n_modules()

        return companies

    def write(self, vals: dict[str, Any]) -> bool:
        if "parent_id" in vals and any(
            c.parent_id.id != vals["parent_id"] for c in self
        ):
            raise UserError(self.env._("The company hierarchy cannot be changed."))

        if vals.get("currency_id"):
            currency = self.env["res.currency"].browse(vals["currency_id"])
            if not currency.active:
                currency.write({"active": True})

        # Capture companies gaining their first country BEFORE the write
        # (after super().write(), country_id is already set so the filter
        # would always be empty).
        companies_needs_l10n = (
            vals.get("country_id")
            and self.filtered(lambda company: not company.country_id)
        ) or self.browse()

        res = super().write(vals)
        invalidation_fields = self.cache_invalidation_fields()
        asset_invalidation_fields = {
            "font",
            "primary_color",
            "secondary_color",
            "external_report_layout_id",
        }
        if not invalidation_fields.isdisjoint(vals):
            self.env.registry.clear_cache()

        if not asset_invalidation_fields.isdisjoint(vals):
            # this is used in the content of an asset (see asset_styles_company_report)
            # and thus needs to invalidate the assets cache when this is changed
            self.env.registry.clear_cache(
                "assets"
            )  # not 100% it is useful a test is missing if it is the case

        # Archiving a company should also archive all of its branches
        if vals.get("active") is False:
            self.child_ids.active = False

        delegated_changed = set(vals) & set(
            self._get_company_root_delegated_field_names()
        )
        for company in self:
            # Copy modified delegated fields from root to branches
            if delegated_changed and not company.parent_id:
                # Perf: one child_of search + write per root; fine since self is
                # almost always a single company (a bulk write over many roots
                # would run N searches + N writes and should batch instead).
                # Sudo: sync must reach ALL branches, some outside user scope.
                branches = self.sudo().search(  # noqa: E8507 — bounded: only root companies (typically 1)
                    [
                        ("id", "child_of", company.id),
                        ("id", "!=", company.id),
                    ]
                )
                changed_vals = {
                    fname: self._fields[fname].convert_to_write(
                        company[fname], branches
                    )
                    for fname in sorted(delegated_changed)
                }
                branches.write(changed_vals)

        if companies_needs_l10n:
            companies_needs_l10n.install_l10n_modules()

        # invalidate company cache to recompute address based on updated partner
        company_address_fields = self._get_company_address_field_names()
        company_address_fields_upd = set(company_address_fields) & set(vals.keys())
        if company_address_fields_upd:
            self.invalidate_model(company_address_fields)
        return res

    def unlink(self) -> bool:
        """Unlink, then clear the cache so res.users._get_company_ids returns only existing company ids."""
        res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _get_company_root_delegated_field_names(self) -> list[str]:
        """Return the field names delegated to the root company.

        These fields must be identical on all branches: they are copied from the
        root and shown readonly in the form view.
        """
        return ["currency_id"]

    def _get_company_address_field_names(self) -> list[str]:
        """Return the address field names shared by company and its partner.

        The names are identical on both models, so they double as the copy map
        between company and partner.
        """
        return ["street", "street2", "city", "zip", "state_id", "country_id"]

    def _get_company_address_update(self, partner: Any) -> dict[str, Any]:
        return {
            fname: partner[fname] for fname in self._get_company_address_field_names()
        }

    @api.depends("parent_path")
    def _compute_parent_ids(self) -> None:
        for company in self.with_context(active_test=False):
            company.parent_ids = (
                self.browse([int(id) for id in company.parent_path.split("/") if id])
                if company.parent_path
                else company
            )
            company.root_id = company.parent_ids[0]

    @api.depends(
        lambda self: [
            f"partner_id.{fname}" for fname in self._get_company_address_field_names()
        ]
    )
    def _compute_address(self) -> None:
        for company in self.filtered(lambda company: company.partner_id):
            # Sudo: partner may be filtered by the res.partner record rule
            # (company_id outside user scope). Company always owns its partner.
            address_data = company.partner_id.sudo().address_get(adr_pref=["contact"])
            if address_data["contact"]:
                partner = company.partner_id.browse(address_data["contact"]).sudo()
                company.update(company._get_company_address_update(partner))

    def _inverse_street(self) -> None:
        for company in self:
            company.partner_id.street = company.street

    def _inverse_street2(self) -> None:
        for company in self:
            company.partner_id.street2 = company.street2

    def _inverse_zip(self) -> None:
        for company in self:
            company.partner_id.zip = company.zip

    def _inverse_city(self) -> None:
        for company in self:
            company.partner_id.city = company.city

    def _inverse_state(self) -> None:
        for company in self:
            company.partner_id.state_id = company.state_id

    def _inverse_country(self) -> None:
        for company in self:
            company.partner_id.country_id = company.country_id

    @api.depends("partner_id.image_1920")
    def _compute_logo_web(self) -> None:
        for company in self:
            img = company.partner_id.image_1920
            company.logo_web = img and base64.b64encode(
                image_process(base64.b64decode(img), size=(180, 0))
            )

    @api.depends("partner_id.image_1920")
    def _compute_uses_default_logo(self) -> None:
        default_logo = self._get_logo()
        for company in self:
            company.uses_default_logo = not company.logo or company.logo == default_logo

    # ``root_id.partner_id.color`` cannot be a dependency: ``root_id`` is a
    # non-stored compute without ``search=``, so the trigger resolver's inverse
    # search would fail. Instead ``partner_id.color`` recomputes the root's own
    # color and ``parent_id.color`` cascades the invalidation down ``child_ids``.
    @api.depends("root_id", "parent_id.color", "partner_id.color")
    def _compute_color(self) -> None:
        for company in self:
            company.color = company.root_id.partner_id.color or (
                company.root_id._origin.id % 12
            )

    def _inverse_color(self) -> None:
        for company in self:
            company.root_id.partner_id.color = company.color

    @api.onchange("state_id")
    def _onchange_state(self) -> None:
        if self.state_id.country_id:
            self.country_id = self.state_id.country_id

    @api.onchange("country_id")
    def _onchange_country_id(self) -> None:
        if self.country_id:
            self.currency_id = self.country_id.currency_id

    @api.onchange("parent_id")
    def _onchange_parent_id(self) -> None:
        if self.parent_id:
            for fname in self._get_company_root_delegated_field_names():
                if self[fname] != self.parent_id[fname]:
                    self[fname] = self.parent_id[fname]

    @api.depends("country_id")
    def _compute_uninstalled_l10n_module_ids(self) -> None:
        # This will only compute uninstalled modules with auto-install without recursion,
        # the rest will eventually be handled by `button_install`
        self.env["ir.module.module"].flush_model(
            ["auto_install", "country_ids", "dependencies_id"]
        )
        self.env["ir.module.module.dependency"].flush_model()
        self.env.cr.execute(
            """
            SELECT country.id,
                   ARRAY_AGG(module.id)
              FROM ir_module_module module,
                   res_country country
             WHERE module.auto_install
               AND state != ALL(%(install_states)s)
               AND NOT EXISTS (
                       SELECT 1
                         FROM ir_module_module_dependency d
                         JOIN ir_module_module mdep ON (d.name = mdep.name)
                        WHERE d.module_id = module.id
                          AND d.auto_install_required
                          AND mdep.state != ALL(%(install_states)s)
                   )
               AND EXISTS (
                       SELECT 1
                         FROM module_country mc
                        WHERE mc.module_id = module.id
                          AND mc.country_id = country.id
                   )
               AND country.id = ANY(%(country_ids)s)
          GROUP BY country.id
        """,
            {
                "country_ids": self.country_id.ids,
                "install_states": ["installed", "to install", "to upgrade"],
            },
        )
        mapping = dict(self.env.cr.fetchall())
        for company in self:
            company.uninstalled_l10n_module_ids = self.env["ir.module.module"].browse(
                mapping.get(company.country_id.id)
            )

    def install_l10n_modules(self) -> Any:
        uninstalled_modules = self.uninstalled_l10n_module_ids
        is_ready_and_not_test = (
            not tools.config["test_enable"]
            and (self.env.registry.ready or not self.env.registry._init)
            and not modules.module.current_test
            and not self.env.context.get(
                "install_mode"
            )  # due to savepoint when importing the file
            and not self.env.context.get(
                "import_file"
            )  # same: button_immediate_install commits, erasing import savepoints
        )
        if uninstalled_modules and is_ready_and_not_test:
            return uninstalled_modules.button_immediate_install()
        return is_ready_and_not_test

    @api.model
    def _get_view(
        self,
        view_id: int | None = None,
        view_type: str = "form",
        **options: Any,
    ) -> tuple:
        delegated_fnames = set(self._get_company_root_delegated_field_names())
        arch, view = super()._get_view(view_id, view_type, **options)
        for f in arch.iter("field"):
            if f.get("name") in delegated_fnames:
                f.set("readonly", "parent_id != False")
        return arch, view

    @api.model
    def _search_display_name(self, operator: str, value: str) -> Domain:
        context = dict(self.env.context)
        newself = self
        constraint = Domain.TRUE
        if context.pop("user_preference", None):
            # Constrain to the user's own companies: record rules alone would
            # limit the search to currently visible companies, hiding others she
            # belongs to. Search across all companies as superuser, then AND the
            # constraint below (same pattern as __accessible_branches).
            companies = self.env.user.company_ids
            constraint = Domain("id", "in", companies.ids)
            newself = newself.sudo()
        newself = newself.with_context(context)
        domain = super(ResCompany, newself)._search_display_name(operator, value)
        return domain & constraint

    @api.depends("company_details")
    def _compute_empty_company_details(self) -> None:
        # When an html field is empty a <p> tag remains with a <br> in it,
        # but when company details is empty we want to show the company info instead
        for record in self:
            record.is_company_details_empty = not html2plaintext(
                record.company_details or ""
            )

    def cache_invalidation_fields(self) -> set[str]:
        # This list is not well defined and tests should be improved
        return {
            "active",  # user._get_company_ids and other potential cached search
            "sequence",  # user._get_company_ids and other potential cached search
            "partner_id",  # _get_company_partner_ids (own-company partner guards)
        }

    @api.model
    def _get_main_company(self) -> Self:
        try:
            # Sudo: may be called during bootstrap or cron with no company context.
            main_company = self.sudo().env.ref("base.main_company")
        except ValueError:
            main_company = (
                self.env["res.company"].sudo().search([], limit=1, order="id")
            )

        return main_company

    @ormcache("tuple(self.env.companies.ids)", "self.id", "self.env.uid")
    def __accessible_branches(self) -> list[int]:
        # Get branches of this company that the current user can use
        self.ensure_one()

        accessible_branch_ids = []
        accessible = self.env.companies
        # Sudo is required to traverse child_ids across the full hierarchy,
        # which may include companies outside the user's company_ids. The
        # intersection with `accessible` below is the real access gate.
        current = self.sudo()
        seen = set()
        while current:
            new = current - current.browse(seen)
            if not new:
                break  # cycle guard
            accessible_branch_ids.extend((new & accessible).ids)
            seen.update(new.ids)
            current = new.child_ids

        if not accessible_branch_ids and self.env.uid == SUPERUSER_ID:
            # Under superuser (e.g. in a cron) the intersection with accessible
            # companies may be empty; superuser bypasses record rules and has
            # access to all companies, so fall back to the current company.
            return self.ids

        return accessible_branch_ids

    def _accessible_branches(self) -> Self:
        return self.browse(self.__accessible_branches())

    @ormcache()
    def _get_company_partner_ids(self):
        return tuple(
            self.env["res.company"]
            .sudo()
            .with_context(active_test=False)
            .search([])
            .partner_id.ids
        )

    def _all_branches_selected(self) -> bool:
        """Return whether exactly all branches of self's companies are selected.

        Useful for actions that only make sense on whole companies, branches
        included.
        """
        # Sudo required: knowing ALL branches of root requires reading companies
        # outside the user's allowed set. This is structural info, not data access.
        return self == self.sudo().search([("id", "child_of", self.root_id.ids)])

    def action_all_company_branches(self) -> dict[str, Any]:
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Branches"),
            "res_model": "res.company",
            "domain": [("parent_id", "=", self.id)],
            "context": {
                "active_test": False,
                "default_parent_id": self.id,
            },
            "views": [[False, "list"], [False, "kanban"], [False, "form"]],
        }

    def _get_public_user(self) -> models.Model:
        """Return (creating if needed) the company's public ``res.users``."""
        self.ensure_one()
        # Deterministic per-company login; login uniqueness is global (DB
        # constraint on res.users), so it keeps public users from colliding.
        login = f"public-user@company-{self.id}.com"
        # Probe by login rather than group_public membership: a stale or
        # out-of-band-modified public user would be missed by a membership
        # probe, and the copy below would then hit the global login-uniqueness
        # constraint instead of returning a usable record.
        existing = (
            self.env["res.users"]
            .sudo()
            .with_context(active_test=False)
            .search([("login", "=", login), ("company_id", "=", self.id)], limit=1)
        )
        if existing:
            return existing
        return (
            self.env.ref("base.public_user")
            .sudo()
            .copy(
                {
                    "name": f"Public user for {self.name}",
                    "login": login,
                    "company_id": self.id,
                    "company_ids": [Command.set([self.id])],
                }
            )
        )
