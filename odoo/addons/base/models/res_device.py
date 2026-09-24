import functools
import logging
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from itertools import batched
from typing import Any

from odoo import api, fields, models
from odoo.db.schema import drop_view_if_exists
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

# One device is one browser on one platform in one session of one user; its log
# holds one row per IP address it was seen from.
_DEVICE_IDENTITY = ("user_id", "session_identifier", "platform", "browser")

_REVOKE_SWEEP_BATCH = 10_000


def _device_type(platform: str | None) -> str:
    return "mobile" if (platform or "").lower() in _MOBILE_PLATFORMS else "computer"


def _utc_naive(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=UTC).replace(tzinfo=None)


def _current_session_identifier() -> str | None:
    session = request.session if request else None
    if session is None or not session.sid:
        return None
    return session.sid[:STORED_SESSION_BYTES]


class ResDeviceMixin(models.AbstractModel):
    _name = "res.device.mixin"
    _description = "Device"
    _rec_names_search = ["platform", "browser"]

    session_identifier = fields.Char(
        index="btree",
        required=True,
    )
    platform = fields.Char()
    browser = fields.Char()
    ip_address = fields.Char(string="IP Address")
    country = fields.Char()
    city = fields.Char()
    device_type = fields.Selection(
        selection=[("computer", "Computer"), ("mobile", "Mobile")]
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        index="btree",
        ondelete="cascade",
    )
    first_activity = fields.Datetime()
    last_activity = fields.Datetime()
    revoked = fields.Boolean(
        help="If True, the session file corresponding to this device"
        " no longer exists on the filesystem."
    )
    is_current = fields.Boolean(
        string="Current Device",
        compute="_compute_is_current",
        order_by_sql="_is_current_order_sql",
    )
    linked_ip_addresses = fields.Text(
        string="Linked IP address",
        compute="_compute_linked_ip_addresses",
    )

    @api.depends("platform", "browser")
    def _compute_display_name(self) -> None:
        for device in self:
            platform = device.platform or self.env._("Unknown")
            browser = device.browser or self.env._("Unknown")
            device.display_name = f"{platform.capitalize()} {browser.capitalize()}"

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

    def _device_identity(self) -> tuple[Any, ...]:
        return tuple(
            self[name].id if name == "user_id" else self[name]
            for name in _DEVICE_IDENTITY
        )

    @api.depends(*_DEVICE_IDENTITY)
    def _compute_linked_ip_addresses(self) -> None:
        query = self.env["res.device.log"]._search(
            [("session_identifier", "in", list(set(self.mapped("session_identifier"))))]
        )
        column = functools.partial(SQL.identifier, query.table)
        identity = [column(name) for name in _DEVICE_IDENTITY]
        query.order = None
        query.groupby = SQL(", ").join(identity)
        rows = self.env.execute_query(
            query.select(
                *identity,
                SQL(
                    "array_agg(%s ORDER BY %s DESC, %s DESC) FILTER (WHERE %s IS NOT NULL)",
                    column("ip_address"),
                    column("last_activity"),
                    column("id"),
                    column("ip_address"),
                ),
            )
        )
        ips_by_device = {
            (
                user_id or False,
                session_identifier,
                platform or False,
                browser or False,
            ): ips
            for user_id, session_identifier, platform, browser, ips in rows
        }
        _debug.perf.count(
            "linked_ip_addresses_computed", devices=len(self), groups=len(rows)
        )
        for device in self:
            device.linked_ip_addresses = "\n".join(
                OrderedSet(ips_by_device.get(device._device_identity()) or ())
            )


