import logging
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import Any

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Field
from odoo.http import (
    STORED_SESSION_BYTES,
    GeoIP,
    get_session_max_inactivity,
    request,
    root,
)
from odoo.libs.debug_log import DebugLog
from odoo.tools import SQL, OrderedSet

from .res_users import check_identity

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)

# The mobile platforms odoo.libs._vendor.useragents.UserAgentParser can emit.
_MOBILE_PLATFORMS = frozenset(
    {"android", "iphone", "ipad", "blackberry", "symbian", "windows phone"}
)

_DISPLAY_NAMES = {
    "blackberry": "BlackBerry",
    "chromeos": "ChromeOS",
    "freebsd": "FreeBSD",
    "ipad": "iPad",
    "iphone": "iPhone",
    "macos": "macOS",
    "msie": "Internet Explorer",
    "netbsd": "NetBSD",
    "openbsd": "OpenBSD",
    "samsung": "Samsung Internet",
}

DEFAULT_RETENTION_DAYS = 90
_REVOKE_SWEEP_BATCH = 10_000
_RETENTION_BATCH = 10_000


def _device_type(platform: str | None) -> str:
    return "mobile" if (platform or "").lower() in _MOBILE_PLATFORMS else "computer"


def _display(name: str) -> str:
    return _DISPLAY_NAMES.get(name) or name.title()


def _utc_naive(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=UTC).replace(tzinfo=None)


def _current_session_identifier() -> str | None:
    session = request.session if request else None
    if session is None or not session.sid:
        return None
    return session.sid[:STORED_SESSION_BYTES]


