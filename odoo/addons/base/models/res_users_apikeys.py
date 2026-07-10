import binascii
import datetime
import logging
import os
from hashlib import sha256
from typing import Any, Self

from odoo import _, api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.tools import SQL
from odoo.tools.password import CryptContext

from .res_users import check_identity

_logger = logging.getLogger(__name__)

# API keys support
API_KEY_SIZE = 20  # in bytes
INDEX_SIZE = 8  # in hex digits, so 4 bytes, or 20% of the key
KEY_CRYPT_CONTEXT = CryptContext(
    # default 29000 rounds (25~50ms) is unnecessary here: keys are fully random,
    # so dictionary attacks aren't a concern
    ["pbkdf2_sha512"],
    pbkdf2_sha512__rounds=6000,
)


class ResUsersApikeys(models.Model):
    _name = "res.users.apikeys"
    _description = "Users API Keys"
    _auto = False  # so we can have a secret column
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
        # INDEX_SIZE is embedded directly because DDL structural positions
        # (varchar length, CHECK constraints) cannot use server-side binding.
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
            # unique determinist index name
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
        """Remove the API key(s) without an identity check.

        Use :meth:`remove` for the identity-checked path; this variant skips it
        (mainly to remove trusted devices).
        """
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
        # AK-P2 (audit 2026-07-06): revoking a key MUST drop the memoised
        # credential check. `res.users._check_uid_passwd_cached` memoises
        # *successful* authentications (including the API-key path); without this
        # clear a revoked key keeps authenticating RPC until an unrelated
        # invalidation. Clearing here rather than only in `_remove` also covers
        # direct deletion via `res.users.api_key_ids` (a SELF_WRITEABLE_FIELDS
        # one2many, so `Command.delete` bypasses `_remove`). Key creation needs
        # no clear: a failed check raises and ormcache memoises values, not
        # exceptions.
        res = super().unlink()
        self.env.registry.clear_cache()
        return res

    def _check_credentials(self, *, scope: str, key: str) -> int | None:
        """Return the user id whose API key matches ``key`` for ``scope``, else None.

        :param str scope: the requested scope; a NULL-scope stored key matches any
            scope, a scoped key matches only its own scope.
        :param str key: the cleartext API key to verify.
        :return: the owning user id, or None when no active, unexpired key matches.
        :rtype: int | None
        """
        # AK-L1 (audit 2026-05-28, S3 latent, accepted): candidate rows are
        # narrowed by `index = key[:INDEX_SIZE]`, the first 8 hex chars (32 bits)
        # stored in cleartext for lookup speed. Deliberate trade-off: the full
        # secret is only stored as a salted pbkdf2 hash, so DB read access still
        # leaves the remaining 128 bits infeasible. verify() calls scale with
        # prefix collisions, not the secret, so this is not a timing oracle.
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
            if key and KEY_CRYPT_CONTEXT.verify(key, current_key):
                return user_id
        return None

    def _get_max_duration(self) -> float:
        """Return the maximum API-key duration (in days) for ``self.env.user``.

        The highest ``api_key_duration`` across the user's groups; a user whose
        groups grant none is coerced to 1.0 day rather than denied key creation.
        """
        return (
            max(
                (group.api_key_duration for group in self.env.user.all_group_ids),
                default=0.0,
            )
            or 1.0
        )

    def _check_expiration_date(self, date: datetime.datetime | None) -> None:
        """Validate ``date`` against the caller's allowed API-key duration.

        :param date: the requested expiration date, or None for a persistent key.
        :raises ValidationError: when a non-system user omits the date or exceeds
            the maximum duration allowed by their group privileges.
        """
        # A system (or sudoed) user may create a persistent key or exceed the
        # user's maximum duration.
        if self.env.is_system():
            return
        if not date:
            raise ValidationError(_("The API key must have an expiration date"))
        max_duration = self._get_max_duration()
        # fields.Datetime.now() is freeze-time patchable (matching
        # _compute_expiration_date), unlike datetime.now(UTC).
        if date > fields.Datetime.now() + datetime.timedelta(days=max_duration):
            raise ValidationError(
                _("You cannot exceed %(duration)s days.", duration=max_duration)
            )

    def _generate(
        self,
        scope: str | None,
        name: str,
        expiration_date: datetime.datetime | None,
    ) -> str:
        """Generate an API key for ``self.env.user`` and return its cleartext value.

        :param str scope: the scope of the key. If None, the key gives access to any rpc.
        :param str name: the name of the key, mainly intended to be displayed in the UI.
        :param expiration_date: the expiration date of the key, or None for a
            persistent (infinite-duration) key.
        :return: the cleartext key.
        :rtype: str
        :raises AccessError: when ``self.env.user`` is not an internal user.
        """
        # AK-P1 (audit 2026-05-28): enforce the "only internal users hold API
        # keys" invariant at the minting primitive, not only the make_key UI
        # path, so any caller of _generate is self-guarded. Exceeding the user's
        # max duration requires a sudoed env (env.is_system()).
        if not self.env.user._is_internal():
            raise AccessError(_("Only internal users can create API keys"))
        self._check_expiration_date(expiration_date)
        # no need to clear the LRU when *adding* a key, only when removing
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
            # AK-P2: a key that authenticated while valid may still be memoised
            # in res.users._check_uid_passwd_cached past its expiration date;
            # this raw DELETE bypasses unlink(), so clear the cache here too.
            self.env.registry.clear_cache()
        _logger.info("GC %r delete %d entries", self._name, count)


class ResUsersApikeysDescription(models.TransientModel):
    _name = "res.users.apikeys.description"
    _description = "API Key Description"

    def _selection_duration(self) -> list[tuple[str, str]]:
        # duration value is a string representing the number of days.
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
        )  # Magic value to detect an infinite duration
        custom_duration = (
            "-1",
            "Custom Date",
        )  # Will force the user to enter a date manually
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
        # Validate per record: reading `expiration_date` on the whole batch
        # would raise an ensure_one ValueError for a multi-record create.
        apikeys = self.env["res.users.apikeys"]
        for record in records:
            apikeys._check_expiration_date(record.expiration_date)
        return records

    @check_identity
    def make_key(self) -> dict[str, Any]:
        # only create keys for users who can delete their keys
        self.check_access_make_key()

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

    def check_access_make_key(self) -> None:
        if not self.env.user._is_internal():
            raise AccessError(_("Only internal users can create API keys"))


class ResUsersApikeysShow(models.AbstractModel):
    _name = "res.users.apikeys.show"
    _description = "Show API Key"

    # the field 'id' is necessary for the onchange that returns the value of 'key'
    id = fields.Id()
    key = fields.Char(readonly=True)