class ResDeviceLog(models.Model):
    _name = "res.device.log"
    _inherit = ["res.device.mixin"]
    _description = "Device Log"

    _composite_idx = models.Index(
        "(user_id, session_identifier, platform, browser, last_activity, id) WHERE revoked IS NOT TRUE"
    )
    _active_last_activity_idx = models.Index(
        "(last_activity) WHERE revoked IS NOT TRUE"
    )

    @api.model
    def _update_device(self, request: Any) -> None:
        trace = request.session.update_trace(request)
        if not trace:
            _debug.logic("device_log_skipped", reason="trace_unchanged")
            return

        geoip = GeoIP(trace["ip_address"], app=request.app)
        row = {
            "session_identifier": request.session.sid[:STORED_SESSION_BYTES],
            "platform": trace["platform"],
            "browser": trace["browser"],
            "ip_address": trace["ip_address"],
            "country": geoip.get("country_name"),
            "city": geoip.get("city"),
            "device_type": _device_type(trace["platform"]),
            "user_id": request.session.uid,
            "first_activity": _utc_naive(trace["first_activity"]),
            "last_activity": _utc_naive(trace["last_activity"]),
            "revoked": False,
        }
        insert = SQL(
            "INSERT INTO res_device_log (%s) VALUES %s",
            SQL(", ").join(map(SQL.identifier, row)),
            tuple(row.values()),
        )
        own_cursor = self.env.cr.readonly
        if own_cursor:
            with self.env.registry.cursor(readonly=False) as cr:
                cr.execute(insert)
        else:
            # Contain this optional write without flushing unrelated pending
            # ORM work: a failure must not abort the request's transaction.
            with self.env.cr.savepoint(flush=False):
                self.env.cr.execute(insert)
        _logger.info(
            "User %d device log added for %s %s",
            row["user_id"],
            row["platform"],
            row["browser"],
        )
        _debug.lifecycle(
            "device_log_inserted",
            uid=row["user_id"],
            platform=row["platform"],
            browser=row["browser"],
            device_type=row["device_type"],
            own_cursor=own_cursor,
        )

    @api.model
    def _mark_revoked(self, session_identifiers: Collection[str]) -> int:
        self.flush_model(["session_identifier", "revoked"])
        self.env.cr.execute(
            SQL(
                """
                UPDATE res_device_log
                SET revoked = TRUE, write_uid = %s, write_date = %s
                WHERE session_identifier = ANY(%s) AND revoked IS NOT TRUE
                """,
                self.env.uid,
                self.env.cr.now(),
                list(session_identifiers),
            )
        )
        revoked = self.env.cr.rowcount
        self.invalidate_model(["revoked", "write_uid", "write_date"])
        self.env["res.device"].invalidate_model(["revoked"])
        return revoked

    @api.autovacuum
    def _gc_device_log(self) -> tuple[int, bool]:
        self.env.cr.execute(
            SQL(
                """
                DELETE FROM res_device_log
                WHERE id IN (
                    SELECT id
                    FROM (
                        SELECT id,
                            row_number() OVER (
                                PARTITION BY %s
                                ORDER BY last_activity DESC, id DESC
                            ) AS rn
                        FROM res_device_log
                    ) ranked
                    WHERE ranked.rn > 1
                )
                """,
                SQL(", ").join(map(SQL.identifier, (*_DEVICE_IDENTITY, "ip_address"))),
            )
        )
        deleted = self.env.cr.rowcount
        _logger.info("GC device logs delete %d entries", deleted)
        _debug.lifecycle("gc_device_logs", count=deleted)
        return deleted, False

    @api.autovacuum
    def _update_revoked(self) -> tuple[int, bool]:
        inactive_since = fields.Datetime.now() - timedelta(
            seconds=get_session_max_inactivity(self.env)
        )
        self.env.cr.execute(
            SQL(
                """
                SELECT DISTINCT session_identifier
                FROM res_device_log
                WHERE revoked IS NOT TRUE
                    AND last_activity < %s
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
            _debug.lifecycle("device_logs_revoked", count=count, by="gc")
            if not self.env["ir.cron"]._commit_progress(count):
                _debug.logic("revoke_sweep_stopped", reason="time_budget")
                return revoked, True
        _debug.lifecycle("revoke_sweep_done", revoked=revoked)
        return revoked, False


class ResDevice(models.Model):
    _name = "res.device"
    _inherit = ["res.device.mixin"]
    _description = "Devices"
    _auto = False
    _order = "last_activity desc"

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
        root.session_store.remove_sessions_for_identifiers(session_identifiers)
        revoked = self.env["res.device.log"]._mark_revoked(session_identifiers)
        _logger.info(
            "User %d revokes %d session(s) of user(s) %s",
            self.env.uid,
            len(session_identifiers),
            self.mapped("user_id").ids,
        )

        must_logout = any(self.mapped("is_current"))
        _debug.lifecycle(
            "devices_revoked",
            uid=self.env.uid,
            sessions=len(session_identifiers),
            logs=revoked,
            logout=must_logout,
        )
        if must_logout:
            request.session.logout()
        return must_logout

    def _view_query(self) -> SQL:
        def same_device(alias: str) -> SQL:
            return SQL(" AND ").join(
                SQL(
                    "%s = %s"
                    if self._fields[name].required
                    else "%s IS NOT DISTINCT FROM %s",
                    SQL.identifier(alias, name),
                    SQL.identifier("device", name),
                )
                for name in _DEVICE_IDENTITY
            )

        columns = SQL(", ").join(
            SQL(
                "(SELECT min(earliest.first_activity) FROM res_device_log earliest"
                " WHERE %s AND earliest.revoked IS NOT TRUE) AS first_activity",
                same_device("earliest"),
            )
            if name == "first_activity"
            else SQL.identifier("device", name)
            for name, field in self._fields.items()
            if field.store and field.column_type
        )
        return SQL(
            """
            SELECT %s
            FROM res_device_log device
            WHERE device.revoked IS NOT TRUE
              AND NOT EXISTS (
                SELECT 1
                FROM res_device_log newer
                WHERE %s
                    AND newer.revoked IS NOT TRUE
                    AND (newer.last_activity, newer.id) > (device.last_activity, device.id)
              )
            """,
            columns,
            same_device("newer"),
        )

    def init(self) -> None:
        drop_view_if_exists(self.env.cr, self._table)
        _debug.lifecycle("view_recreated", table=self._table)
        self.env.cr.execute(
            SQL(
                "CREATE VIEW %s AS (%s)",
                SQL.identifier(self._table),
                self._view_query(),
            )
        )