class ResDevice(models.Model):
    _name = "res.device"
    _description = "Devices"
    _order = "last_activity desc, id desc"
    _rec_names_search = ["platform", "browser"]

    user_id = fields.Many2one(
        comodel_name="res.users",
        required=True,
        ondelete="cascade",
    )
    session_identifier = fields.Char(
        index="btree",
        required=True,
    )
    platform = fields.Char()
    browser = fields.Char()
    device_type = fields.Selection(
        selection=[("computer", "Computer"), ("mobile", "Mobile")]
    )
    ip_address = fields.Char(string="IP Address")
    country = fields.Char()
    city = fields.Char()
    first_activity = fields.Datetime()
    last_activity = fields.Datetime(index="btree")
    active = fields.Boolean(
        default=True,
        help="Unset once the session this device used no longer exists.",
    )
    log_ids = fields.One2many(
        comodel_name="res.device.log",
        inverse_name="device_id",
        string="Addresses",
    )
    is_current = fields.Boolean(
        string="Current Device",
        compute="_compute_is_current",
        order_by_sql="_is_current_order_sql",
    )

    _identity_uniq = models.UniqueIndex(
        "(user_id, session_identifier, platform, browser) NULLS NOT DISTINCT"
    )

    @api.depends("platform", "browser")
    def _compute_display_name(self) -> None:
        for device in self:
            unknown = self.env._("Unknown")
            platform = _display(device.platform) if device.platform else unknown
            browser = _display(device.browser) if device.browser else unknown
            device.display_name = f"{platform} {browser}"

    @api.depends("session_identifier")
    def _compute_is_current(self) -> None:
        current = _current_session_identifier()
        for device in self:
            device.is_current = current is not None and (
                device.session_identifier == current
            )

    def _is_current_order_sql(
        self, field: Field, alias: str, direction: Any, nulls: Any, query: Any
    ) -> SQL:
        current = _current_session_identifier()
        if current is None:
            # no session to compare against: the term sorts nothing
            return SQL.EMPTY
        _debug.logic("order_by_is_current", direction=str(direction))
        return SQL(
            "%s = %s %s",
            SQL.identifier(alias, "session_identifier"),
            current,
            direction,
        )

    @api.model
    def _update_device(self, request: Any) -> None:
        trace = request.session.update_trace(request)
        if not trace:
            _debug.logic("device_log_skipped", reason="trace_unchanged")
            return

        geoip = GeoIP(trace["ip_address"], app=request.app)
        values = {
            "user_id": request.session.uid,
            "session_identifier": request.session.sid[:STORED_SESSION_BYTES],
            "platform": trace["platform"],
            "browser": trace["browser"],
            "device_type": _device_type(trace["platform"]),
            "ip_address": trace["ip_address"],
            "country": geoip.get("country_name"),
            "city": geoip.get("city"),
            "first_activity": _utc_naive(trace["first_activity"]),
            "last_activity": _utc_naive(trace["last_activity"]),
            "now": self.env.cr.now(),
        }
        upsert = SQL(
            """
            WITH device AS (
                INSERT INTO res_device AS d (
                    user_id, session_identifier, platform, browser, device_type,
                    ip_address, country, city, first_activity, last_activity, active,
                    create_uid, create_date, write_uid, write_date
                )
                VALUES (
                    %(user_id)s, %(session_identifier)s, %(platform)s, %(browser)s,
                    %(device_type)s, %(ip_address)s, %(country)s, %(city)s,
                    %(first_activity)s, %(last_activity)s, TRUE,
                    %(user_id)s, %(now)s, %(user_id)s, %(now)s
                )
                ON CONFLICT (user_id, session_identifier, platform, browser)
                DO UPDATE SET
                    ip_address = CASE WHEN d.last_activity > EXCLUDED.last_activity
                        THEN d.ip_address ELSE EXCLUDED.ip_address END,
                    country = CASE WHEN d.last_activity > EXCLUDED.last_activity
                        THEN d.country ELSE EXCLUDED.country END,
                    city = CASE WHEN d.last_activity > EXCLUDED.last_activity
                        THEN d.city ELSE EXCLUDED.city END,
                    first_activity = LEAST(d.first_activity, EXCLUDED.first_activity),
                    last_activity = GREATEST(d.last_activity, EXCLUDED.last_activity),
                    active = TRUE,
                    write_uid = EXCLUDED.write_uid,
                    write_date = EXCLUDED.write_date
                RETURNING id
            )
            INSERT INTO res_device_log AS l (
                device_id, ip_address, country, city, first_activity, last_activity,
                create_uid, create_date, write_uid, write_date
            )
            SELECT id, %(ip_address)s, %(country)s, %(city)s,
                   %(first_activity)s, %(last_activity)s,
                   %(user_id)s, %(now)s, %(user_id)s, %(now)s
            FROM device
            ON CONFLICT (device_id, ip_address) DO UPDATE SET
                country = EXCLUDED.country,
                city = EXCLUDED.city,
                first_activity = LEAST(l.first_activity, EXCLUDED.first_activity),
                last_activity = GREATEST(l.last_activity, EXCLUDED.last_activity),
                write_uid = EXCLUDED.write_uid,
                write_date = EXCLUDED.write_date
            """,
            **values,
        )
        own_cursor = self.env.cr.readonly
        if own_cursor:
            with self.env.registry.cursor(readonly=False) as cr:
                cr.execute(upsert)
        else:
            # Contain this optional write without flushing unrelated pending
            # ORM work: a failure must not abort the request's transaction.
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(upsert)
        _logger.info(
            "User %d device seen: %s %s",
            values["user_id"],
            values["platform"],
            values["browser"],
        )
        _debug.lifecycle(
            "device_upserted",
            uid=values["user_id"],
            platform=values["platform"],
            browser=values["browser"],
            device_type=values["device_type"],
            own_cursor=own_cursor,
        )

    @check_identity
    def revoke(self) -> dict[str, Any] | None:
        if self._revoke():
            return {"type": "ir.actions.client", "tag": "reload"}
        return None

    def _revoke(self) -> bool:
        if not self:
            _debug.logic("revoke_skipped", uid=self.env.uid, reason="empty_recordset")
            return False
        if not self.env.is_system() and self.mapped("user_id") != self.env.user:
            _debug.logic("revoke_refused", uid=self.env.uid, devices=self.ids)
            raise AccessError(self.env._("You can only revoke your own devices."))
        session_identifiers = list(OrderedSet(self.mapped("session_identifier")))
        must_logout = any(self.mapped("is_current"))
        root.session_store.remove_sessions_for_identifiers(session_identifiers)
        revoked = self._mark_revoked(session_identifiers)
        _logger.info(
            "User %d revokes %d session(s) of user(s) %s",
            self.env.uid,
            len(session_identifiers),
            self.mapped("user_id").ids,
        )
        _debug.lifecycle(
            "devices_revoked",
            uid=self.env.uid,
            sessions=len(session_identifiers),
            devices=revoked,
            logout=must_logout,
        )
        if must_logout:
            request.session.logout()
        return must_logout

    @api.model
    def _mark_revoked(self, session_identifiers: Collection[str]) -> int:
        self.flush_model(["session_identifier", "active"])
        self.env.cr.execute(
            SQL(
                """
                UPDATE res_device
                SET active = FALSE, write_uid = %s, write_date = %s
                WHERE session_identifier = ANY(%s) AND active
                """,
                self.env.uid,
                self.env.cr.now(),
                list(session_identifiers),
            )
        )
        revoked = self.env.cr.rowcount
        self.invalidate_model(["active", "write_uid", "write_date"])
        return revoked

    @api.model
    def _mark_logged_out(self, session_identifier: str) -> None:
        if self.env.cr.readonly:
            # the sweep archives it once the store reports the family gone
            _debug.logic("devices_logged_out_deferred", reason="readonly_cursor")
            return
        archived = self._mark_revoked([session_identifier])
        _debug.lifecycle("devices_logged_out", uid=self.env.uid, devices=archived)

    @api.autovacuum
    def _update_revoked(self) -> tuple[int, bool]:
        inactive_since = fields.Datetime.now() - timedelta(
            seconds=get_session_max_inactivity(self.env)
        )
        self.env.cr.execute(
            SQL(
                """
                SELECT DISTINCT session_identifier
                FROM res_device
                WHERE active AND last_activity < %s
                """,
                inactive_since,
            )
        )
        candidates = [identifier for (identifier,) in self.env.cr.fetchall()]
        _debug.pipeline("revoke_sweep_start", candidates=len(candidates))
        revoked = 0
        for batch in batched(candidates, _REVOKE_SWEEP_BATCH, strict=False):
            missing = root.session_store.get_missing_session_identifiers(batch)
            _debug.pipeline(
                "revoke_sweep", candidates=len(batch), missing_sessions=len(missing)
            )
            if not missing:
                continue
            count = self._mark_revoked(missing)
            revoked += count
            _debug.lifecycle("devices_revoked", count=count, by="gc")
            if not self.env["ir.cron"]._commit_progress(count):
                _debug.logic("revoke_sweep_stopped", reason="time_budget")
                return revoked, True
        _debug.lifecycle("revoke_sweep_done", revoked=revoked)
        return revoked, False

    @api.autovacuum
    def _gc_revoked_devices(self) -> tuple[int, bool] | None:
        cutoff = self._retention_cutoff()
        if cutoff is None:
            _debug.logic("gc_revoked_devices_skipped", reason="retention_disabled")
            return None
        self.env.cr.execute(
            SQL(
                """
                DELETE FROM res_device
                WHERE id IN (
                    SELECT id
                    FROM res_device
                    WHERE active IS NOT TRUE
                      AND (last_activity IS NULL OR last_activity < %s)
                    ORDER BY id
                    LIMIT %s
                )
                """,
                cutoff,
                _RETENTION_BATCH,
            )
        )
        deleted = self.env.cr.rowcount
        _logger.info("GC revoked devices delete %d entries", deleted)
        _debug.lifecycle("gc_revoked_devices", cutoff=str(cutoff), count=deleted)
        return deleted, deleted == _RETENTION_BATCH

    @api.model
    def _retention_cutoff(self) -> datetime | None:
        retention_days = self.env["ir.config_parameter"].get_param_int(
            "base.device_retention_days", DEFAULT_RETENTION_DAYS
        )
        if retention_days <= 0:
            return None
        return self.env.cr.now() - timedelta(days=retention_days)


