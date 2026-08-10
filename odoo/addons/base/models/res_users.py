import collections
import contextlib
import datetime
import hmac
import ipaddress
import logging
import time
import uuid
from functools import wraps
from hashlib import sha256
from typing import TYPE_CHECKING, Any, Self

from lxml import etree
from markupsafe import Markup

from odoo import _, api, fields, models, tools
from odoo.api import SUPERUSER_ID, DomainType, ValuesType
from odoo.exceptions import (
    AccessDenied,
    AccessError,
    UserError,
    ValidationError,
)
from odoo.fields import Command, Domain
from odoo.http import DEFAULT_LANG, request
from odoo.libs.datetime import all_timezones
from odoo.libs.datetime import timezone as get_timezone
from odoo.libs.json import dumps as json_dumps
from odoo.libs.password import CryptContext
from odoo.tools import (
    SQL,
    email_domain_extract,
    frozendict,
    is_html_empty,
    reset_cached_properties,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

_logger = logging.getLogger(__name__)

MIN_ROUNDS = 600_000

LOGIN_FAILURES_PRUNE_THRESHOLD = 1000

_RELATION_ONLY_COMMANDS = frozenset(
    {Command.UNLINK, Command.LINK, Command.CLEAR, Command.SET}
)
"""x2many commands that write the relation and never the comodel record.

On a many2many these only add or drop rows of the relation table. On a
one2many the same commands write the inverse column of the comodel row, so
:meth:`ResUsers._escapes_own_record` rejects one2many outright rather than
consulting this set.
"""


def _is_private_address(source: str | None) -> bool:
    try:
        return ipaddress.ip_address(source).is_private
    except ValueError:
        return False


def _jsonable(o: object) -> bool:
    try:
        json_dumps(o)
    except TypeError:
        return False
    else:
        return True


def check_identity(
    fn: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:

    @wraps(fn)
    def wrapped(self: ResUsers, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if not request:
            raise UserError(_("This method can only be accessed over HTTP"))

        if request.session.get("identity-check-last", 0) > time.time() - 10 * 60:
            return fn(self, *args, **kwargs)

        w = (
            self.sudo()
            .env["res.users.identitycheck"]
            .create(
                {
                    "request": json_dumps(
                        [
                            {k: v for k, v in self.env.context.items() if _jsonable(v)},
                            self._name,
                            self.ids,
                            fn.__name__,
                            args,
                            kwargs,
                        ]
                    )
                }
            )
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.users.identitycheck",
            "res_id": w.id,
            "name": _("Access Control"),
            "target": "new",
            "views": [(False, "form")],
            "context": {"dialog_size": "medium"},
        }

    wrapped.__has_check_identity = True
    return wrapped


class ResUsers(models.Model):
    _name = "res.users"
    _description = "User"
    _inherits = {"res.partner": "partner_id"}
    _order = "name, login"
    _allow_sudo_commands = False

    @property
    def SELF_READABLE_FIELDS(self) -> list[str]:
        return [
            "signature",
            "company_id",
            "login",
            "email",
            "name",
            "image_1920",
            "image_1024",
            "image_512",
            "image_256",
            "image_128",
            "lang",
            "tz",
            "tz_offset",
            "group_ids",
            "partner_id",
            "write_date",
            "action_id",
            "avatar_1920",
            "avatar_1024",
            "avatar_512",
            "avatar_256",
            "avatar_128",
            "share",
            "device_ids",
            "api_key_ids",
            "phone",
            "display_name",
        ]

    @property
    def SELF_WRITEABLE_FIELDS(self) -> list[str]:
        return [
            "signature",
            "action_id",
            "company_id",
            "email",
            "name",
            "image_1920",
            "lang",
            "tz",
            "phone",
        ]

    @api.model
    @tools.ormcache(cache="stable")
    def _self_accessible_fields(self) -> tuple[frozenset[str], frozenset[str]]:
        readable = frozenset(self.SELF_READABLE_FIELDS)
        writeable = frozenset(self.SELF_WRITEABLE_FIELDS)
        return readable, writeable

    @api.model
    def context_get(self) -> frozendict:
        context, user_lang_valid = self._context_get_cached()
        if context and not user_lang_valid and request:
            best_lang = request.best_lang
            if best_lang and best_lang != context["lang"]:
                if best_lang in self._get_installed_lang_codes():
                    return frozendict({**context, "lang": best_lang})
        return context

    @api.model
    @tools.ormcache()
    def _get_installed_lang_codes(self) -> frozenset[str]:
        return frozenset(code for code, _name in self.env["res.lang"].get_installed())

    @api.model
    @tools.ormcache("self.env.uid")
    def _context_get_cached(self) -> tuple[frozendict, bool]:
        try:
            context = self.env.user.with_context(prefetch_fields=False).read(
                ["lang", "tz"], load=False
            )[0]
        except IndexError:
            return frozendict(), False
        context.pop("id")

        langs = [code for code, _ in self.env["res.lang"].get_installed()]
        langset = set(langs)
        user_lang_valid = context.get("lang") in langset

        def _lang_candidates():
            yield context.get("lang")
            yield self.env.user.with_context(
                prefetch_fields=False
            ).company_id.partner_id.lang
            yield DEFAULT_LANG
            if langs:
                yield langs[0]

        context["lang"] = next(
            (lang for lang in _lang_candidates() if lang in langset), DEFAULT_LANG
        )

        context["uid"] = self.env.uid

        return frozendict(context), user_lang_valid

    @tools.ormcache("self.id")
    def _get_company_ids(self) -> tuple[int, ...]:
        domain = [("active", "=", True), ("user_ids", "in", self.id)]
        return self.env["res.company"].search(domain)._ids

    @api.model
    @tools.ormcache("uid", "passwd_hash")
    def _check_uid_passwd_cached(
        self, uid: int, passwd: str, passwd_hash: str
    ) -> datetime.datetime | None:
        user = self.with_user(uid).env.user
        if not user.active:
            raise AccessDenied
        credential = {
            "login": user.login,
            "password": passwd,
            "type": "password",
        }
        result = user._check_credentials(credential, {"interactive": False})
        if result.get("auth_method") == "apikey":
            return self.env["res.users.apikeys"]._get_key_expiration(
                scope="rpc", key=passwd
            )
        return None

    @tools.ormcache("self.id", "sid")
    def _compute_session_token(self, sid: str) -> str | bool:
        field_values = self._session_token_get_values()
        return self._session_token_hash_compute(sid, field_values)

    @tools.ormcache("self.id")
    def _get_group_ids(self) -> tuple[int, ...]:
        self.ensure_one()
        return self.with_context({}).all_group_ids._ids

    def _effective_group_ids(self) -> tuple[int, ...]:
        self.ensure_one()
        return self._get_group_ids() if self.id else self.all_group_ids._origin._ids

    @tools.ormcache(cache="stable")
    def _crypt_context(self) -> CryptContext:
        cfg = self.env["ir.config_parameter"].sudo()
        return CryptContext(
            ["pbkdf2_sha512", "plaintext"],
            deprecated=["auto"],
            pbkdf2_sha512__rounds=max(
                MIN_ROUNDS, int(cfg.get_param("password.hashing.rounds", 0))
            ),
        )

    def _check_company_domain(self, companies: Self | str | None) -> Domain:
        if not companies:
            return Domain.TRUE
        company_ids = (
            companies if isinstance(companies, str) else models.to_record_ids(companies)
        )
        return Domain("company_ids", "in", company_ids)

    def _default_groups(self) -> Self:
        groups = self.env.ref("base.group_user")
        default_group = self.env.ref(
            "base.default_user_group", raise_if_not_found=False
        )
        if default_group:
            groups += default_group.implied_ids
        return groups

    def _default_view_group_hierarchy(self) -> dict[str, Any]:
        return self.env["res.groups"]._get_view_group_hierarchy()

    partner_id = fields.Many2one(
        "res.partner",
        string="Related Partner",
        required=True,
        ondelete="restrict",
        bypass_search_access=True,
        index=True,
        help="Partner-related data of the user",
    )
    login = fields.Char(required=True, help="Used to log into the system")
    password = fields.Char(
        compute="_compute_password",
        inverse="_set_password",
        copy=False,
        help="Keep empty if you don't want the user to be able to connect on the system.",
    )
    new_password = fields.Char(
        string="Set Password",
        compute="_compute_password",
        inverse="_set_new_password",
        help="Specify a value only when creating a user or if you're "
        "changing the user's password, otherwise leave empty. After "
        "a change of password, the user has to login again.",
    )
    api_key_ids = fields.One2many("res.users.apikeys", "user_id", string="API Keys")
    signature = fields.Html(
        string="Email Signature",
        compute="_compute_signature",
        readonly=False,
        store=True,
    )
    active = fields.Boolean(default=True)
    active_partner = fields.Boolean(
        related="partner_id.active",
        readonly=True,
        string="Partner is Active",
    )
    action_id = fields.Many2one(
        "ir.actions.actions",
        string="Home Action",
        help="If specified, this action will be opened at log on for this user, in addition to the standard menu.",
    )
    log_ids = fields.One2many("res.users.log", "create_uid", string="User log entries")
    device_ids = fields.One2many("res.device", "user_id", string="User devices")
    login_date = fields.Datetime(
        related="log_ids.create_date",
        string="Latest Login",
        readonly=False,
    )
    share = fields.Boolean(
        compute="_compute_share",
        compute_sudo=True,
        string="Share User",
        store=True,
        help="External user with limited access, created only for the purpose of sharing data.",
    )
    tz_offset = fields.Char(compute="_compute_tz_offset", string="Timezone offset")

    name = fields.Char(related="partner_id.name", inherited=True, readonly=False)
    email = fields.Char(related="partner_id.email", inherited=True, readonly=False)
    email_domain_placeholder = fields.Char(compute="_compute_email_domain_placeholder")
    phone = fields.Char(related="partner_id.phone", inherited=True, readonly=False)

    res_users_settings_ids = fields.One2many("res.users.settings", "user_id")
    res_users_settings_id = fields.Many2one(
        "res.users.settings",
        string="Settings",
        compute="_compute_res_users_settings_id",
        search="_search_res_users_settings_id",
    )

    companies_count = fields.Integer(
        compute="_compute_companies_count",
        string="Number of Companies",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company.id,
        help="The default company for this user.",
        context={"user_preference": True},
    )
    company_ids = fields.Many2many(
        "res.company",
        "res_company_users_rel",
        "user_id",
        "cid",
        string="Companies",
        default=lambda self: self.env.company.ids,
    )

    group_ids = fields.Many2many(
        "res.groups",
        "res_groups_users_rel",
        "uid",
        "gid",
        string="Groups",
        default=lambda s: s._default_groups(),
        help="Groups explicitly assigned to the user",
    )
    all_group_ids = fields.Many2many(
        "res.groups",
        string="Groups and implied groups",
        compute="_compute_all_group_ids",
        compute_sudo=True,
        search="_search_all_group_ids",
    )

    accesses_count = fields.Integer(
        "# Access Rights",
        help="Number of access rights that apply to the current user",
        compute="_compute_accesses_count",
        compute_sudo=True,
    )
    rules_count = fields.Integer(
        "# Record Rules",
        help="Number of record rules that apply to the current user",
        compute="_compute_accesses_count",
        compute_sudo=True,
    )
    groups_count = fields.Integer(
        "# Groups",
        help="Number of groups that apply to the current user",
        compute="_compute_accesses_count",
        compute_sudo=True,
    )

    view_group_hierarchy = fields.Json(
        string="Technical field for user group setting",
        store=False,
        copy=False,
        default=_default_view_group_hierarchy,
    )
    role = fields.Selection(
        [("group_user", "User"), ("group_system", "Administrator")],
        compute="_compute_role",
        readonly=False,
        string="Role",
    )

    def init(self) -> None:
        cr = self.env.cr

        cr.execute(
            r"""
            SELECT id, password FROM res_users
            WHERE password IS NOT NULL
            AND password !~ '^\$[^$]+\$[^$]+\$.'
            """
        )
        rows = cr.fetchall()
        if rows:
            ctx = self._crypt_context()
            hashed = [(ctx.hash(pw), uid) for uid, pw in rows]
            cr.executemany("UPDATE res_users SET password=%s WHERE id=%s", hashed)
            self.sudo().browse([uid for uid, _pw in rows]).invalidate_recordset(
                ["password"]
            )

    _login_key = models.Constraint(
        "UNIQUE (login)", "You can not have two users with the same login!"
    )

    @api.constrains("company_id", "company_ids", "active")
    def _check_user_company(self) -> None:
        for user in self.filtered(lambda u: u.active):
            if user.company_id not in user.company_ids:
                raise ValidationError(
                    _(
                        "Company %(company_name)s is not in the allowed companies for user %(user_name)s (%(company_allowed)s).",
                        company_name=user.company_id.name,
                        user_name=user.name,
                        company_allowed=", ".join(user.mapped("company_ids.name")),
                    )
                )

    @api.constrains("action_id")
    def _check_action_id(self) -> None:
        action_open_website = self.env.ref(
            "base.action_open_website", raise_if_not_found=False
        )
        if action_open_website and any(
            user.action_id.id == action_open_website.id for user in self
        ):
            raise ValidationError(
                _('The "App Switcher" action cannot be selected as home action.')
            )
        users_sudo = self.sudo()
        client_ids = []
        window_ids = []
        for user in users_sudo:
            if user.action_id.type == "ir.actions.client":
                client_ids.append(user.action_id.id)
            elif user.action_id.type == "ir.actions.act_window":
                window_ids.append(user.action_id.id)

        if client_ids:
            for action in self.env["ir.actions.client"].sudo().browse(client_ids):
                if action.tag == "reload":
                    raise ValidationError(
                        _(
                            'The "%s" action cannot be selected as home action.',
                            action.name,
                        )
                    )
        if window_ids:
            for action in self.env["ir.actions.act_window"].sudo().browse(window_ids):
                if action.context and "active_id" in action.context:
                    raise ValidationError(
                        _(
                            'The action "%s" cannot be set as the home action because it requires a record to be selected beforehand.',
                            action.name,
                        )
                    )

    @api.constrains("group_ids")
    def _check_disjoint_groups(self) -> None:
        user_type_groups = self.env["res.groups"]._get_user_type_groups()
        for user in self:
            disjoint_groups = user.all_group_ids & user_type_groups
            if len(disjoint_groups) > 1:
                raise ValidationError(
                    _(
                        "User %(user)s cannot be at the same time in exclusive groups %(groups)s.",
                        user=repr(user.name),
                        groups=", ".join(repr(g.display_name) for g in disjoint_groups),
                    )
                )

    @api.constrains("group_ids")
    def _check_at_least_one_administrator(self) -> None:
        if not self.env.registry._init_modules:
            return
        has_admin = (
            self.env["res.users"]
            .sudo()
            .search_count(
                [
                    ("all_group_ids", "in", self.env.ref("base.group_system").ids),
                    ("active", "=", True),
                ],
                limit=1,
            )
        )
        if not has_admin:
            raise ValidationError(_("You must have at least an administrator user."))

    def _set_password(self) -> None:
        ctx = self._crypt_context()
        for user in self:
            if user.password:
                self._set_encrypted_password(user.id, ctx.hash(user.password))
            else:
                user._set_empty_password()

    def _set_empty_password(self) -> None:
        self.ensure_one()
        self.flush_recordset(["password"])
        self.env.cr.execute(
            "UPDATE res_users SET password=NULL WHERE id=%s", (self.id,)
        )
        self.invalidate_recordset(["password"])

    def _set_encrypted_password(self, uid: int, pw: str) -> None:
        if self._crypt_context().identify(pw) == "plaintext":
            msg = "Refusing to store a plaintext password — encrypt first."
            raise ValueError(msg)

        self.env.cr.execute("UPDATE res_users SET password=%s WHERE id=%s", (pw, uid))
        self.browse(uid).invalidate_recordset(["password"])

    def _rpc_api_keys_only(self) -> bool:
        return False

    def _check_credentials(
        self, credential: dict[str, Any], env: dict[str, Any]
    ) -> dict[str, Any]:
        if not (credential["type"] == "password" and credential.get("password")):
            raise AccessDenied

        interactive = env.get("interactive", True)

        if interactive or not self.env.user._rpc_api_keys_only():
            if "interactive" not in env:
                _logger.warning(
                    "_check_credentials without 'interactive' env key, assuming interactive login. \
                    Check calls and overrides to ensure the 'interactive' key is properly set in \
                    all _check_credentials environments"
                )

            self.env.cr.execute(
                "SELECT COALESCE(password, '') FROM res_users WHERE id=%s",
                [self.env.user.id],
            )
            row = self.env.cr.fetchone()
            if row is None:
                raise AccessDenied
            [hashed] = row
            valid, replacement = self._crypt_context().verify_and_update(
                credential["password"], hashed
            )
            if replacement is not None:
                self._set_encrypted_password(self.env.user.id, replacement)
                if request and self == self.env.user:
                    self.env.flush_all()
                    self.env.registry.clear_cache()
                    new_token = self.env.user._compute_session_token(
                        request.session.sid
                    )
                    request.session.session_token = new_token

            if valid:
                return {
                    "uid": self.env.user.id,
                    "auth_method": "password",
                    "mfa": "default",
                }

        if not interactive:
            if (
                self.env["res.users.apikeys"]._check_credentials(
                    scope="rpc", key=credential["password"]
                )
                == self.env.uid
            ):
                return {
                    "uid": self.env.user.id,
                    "auth_method": "apikey",
                    "mfa": "default",
                }

            if self.env.user._rpc_api_keys_only():
                _logger.info(
                    "Invalid API key or password-based authentication attempted for a non-interactive (API) "
                    "context that requires API key authentication only."
                )

        raise AccessDenied

    @api.depends_context("uid")
    def _compute_email_domain_placeholder(self) -> None:
        domain = email_domain_extract(self.env.user.email)
        self.email_domain_placeholder = (
            _("e.g. %(placeholder)s", placeholder=f"email@{domain}")
            if domain
            else _("Email")
        )

    def _compute_password(self) -> None:
        for user in self:
            user.password = ""
            user.new_password = ""

    def _set_new_password(self) -> None:
        for user in self:
            if not user.new_password:
                continue
            if user == self.env.user:
                raise UserError(
                    _(
                        "Please use the change password wizard (in User Preferences or User menu) to change your own password."
                    )
                )
            user.password = user.new_password

    @api.depends("group_ids")
    def _compute_role(self) -> None:
        group_defs = self.env["res.groups"]._get_group_definitions()
        system_id = group_defs.get_id("base.group_system")
        user_id = group_defs.get_id("base.group_user")
        for user in self:
            gids = user._effective_group_ids()
            if system_id in gids:
                user.role = "group_system"
            elif user_id in gids:
                user.role = "group_user"
            else:
                user.role = False

    @api.onchange("role")
    def _onchange_role(self) -> None:
        group_admin = self.env["res.groups"].new(
            origin=self.env.ref("base.group_system")
        )
        group_user = self.env["res.groups"].new(origin=self.env.ref("base.group_user"))
        for user in self:
            if user.role and user.has_group("base.group_user"):
                groups = user.group_ids - (group_admin + group_user)
                user.group_ids = groups + (
                    group_admin if user.role == "group_system" else group_user
                )

    @api.depends("group_ids.all_implied_ids")
    def _compute_all_group_ids(self) -> None:
        for user in self:
            user.all_group_ids = user.group_ids.all_implied_ids

    def _search_all_group_ids(self, operator: str, value: Any) -> list:
        return [("group_ids.all_implied_ids", operator, value)]

    @api.depends("name")
    def _compute_signature(self) -> None:
        for user in self.filtered(
            lambda user: user.name and is_html_empty(user.signature)
        ):
            user.signature = Markup("<div>%s</div>") % user["name"]

    @api.depends("all_group_ids")
    def _compute_share(self) -> None:
        user_group_id = self.env["ir.model.data"]._xmlid_to_res_id("base.group_user")
        internal_users = self.filtered_domain(
            [("all_group_ids", "in", [user_group_id])]
        )
        internal_users.share = False
        (self - internal_users).share = True

    def _compute_companies_count(self) -> None:
        self.companies_count = self.env["res.company"].sudo().search_count([])

    @api.depends("tz")
    def _compute_tz_offset(self) -> None:
        now = datetime.datetime.now
        tz_cache: dict[str | None, str] = {}
        for user in self:
            tz = user.tz or "GMT"
            if (offset := tz_cache.get(tz)) is None:
                offset = tz_cache[tz] = now(get_timezone(tz)).strftime("%z")
            user.tz_offset = offset

    @api.depends("all_group_ids")
    def _compute_accesses_count(self) -> None:
        all_groups = self.all_group_ids
        accesses_per_group = dict.fromkeys(all_groups.ids, 0)
        rules_per_group: dict[int, set[int]] = {gid: set() for gid in all_groups.ids}
        if all_groups:
            for group, count in self.env["ir.model.access"]._read_group(
                [("group_id", "in", all_groups.ids)], ["group_id"], ["__count"]
            ):
                accesses_per_group[group.id] = count
            for rule in self.env["ir.rule"].search_fetch(
                [("groups", "in", all_groups.ids)], ["groups"]
            ):
                for group_id in rule.groups.ids:
                    if group_id in rules_per_group:
                        rules_per_group[group_id].add(rule.id)

        for user in self:
            group_ids = user.all_group_ids.ids
            user.accesses_count = sum(accesses_per_group[gid] for gid in group_ids)
            user.rules_count = len(
                set().union(*(rules_per_group[g] for g in group_ids))
            )
            user.groups_count = len(group_ids)

    @api.depends("res_users_settings_ids")
    def _compute_res_users_settings_id(self) -> None:
        for user in self:
            user.res_users_settings_id = (
                user.res_users_settings_ids and user.res_users_settings_ids[0]
            )

    @api.model
    def _search_res_users_settings_id(self, operator: str, operand: Any) -> Domain:
        return Domain("res_users_settings_ids", operator, operand)

    @api.model
    @tools.ormcache()
    def _settings_backed_fields(self) -> frozenset[str]:
        return frozenset(
            name
            for name, field in self._fields.items()
            if field.related
            and field.related.startswith("res_users_settings_id.")
            and not field.readonly
        )

    def _settings_value_is_a_choice(self, name: str, value: Any) -> bool:
        if value:
            return True
        _, target_name = self._fields[name].related.split(".", 1)
        return not self.env["res.users.settings"]._fields[target_name].required

    @api.onchange("login")
    def on_change_login(self) -> None:
        if self.login and tools.single_email_re.match(self.login):
            self.email = self.login

    @api.onchange("parent_id")
    def onchange_parent_id(self) -> dict[str, Any] | None:
        return self.partner_id.onchange_parent_id()

    def onchange(
        self,
        values: dict[str, Any],
        field_names: list[str],
        fields_spec: dict[str, Any],
    ) -> dict[str, Any]:
        if self == self.env.user:
            user_sudo = self.sudo()
            fields_ = self._fields
            for field_name in self._self_accessible_fields()[0]:
                field = fields_[field_name]
                if field.type in ("binary", "one2many", "many2many"):
                    continue
                user_sudo[field_name]
        return super().onchange(values, field_names, fields_spec)

    def read(
        self,
        fields: collections.abc.Sequence[str] | None = None,
        load: str = "_classic_read",
    ) -> list[ValuesType]:
        readable, _ = self._self_accessible_fields()
        if (
            fields
            and self == self.env.user
            and all(key in readable or key.startswith("context_") for key in fields)
        ):
            self = self.sudo()
        return super().read(fields=fields, load=load)

    def _has_field_access(self, field: Any, operation: str) -> bool:
        return super()._has_field_access(field, operation) or (
            operation == "read"
            and self._origin == self.env.user
            and field.name in self._self_accessible_fields()[0]
        )

    def _sync_partner_company(self) -> None:
        by_company = collections.defaultdict(lambda: self.env["res.partner"])
        for user in self:
            partner = user.partner_id
            if partner.company_id and partner.company_id != user.company_id:
                by_company[user.company_id.id] |= partner
        for company_id, partners in by_company.items():
            partners.write({"company_id": company_id})

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        backed = self._settings_backed_fields()
        deferred = [
            {
                k: v
                for k, v in vals.items()
                if k in backed and self._settings_value_is_a_choice(k, v)
            }
            for vals in vals_list
        ]
        # Keyed on the values, not on `deferred`: a settings key that was
        # dropped as an absence must still not reach `super().create()`, where
        # it would meet the same missing row the deferral exists to avoid.
        if any(k in backed for vals in vals_list for k in vals):
            vals_list = [
                {k: v for k, v in vals.items() if k not in backed} for vals in vals_list
            ]
        users = super().create(vals_list)
        setting_vals = [
            {"user_id": user.id}
            for user in users
            if not user.res_users_settings_ids and user._is_internal()
        ]
        users._sync_partner_company()
        users.partner_id.active = True
        inactive = users.filtered(lambda u: not u.active)
        if inactive:
            inactive.partner_id.active = False
        for user in users:
            if not user.image_1920 and not user.share and user.name:
                user.image_1920 = user.partner_id._avatar_generate_svg()
        if setting_vals:
            self.env["res.users.settings"].sudo().create(setting_vals)
        for user, settings in zip(users, deferred, strict=True):
            if settings:
                user.write(settings)
        return users

    def _escapes_own_record(self, vals: dict[str, Any]) -> bool:
        for fname, value in vals.items():
            field = self._fields.get(fname)
            if field is None or field.type not in ("one2many", "many2many"):
                continue
            if field.type == "one2many":
                return True
            if isinstance(value, models.BaseModel) or not value:
                continue
            if not isinstance(value, (list, tuple)):
                return True
            for command in value:
                if isinstance(command, (list, tuple)):
                    if not command or command[0] not in _RELATION_ONLY_COMMANDS:
                        return True
                elif not isinstance(command, int):
                    return True
        return False

    def write(self, vals: dict[str, Any]) -> bool:
        if vals.get("active") and SUPERUSER_ID in self._ids:
            raise UserError(_("You cannot activate the superuser."))
        if vals.get("active") is False and self.env.uid in self._ids:
            raise UserError(
                _("You cannot deactivate the user you're currently logged in as.")
            )

        if vals.get("active"):
            self.partner_id.action_unarchive()

        if not self._settings_backed_fields().isdisjoint(vals):
            settings = self.env["res.users.settings"]
            for user in self:
                settings._find_or_create_for_user(user)

        if self == self.env.user and vals:
            writeable = self._self_accessible_fields()[1]
            if all(key in writeable for key in vals) and not self._escapes_own_record(
                vals
            ):
                self = self.sudo()

        res = super().write(vals)

        if "company_id" in vals:
            self._sync_partner_company()

        if "company_id" in vals or "company_ids" in vals:
            for env in list(self.env.transaction.envs):
                if env.user in self:
                    reset_cached_properties(env)

        if "group_ids" in vals and self.ids:
            self.env["ir.model.access"].call_cache_clearing_methods()
        elif self._get_invalidation_fields() & vals.keys():
            self.env.registry.clear_cache()

        return res

    @api.ondelete(at_uninstall=True)
    def _unlink_except_master_data(self) -> None:
        portal_user_template = self.env.ref("base.template_portal_user_id", False)
        public_user = self.env.ref("base.public_user", False)
        if SUPERUSER_ID in self.ids:
            raise UserError(
                _(
                    "You can not remove the admin user as it is used internally for resources created by Odoo (updates, module installation, ...)"
                )
            )
        user_admin = self.env.ref("base.user_admin", raise_if_not_found=False)
        if user_admin and user_admin in self:
            raise UserError(
                _(
                    "You cannot delete the admin user because it is utilized in various places (such as security configurations,...). Instead, archive it."
                )
            )
        self.env.registry.clear_cache()
        if portal_user_template and portal_user_template in self:
            raise UserError(
                _(
                    "Deleting the template users is not allowed. Deleting this profile will compromise critical functionalities."
                )
            )
        if public_user and public_user in self:
            raise UserError(
                _(
                    "Deleting the public user is not allowed. Deleting this profile will compromise critical functionalities."
                )
            )

    @api.model
    def name_search(
        self,
        name: str = "",
        domain: DomainType | None = None,
        operator: str = "ilike",
        limit: int = 100,
    ) -> list[tuple[int, str]]:
        domain = Domain(domain or Domain.TRUE)
        if (
            name
            and operator not in Domain.NEGATIVE_OPERATORS
            and (
                user := self.search_fetch(
                    Domain("login", "=", name) & domain, ["display_name"]
                )
            )
        ):
            return [(u.id, u.display_name) for u in user]
        return super().name_search(name, domain, operator, limit)

    @api.model
    def _search_display_name(self, operator: str, value: Any) -> list:
        domain = super()._search_display_name(operator, value)
        if operator in ("in", "ilike") and value:
            name_domain = [
                ("login", "in", [value] if isinstance(value, str) else value)
            ]
            if users := self.search(name_domain):
                domain = [("id", "in", users.ids)]
        return domain

    def copy_data(self, default: ValuesType | None = None) -> list[ValuesType]:
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for user, vals in zip(self, vals_list, strict=True):
            if ("name" not in default) and ("partner_id" not in default):
                vals["name"] = _("%s (copy)", user.name)
            if "login" not in default:
                vals["login"] = _("%s (copy)", user.login)
        return vals_list

    @api.model
    def action_get(self) -> dict[str, Any]:
        return self.env.ref("base.action_res_users_my").sudo().read()[0]

    @api.model
    def _get_invalidation_fields(self) -> set[str]:
        return {
            "group_ids",
            "active",
            "lang",
            "tz",
            "company_id",
            "company_ids",
            *self._get_session_token_fields(),
        }

    @api.model
    def _update_last_login(self) -> None:
        self.env["res.users.log"].sudo().create({})

    @api.model
    def _get_login_domain(self, login: str) -> Domain:
        return Domain("login", "=", login)

    @api.model
    def _get_email_domain(self, email: str) -> Domain:
        return Domain("email", "=ilike", tools.escape_psql(email or ""))

    @api.model
    def _get_login_order(self) -> str:
        return self._order

    def _login(
        self, credential: dict[str, Any], user_agent_env: dict[str, Any]
    ) -> dict[str, Any]:
        login = credential["login"]
        ip = request.httprequest.environ["REMOTE_ADDR"] if request else "n/a"
        try:
            with self._assert_can_auth(user=login):
                user = self.sudo().search(
                    self._get_login_domain(login),
                    order=self._get_login_order(),
                    limit=1,
                )
                if not user:
                    raise AccessDenied
                user = user.with_user(user).sudo()
                auth_info = user._check_credentials(credential, user_agent_env)
                tz = request.cookies.get("tz") if request else None
                if tz in all_timezones() and (not user.tz or not user.login_date):
                    user.tz = tz
                user._update_last_login()
        except AccessDenied:
            _logger.info("Login failed for login:%s from %s", login, ip)
            raise

        _logger.info("Login successful for login:%s from %s", login, ip)

        return auth_info

    def authenticate(
        self, credential: dict[str, Any], user_agent_env: dict[str, Any]
    ) -> dict[str, Any]:
        auth_info = self._login(credential, user_agent_env=user_agent_env)
        if user_agent_env and user_agent_env.get("base_location"):
            env = self.env(user=auth_info["uid"])
            if env.user.has_group("base.group_system"):
                try:
                    base = user_agent_env["base_location"]
                    ICP = env["ir.config_parameter"]
                    if not ICP.get_param("web.base.url.freeze"):
                        ICP.set_param("web.base.url", base)
                except Exception:
                    _logger.exception(
                        "Failed to update web.base.url configuration parameter"
                    )
        return auth_info

    @api.model
    def _check_uid_passwd(self, uid: int, passwd: str) -> None:
        if not passwd:
            raise AccessDenied
        with self._assert_can_auth(user=uid):
            passwd_hash = sha256(passwd.encode()).hexdigest()
            key_expiration = self._check_uid_passwd_cached(uid, passwd, passwd_hash)
            if key_expiration is not None and key_expiration <= fields.Datetime.now():
                raise AccessDenied

    def _get_session_token_fields(self) -> set[str]:
        return {"id", "login", "password", "active"}

    def _get_session_token_query_params(self) -> dict[str, SQL]:
        database_secret = SQL(
            "SELECT value FROM ir_config_parameter WHERE key='database.secret'"
        )
        fields = SQL(", ").join(
            SQL.identifier(self._table, fname)
            for fname in sorted(self._get_session_token_fields())
            if not self._fields[fname].relational
        )
        return {
            "select": SQL("(%s) as database_secret, %s", database_secret, fields),
            "from": SQL("res_users"),
            "joins": SQL(""),
            "where": SQL("res_users.id = %s", self.id),
            "group_by": SQL("res_users.id"),
        }

    def _session_token_get_values(self) -> tuple[tuple[str, Any], ...] | bool:
        self.env.cr.execute(
            SQL(
                "SELECT %(select)s FROM %(from)s %(joins)s WHERE %(where)s GROUP BY %(group_by)s",
                **self._get_session_token_query_params(),
            )
        )
        if self.env.cr.rowcount != 1:
            return False
        data_fields = self.env.cr.fetchone()
        cr_description = self.env.cr.description
        return tuple(
            (column.name, data_fields[index])
            for index, column in enumerate(cr_description)
        )

    def _session_token_hash_compute(
        self, sid: str, field_values: tuple[tuple[str, Any], ...] | bool
    ) -> str | bool:
        if not field_values:
            return False
        key_tuple = tuple((k, v) for k, v in field_values if v is not None)
        key = str(key_tuple).encode()
        data = sid.encode()
        h = hmac.new(key, data, sha256)
        return h.hexdigest()

    @api.model
    def change_password(self, old_passwd: str, new_passwd: str) -> bool:
        if not old_passwd:
            raise AccessDenied

        credential = {
            "login": self.env.user.login,
            "password": old_passwd,
            "type": "password",
        }
        self._check_credentials(credential, {"interactive": True})

        self.env.user._change_password(new_passwd)
        return True

    def _change_password(self, new_passwd: str) -> None:
        new_passwd = new_passwd.strip()
        if not new_passwd:
            raise UserError(
                _("Setting empty passwords is not allowed for security reasons!")
            )

        ip = request.httprequest.environ["REMOTE_ADDR"] if request else "n/a"
        _logger.info(
            "Password change for %r (#%d) by %r (#%d) from %s",
            self.login,
            self.id,
            self.env.user.login,
            self.env.user.id,
            ip,
        )

        self.password = new_passwd

    def _deactivate_portal_user(self, **post: Any) -> None:
        non_portal_users = self.filtered(lambda user: not user.share)
        if non_portal_users:
            raise AccessDenied(
                _(
                    "Only the portal users can delete their accounts. The user(s) %s can not be deleted.",
                    ", ".join(non_portal_users.mapped("name")),
                )
            )

        ip = request.httprequest.environ["REMOTE_ADDR"] if request else "n/a"

        res_users_deletion_values = []

        for user in self:
            _logger.info(
                'Account deletion asked for "%s" (#%i) from %s. Archive the user and remove login information.',
                user.login,
                user.id,
                ip,
            )

            user.write(
                {
                    "login": f"__deleted_user_{user.id}_{uuid.uuid4().hex}",
                    "password": "",
                }
            )
            user.api_key_ids._remove()

            res_users_deletion_values.append(
                {
                    "user_id": user.id,
                    "state": "todo",
                }
            )

        with contextlib.suppress(UserError, AccessError, ValidationError):
            self.with_user(SUPERUSER_ID).action_archive()
        with contextlib.suppress(UserError, AccessError, ValidationError):
            self.partner_id.action_archive()
        self.env["res.users.deletion"].create(res_users_deletion_values)

    def preference_save(self) -> dict[str, Any]:
        return {
            "type": "ir.actions.client",
            "tag": "reload_context",
        }

    def action_change_password_wizard(self) -> dict[str, Any]:
        return {
            "type": "ir.actions.act_window",
            "target": "new",
            "res_model": "change.password.wizard",
            "view_mode": "form",
        }

    @check_identity
    def preference_change_password(self) -> dict[str, Any]:
        return {
            "type": "ir.actions.act_window",
            "target": "new",
            "res_model": "change.password.own",
            "view_mode": "form",
        }

    @check_identity
    def api_key_wizard(self) -> dict[str, Any]:
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.users.apikeys.description",
            "name": "New API Key",
            "target": "new",
            "views": [(False, "form")],
        }

    @check_identity
    def action_revoke_all_devices(self) -> dict[str, Any]:
        return (
            self.env.user if self.id == self.env.uid else self
        )._action_revoke_all_devices()

    def _action_revoke_all_devices(self) -> dict[str, Any]:
        devices = self.env["res.device"].search([("user_id", "=", self.id)])
        devices.filtered(lambda d: not d.is_current)._revoke()
        return {"type": "ir.actions.client", "tag": "reload"}

    def _assert_group_query_allowed(self) -> None:
        if not (
            self.env.su
            or self == self.env.user
            or self.env.user._has_group("base.group_user")
        ):
            raise AccessError(
                _("You can only call user.has_group() with your current user.")
            )

    @api.readonly
    def has_groups(self, group_spec: str) -> bool:
        if group_spec == ".":
            return False

        positives = []
        negatives = []
        for group_ext_id in group_spec.split(","):
            group_ext_id = group_ext_id.strip()
            if group_ext_id.startswith("!"):
                negatives.append(group_ext_id.removeprefix("!"))
            else:
                positives.append(group_ext_id)

        self.ensure_one()
        self._assert_group_query_allowed()

        def _check(ext_id):
            result = self._has_group(ext_id)
            if ext_id == "base.group_no_one":
                result = result and bool(request and request.session.debug)
            return result

        if any(_check(ext_id) for ext_id in negatives):
            return False
        if any(_check(ext_id) for ext_id in positives):
            return True
        return not positives

    @api.readonly
    def has_group(self, group_ext_id: str) -> bool:
        self.ensure_one()
        self._assert_group_query_allowed()

        result = self._has_group(group_ext_id)
        if group_ext_id == "base.group_no_one":
            result = result and bool(request and request.session.debug)
        return result

    def _has_group(self, group_ext_id: str) -> bool:
        group_id = self.env["res.groups"]._get_group_definitions().get_id(group_ext_id)
        return group_id in self._effective_group_ids()

    def has_any_group_id(self, group_ids: collections.abc.Collection[int]) -> bool:
        self.ensure_one()
        self._assert_group_query_allowed()

        group_ids = set(group_ids)
        if not (request and request.session.debug):
            no_one = self.env["ir.model.data"]._xmlid_to_res_id(
                "base.group_no_one", raise_if_not_found=False
            )
            group_ids.discard(no_one)
        return not group_ids.isdisjoint(self._effective_group_ids())

    def _action_show(self) -> dict[str, Any]:
        view_id = self.env.ref("base.view_users_form").id
        action = {
            "type": "ir.actions.act_window",
            "res_model": "res.users",
            "context": {"create": False},
        }
        if len(self) > 1:
            action.update(
                {
                    "name": _("Users"),
                    "view_mode": "list,form",
                    "views": [[None, "list"], [view_id, "form"]],
                    "domain": [("id", "in", self.ids)],
                }
            )
        else:
            action.update(
                {
                    "view_mode": "form",
                    "views": [[view_id, "form"]],
                    "res_id": self.id,
                }
            )
        return action

    def action_show_groups(self) -> dict[str, Any]:
        self.ensure_one()
        return {
            "name": _("Groups"),
            "view_mode": "list,form",
            "res_model": "res.groups",
            "type": "ir.actions.act_window",
            "context": {"create": False, "delete": False},
            "domain": [("id", "in", self.all_group_ids.ids)],
            "target": "current",
        }

    def action_show_accesses(self) -> dict[str, Any]:
        self.ensure_one()
        return {
            "name": _("Access Rights"),
            "view_mode": "list,form",
            "res_model": "ir.model.access",
            "type": "ir.actions.act_window",
            "context": {"create": False, "delete": False},
            "domain": [("id", "in", self.all_group_ids.model_access.ids)],
            "target": "current",
        }

    def action_show_rules(self) -> dict[str, Any]:
        self.ensure_one()
        return {
            "name": _("Record Rules"),
            "view_mode": "list,form",
            "res_model": "ir.rule",
            "type": "ir.actions.act_window",
            "context": {"create": False, "delete": False},
            "domain": [("id", "in", self.all_group_ids.rule_groups.ids)],
            "target": "current",
        }

    def _is_internal(self) -> bool:
        self.ensure_one()
        return self._has_group("base.group_user")

    def _is_portal(self) -> bool:
        self.ensure_one()
        return self._has_group("base.group_portal")

    def _is_public(self) -> bool:
        self.ensure_one()
        return self._has_group("base.group_public")

    def _is_system(self) -> bool:
        self.ensure_one()
        return self._has_group("base.group_system")

    def _is_admin(self) -> bool:
        self.ensure_one()
        return self._is_superuser() or self._has_group("base.group_erp_manager")

    def _is_superuser(self) -> bool:
        self.ensure_one()
        return self.id == SUPERUSER_ID

    @api.model
    def get_company_currency_id(self) -> int:
        return self.env.company.currency_id.id

    @contextlib.contextmanager
    def _assert_can_auth(self, user: int | str | None = None) -> Generator[None]:
        if not request:
            yield
            return

        reg = self.env.registry
        failures_map = getattr(reg, "_login_failures", None)
        if failures_map is None:
            failures_map = reg._login_failures = collections.defaultdict(
                lambda: (0, datetime.datetime.min.replace(tzinfo=datetime.UTC))
            )

        source = request.httprequest.remote_addr
        failures, previous = failures_map[source]
        if self._on_login_cooldown(failures, previous):
            _logger.warning(
                "Login attempt ignored for %s (user %r) on %s: "
                "%d failures since last success, last failure at %s. "
                "You can configure the number of login failures before a "
                "user is put on cooldown as well as the duration in the "
                "System Parameters. Disable this feature by setting "
                '"base.login_cooldown_after" to 0.',
                source,
                user or "?",
                self.env.cr.dbname,
                failures,
                previous,
            )
            if _is_private_address(source):
                _logger.warning(
                    "The rate-limited IP address %s is classified as private "
                    "and *might* be a proxy. If your Odoo is behind a proxy, "
                    "it may be mis-configured. Check that you are running "
                    "Odoo in Proxy Mode and that the proxy is properly configured, see "
                    "https://www.odoo.com/documentation/latest/administration/install/deploy.html#https for details.",
                    source,
                )
            raise AccessDenied(
                _("Too many login failures, please wait a bit before trying again.")
            )

        try:
            yield
        except AccessDenied:
            now = datetime.datetime.now(datetime.UTC)
            failures, __ = reg._login_failures[source]
            reg._login_failures[source] = (failures + 1, now)
            if len(reg._login_failures) > LOGIN_FAILURES_PRUNE_THRESHOLD:
                delay = int(
                    self.env["ir.config_parameter"]
                    .sudo()
                    .get_param("base.login_cooldown_duration", 60)
                )
                cutoff = now - datetime.timedelta(seconds=delay)
                for src, (__, last_failure) in list(reg._login_failures.items()):
                    if last_failure < cutoff:
                        del reg._login_failures[src]
            raise
        else:
            reg._login_failures.pop(source, None)

    def _on_login_cooldown(self, failures: int, previous: datetime.datetime) -> bool:
        cfg = self.env["ir.config_parameter"].sudo()
        min_failures = int(cfg.get_param("base.login_cooldown_after", 5))
        if min_failures == 0:
            return False

        delay = int(cfg.get_param("base.login_cooldown_duration", 60))
        return failures >= min_failures and (
            datetime.datetime.now(datetime.UTC) - previous
        ) < datetime.timedelta(seconds=delay)

    def _mfa_type(self) -> str | None:
        return

    def _mfa_url(self) -> str | None:
        return

    @api.model
    def fields_get(
        self,
        allfields: collections.abc.Collection[str] | None = None,
        attributes: collections.abc.Collection[str] | None = None,
    ) -> dict[str, ValuesType]:
        res = super().fields_get(allfields, attributes=attributes)

        readable_fields, writeable_fields = self._self_accessible_fields()
        missing = (writeable_fields | readable_fields).difference(res.keys())
        if allfields:
            missing = missing.intersection(allfields)
        if missing:
            self = self.sudo()
            res.update(
                {
                    key: dict(
                        values,
                        readonly=key not in writeable_fields,
                        searchable=False,
                    )
                    for key, values in super()
                    .fields_get(sorted(missing), attributes)
                    .items()
                }
            )
        return res

    def _get_view_postprocessed(
        self, view: Any, arch: bytes, **options: Any
    ) -> tuple[bytes, dict[str, Any]]:
        arch, models = super()._get_view_postprocessed(view, arch, **options)
        if view == self.env.ref("base.view_users_form_simple_modif"):
            tree = etree.fromstring(arch)
            for node_field in tree.xpath("//field[@__groups_key__]"):
                if node_field.get("name") in self.SELF_READABLE_FIELDS:
                    node_field.attrib.pop("__groups_key__")
            arch = etree.tostring(tree)
        return arch, models


ResUsersPatchedInTest = ResUsers


class UsersMultiCompany(models.Model):
    _inherit = "res.users"

    def _multi_company_group_command(self, group_id: int) -> Any | None:
        self.ensure_one()
        company_count = len(self.sudo().company_ids)
        is_member = group_id in self.group_ids.ids
        if company_count > 1 and not is_member:
            return Command.link(group_id)
        if company_count <= 1 and is_member:
            return Command.unlink(group_id)
        return None

    def _sync_multi_company_group(self) -> None:
        group_multi_company_id = self.env["ir.model.data"]._xmlid_to_res_id(
            "base.group_multi_company", raise_if_not_found=False
        )
        if not group_multi_company_id:
            return
        link = Command.link(group_multi_company_id)
        unlink = Command.unlink(group_multi_company_id)
        to_add = to_remove = self.browse()
        for user in self:
            command = user._multi_company_group_command(group_multi_company_id)
            if command == link:
                to_add |= user
            elif command == unlink:
                to_remove |= user
        if to_remove:
            to_remove.write({"group_ids": [unlink]})
        if to_add:
            to_add.write({"group_ids": [link]})

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        users = super().create(vals_list)
        users._sync_multi_company_group()
        return users

    def write(self, vals: dict[str, Any]) -> bool:
        res = super().write(vals)
        if "company_ids" in vals:
            self._sync_multi_company_group()
        return res

    @api.model
    def new(
        self,
        values: ValuesType | None = None,
        origin: Self | None = None,
        ref: str | None = None,
    ) -> Self:
        if values is None:
            values = {}
        user = super().new(values=values, origin=origin, ref=ref)
        group_multi_company_id = self.env["ir.model.data"]._xmlid_to_res_id(
            "base.group_multi_company", raise_if_not_found=False
        )
        if group_multi_company_id:
            command = user._multi_company_group_command(group_multi_company_id)
            if command is not None:
                user.update({"group_ids": [command]})
        return user
