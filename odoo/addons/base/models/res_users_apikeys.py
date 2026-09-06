import binascii
import datetime
import logging
import os
from hashlib import sha256
from typing import Any, Self

from odoo import _, api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.http import request
from odoo.libs.password import CryptContext
from odoo.tools import SQL, str2bool

from .res_users import check_identity

_logger = logging.getLogger(__name__)

API_KEY_SIZE = 20
INDEX_SIZE = 8
#: how many live keys a user may hold before `generate` refuses to issue more.
#: Overridable per database with `base.programmatic_api_keys_limit`.
PROGRAMMATIC_KEYS_LIMIT = 10
KEY_CRYPT_CONTEXT = CryptContext(
    ["pbkdf2_sha512"],
    pbkdf2_sha512__rounds=6000,
)


class ResUsersApikeys(models.Model):
    _name = "res.users.apikeys"
    _description = "Users API Keys"
    _auto = False
    _allow_sudo_commands = False

    name = fields.Char("Description", required=True, readonly=True)
    user_id = fields.Many2one(
        "res.users",
        index=True,
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    scope = fields.Char("Scope", readonly=True)
    create_date = fields.Datetime("Creation Date", readonly=True)
    expiration_date = fields.Datetime("Expiration Date", readonly=True)

    def init(self) -> None:
        table = SQL.identifier(self._table)
        self.env.cr.execute(
            SQL(
                f"""
                CREATE TABLE IF NOT EXISTS %s (
                    id serial primary key,
                    name varchar not null,
                    user_id integer not null REFERENCES res_users(id) ON DELETE CASCADE,
                    scope varchar,
                    expiration_date timestamp without time zone,
                    index varchar({INDEX_SIZE}) not null CHECK (char_length(index) = {INDEX_SIZE}),
                    key varchar not null,
                    create_date timestamp without time zone DEFAULT (now() at time zone 'UTC')
                )
                """,
                table,
            )
        )

        index_name = self._table + "_user_id_index_idx"
        if len(index_name) > 63:
            index_name = (
                self._table[:50]
                + "_idx_"
                + sha256(self._table.encode()).hexdigest()[:8]
            )
        self.env.cr.execute(
            SQL(
                "CREATE INDEX IF NOT EXISTS %s ON %s (user_id, index)",
                SQL.identifier(index_name),
                table,
            )
        )

    @check_identity
    def remove(self) -> dict[str, str]:
        return self._remove()

    def _remove(self) -> dict[str, str]:
        if not self:
            return {"type": "ir.actions.act_window_close"}
        if self.env.is_system() or self.mapped("user_id") == self.env.user:
            ip = request.httprequest.environ["REMOTE_ADDR"] if request else "n/a"
            _logger.info(
                "API key(s) removed: scope: <%s> for '%s' (#%s) from %s",
                self.mapped("scope"),
                self.env.user.login,
                self.env.uid,
                ip,
            )
            self.sudo().unlink()
            return {"type": "ir.actions.act_window_close"}
        raise AccessError(
            _(
                "You can not remove API keys unless they're yours or you are a system user"
            )
        )

    def unlink(self) -> bool:
        res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _check_credentials(self, *, scope: str, key: str) -> int | None:
        if not scope or not key:
            msg = "scope and key required"
            raise ValueError(msg)
        index = key[:INDEX_SIZE]
        self.env.cr.execute(
            SQL(
                """
                SELECT user_id, key
                FROM %s INNER JOIN res_users u ON (u.id = user_id)
                WHERE
                    u.active and index = %s
                    AND (scope IS NULL OR scope = %s)
                    AND (
                        expiration_date IS NULL OR
                        expiration_date >= now() at time zone 'utc'
                    )
                """,
                SQL.identifier(self._table),
                index,
                scope,
            )
        )
        for user_id, current_key in self.env.cr.fetchall():
            if KEY_CRYPT_CONTEXT.verify(key, current_key):
                return user_id
        return None

    def _get_key_expiration(self, *, scope: str, key: str) -> datetime.datetime | None:
        if not scope or not key:
            return None
        index = key[:INDEX_SIZE]
        self.env.cr.execute(
            SQL(
                """
                SELECT key, expiration_date
                FROM %s INNER JOIN res_users u ON (u.id = user_id)
                WHERE u.active AND index = %s AND (scope IS NULL OR scope = %s)
                """,
                SQL.identifier(self._table),
                index,
                scope,
            )
        )
        for current_key, expiration_date in self.env.cr.fetchall():
            if KEY_CRYPT_CONTEXT.verify(key, current_key):
                return expiration_date
        return None

    def _get_max_duration(self) -> float:
        return (
            max(
                (group.api_key_duration for group in self.env.user.all_group_ids),
                default=0.0,
            )
            or 1.0
        )

    def _check_expiration_date(self, date: datetime.datetime | None) -> None:
        if self.env.is_system():
            return
        if not date:
            raise ValidationError(_("The API key must have an expiration date"))
        max_duration = self._get_max_duration()
        if date > fields.Datetime.now() + datetime.timedelta(days=max_duration):
            raise ValidationError(
                _("You cannot exceed %(duration)s days.", duration=max_duration)
            )

    def _check_generate_access(self) -> None:
        if not self.env.user._is_internal():
            raise AccessError(_("Only internal users can create API keys"))

    def _generate(
        self,
        scope: str | None,
        name: str,
        expiration_date: datetime.datetime | None,
    ) -> str:
        self._check_generate_access()
        self._check_expiration_date(expiration_date)
        k = binascii.hexlify(os.urandom(API_KEY_SIZE)).decode()
        self.env.cr.execute(
            SQL(
                """
                INSERT INTO %s (name, user_id, scope, expiration_date, key, index)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                SQL.identifier(self._table),
                name,
                self.env.user.id,
                scope,
                expiration_date or None,
                KEY_CRYPT_CONTEXT.hash(k),
                k[:INDEX_SIZE],
            )
        )

        ip = request.httprequest.environ["REMOTE_ADDR"] if request else "n/a"
        _logger.info(
            "%s generated: scope: <%s> for '%s' (#%s) from %s",
            self._description,
            scope,
            self.env.user.login,
            self.env.uid,
            ip,
        )

        return k

    def _check_programmatic_access(self) -> None:
        """Issuing keys without a browser is opt-in, per database.

        A system user is exempt: they can flip the parameter anyway, and doing
        it around every call would leave a window in which *everyone* may
        manage keys programmatically -- three writes that are not atomic, and
        a server that dies between them leaves the door open.
        """
        enabled = str2bool(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("base.enable_programmatic_api_keys"),
            False,
        )
        if not (self.env.is_system() or enabled):
            raise UserError(_("Programmatic API keys are not enabled"))

    def _get_programmatic_limit(self) -> int:
        value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("base.programmatic_api_keys_limit", PROGRAMMATIC_KEYS_LIMIT)
        )
        try:
            return int(value)
        except TypeError, ValueError:
            _logger.warning(
                "Ignoring invalid 'base.programmatic_api_keys_limit' %r, using %s",
                value,
                PROGRAMMATIC_KEYS_LIMIT,
            )
            return PROGRAMMATIC_KEYS_LIMIT

    @api.model
    def generate(
        self,
        key: str,
        scope: str | None,
        name: str,
        expiration_date: datetime.datetime | str | None,
    ) -> str:
        """Issue a new API key, authenticated by an existing one.

        `key` must be a live key of the calling user. A key with no scope
        opens any scope; a scoped key only opens its own -- `_check_credentials`
        is what decides, and the scope it accepted is the one handed to
        `_generate`.

        To rotate: generate the replacement, store it, then `revoke` the old
        one. Doing it in that order means a crash in between costs a stale key,
        not a locked-out integration.
        """
        self._check_programmatic_access()
        with self.env["res.users"]._assert_can_auth(user=key[:INDEX_SIZE]):
            if not isinstance(expiration_date, datetime.datetime):
                expiration_date = fields.Datetime.from_string(expiration_date)

            live_keys = self.search_count(
                [
                    ("user_id", "=", self.env.uid),
                    "|",
                    ("expiration_date", "=", False),
                    ("expiration_date", ">=", self.env.cr.now()),
                ]
            )
            limit = self._get_programmatic_limit()
            if live_keys >= limit:
                raise UserError(
                    _(
                        "Limit of %(limit)s API keys is reached for programmatic "
                        "creation",
                        limit=limit,
                    )
                )

            uid = self._check_credentials(scope=scope or "rpc", key=key)
            if not uid or uid != self.env.uid:
                raise AccessDenied(
                    _(
                        "The provided API key is invalid or does not belong to "
                        "the current user."
                    )
                )

            new_key = self._generate(scope, name, expiration_date)
            _logger.info(
                "%s %r generated from %r",
                self._description,
                new_key[:INDEX_SIZE],
                key[:INDEX_SIZE],
            )
            return new_key

    @api.model
    def revoke(self, key: str) -> bool:
        """Remove an API key, given the key itself."""
        self._check_programmatic_access()
        if not key:
            msg = "key required"
            raise ValueError(msg)
        with self.env["res.users"]._assert_can_auth(user=key[:INDEX_SIZE]):
            self.env.cr.execute(
                SQL(
                    """
                    SELECT id, key
                    FROM %s
                    WHERE
                        index = %s
                        AND (
                            expiration_date IS NULL OR
                            expiration_date >= now() at time zone 'utc'
                        )
                    """,
                    SQL.identifier(self._table),
                    key[:INDEX_SIZE],
                )
            )
            for key_id, current_key in self.env.cr.fetchall():
                if KEY_CRYPT_CONTEXT.verify(key, current_key):
                    # _remove refuses a key that is neither yours nor system's
                    self.browse(key_id)._remove()
                    return True
            raise AccessDenied(_("The provided API key is invalid."))

    @api.autovacuum
    def _gc_user_apikeys(self) -> None:
        self.env.cr.execute(
            SQL(
                """
            DELETE FROM %s
            WHERE
                expiration_date IS NOT NULL AND
                expiration_date < now() at time zone 'utc'
        """,
                SQL.identifier(self._table),
            )
        )
        count = self.env.cr.rowcount
        if count:
            self.env.registry.clear_cache()
        _logger.info("GC %r delete %d entries", self._name, count)


class ResUsersApikeysDescription(models.TransientModel):
    _name = "res.users.apikeys.description"
    _description = "API Key Description"

    def _selection_duration(self) -> list[tuple[str, str]]:
        durations = [
            ("1", "1 Day"),
            ("7", "1 Week"),
            ("30", "1 Month"),
            ("90", "3 Months"),
            ("180", "6 Months"),
            ("365", "1 Year"),
        ]
        persistent_duration = (
            "0",
            "Persistent Key",
        )
        custom_duration = (
            "-1",
            "Custom Date",
        )
        if self.env.is_system():
            return durations + [persistent_duration, custom_duration]
        max_duration = self.env["res.users.apikeys"]._get_max_duration()
        return list(
            filter(lambda duration: int(duration[0]) <= max_duration, durations)
        ) + [custom_duration]

    name = fields.Char("Description", required=True)
    duration = fields.Selection(
        selection="_selection_duration",
        string="Duration",
        required=True,
        default=lambda self: self._selection_duration()[0][0],
    )
    expiration_date = fields.Datetime(
        "Expiration Date",
        compute="_compute_expiration_date",
        store=True,
        readonly=False,
    )

    @api.depends("duration")
    def _compute_expiration_date(self) -> None:
        for record in self:
            duration = int(record.duration)
            if duration >= 0:
                record.expiration_date = (
                    fields.Datetime.now() + datetime.timedelta(days=duration)
                    if duration
                    else None
                )

    @api.onchange("expiration_date")
    def _onchange_expiration_date(self) -> dict[str, Any] | None:
        try:
            self.env["res.users.apikeys"]._check_expiration_date(self.expiration_date)
        except UserError as error:
            warning = {
                "type": "notification",
                "title": _("The API key duration is not correct."),
                "message": error.args[0],
            }
            return {"warning": warning}

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        records = super().create(vals_list)
        apikeys = self.env["res.users.apikeys"]
        for record in records:
            apikeys._check_expiration_date(record.expiration_date)
        return records

    @check_identity
    def action_generate_key(self) -> dict[str, Any]:
        self.check_access_generate_key()

        description = self.sudo()
        k = self.env["res.users.apikeys"]._generate(
            None, description.name, self.expiration_date
        )
        description.unlink()

        return {
            "type": "ir.actions.act_window",
            "res_model": "res.users.apikeys.show",
            "name": _("API Key Ready"),
            "views": [(False, "form")],
            "target": "new",
            "context": {
                "default_key": k,
            },
        }

    def check_access_generate_key(self) -> None:
        self.env["res.users.apikeys"]._check_generate_access()


class ResUsersApikeysShow(models.AbstractModel):
    _name = "res.users.apikeys.show"
    _description = "Show API Key"

    id = fields.Id()
    key = fields.Char(readonly=True)