class ResDeviceLog(models.Model):
    _name = "res.device.log"
    _description = "Device Address"
    _order = "last_activity desc, id desc"
    _rec_name = "ip_address"

    device_id = fields.Many2one(
        comodel_name="res.device",
        required=True,
        ondelete="cascade",
    )
    ip_address = fields.Char(string="IP Address")
    country = fields.Char()
    city = fields.Char()
    first_activity = fields.Datetime()
    last_activity = fields.Datetime()

    _device_address_uniq = models.UniqueIndex(
        "(device_id, ip_address) NULLS NOT DISTINCT"
    )

    @api.autovacuum
    def _gc_stale_addresses(self) -> tuple[int, bool] | None:
        cutoff = self.env["res.device"]._retention_cutoff()
        if cutoff is None:
            _debug.logic("gc_stale_addresses_skipped", reason="retention_disabled")
            return None
        self.env.cr.execute(
            SQL(
                """
                DELETE FROM res_device_log
                WHERE id IN (
                    SELECT address.id
                    FROM res_device_log address
                    JOIN res_device device ON device.id = address.device_id
                    WHERE address.last_activity < %s
                      AND address.ip_address IS DISTINCT FROM device.ip_address
                    ORDER BY address.id
                    LIMIT %s
                )
                """,
                cutoff,
                _RETENTION_BATCH,
            )
        )
        deleted = self.env.cr.rowcount
        _logger.info("GC stale device addresses delete %d entries", deleted)
        _debug.lifecycle("gc_stale_addresses", cutoff=str(cutoff), count=deleted)
        return deleted, deleted == _RETENTION_BATCH
