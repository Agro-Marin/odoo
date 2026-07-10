import logging
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

from odoo import api, fields, models, tools
from odoo.exceptions import AccessError
from odoo.http import (
    STORED_SESSION_BYTES,
    GeoIP,
    get_session_max_inactivity,
    request,
    root,
)
from odoo.tools import SQL, OrderedSet, unique
from odoo.tools.translate import _

from .res_users import check_identity

_logger = logging.getLogger(__name__)

_MOBILE_PLATFORMS = frozenset(
    {
        "android",
        "iphone",
        "ipad",
        "ipod",
        "blackberry",
        "windows phone",
        "webos",
    }
)

# Single source of truth for the columns identifying one "device" (RDEV-P4): the
# ``res.device`` view de-dup (ResDevice._where) and the GC (_gc_device_log) both
# derive their grouping from this constant so the two queries can't drift apart
# again. The boolean marks a nullable column, compared NULL-safely (IS NOT
# DISTINCT FROM) in joins; PARTITION BY groups NULLs natively. Column order
# matches the leading columns of ``ResDeviceLog._composite_idx``.
_DEVICE_IDENTITY_COLUMNS = (
    # (column, nullable)
    ("user_id", True),
    ("session_identifier", False),
    ("platform", True),
    ("browser", True),
)


class ResDeviceLog(models.Model):
    _name = "res.device.log"
    _description = "Device Log"
    _rec_names_search = ["platform", "browser"]

    session_identifier = fields.Char("Session Identifier", required=True, index="btree")
    platform = fields.Char("Platform")
    browser = fields.Char("Browser")
    ip_address = fields.Char("IP Address")
    country = fields.Char("Country")
    city = fields.Char("City")
    device_type = fields.Selection(
        [("computer", "Computer"), ("mobile", "Mobile")], "Device Type"
    )
    user_id = fields.Many2one("res.users", index="btree")
    first_activity = fields.Datetime("First Activity")
    last_activity = fields.Datetime("Last Activity", index="btree")
    revoked = fields.Boolean(
        "Revoked",
        help="If True, the session file corresponding to this device"
        " no longer exists on the filesystem.",
    )
    is_current = fields.Boolean("Current Device", compute="_compute_is_current")
    linked_ip_addresses = fields.Text(
        "Linked IP address", compute="_compute_linked_ip_addresses"
    )

    _composite_idx = models.Index(
        "(user_id, session_identifier, platform, browser, last_activity, id) WHERE revoked IS NOT TRUE"
    )
    _revoked_idx = models.Index("(revoked) WHERE revoked IS NOT TRUE")

    @api.depends("platform", "browser")
    def _compute_display_name(self) -> None:
        for device in self:
            platform = device.platform or _("Unknown")
            browser = device.browser or _("Unknown")
            device.display_name = f"{platform.capitalize()} {browser.capitalize()}"

    def _compute_is_current(self) -> None:
        """Flag the device backing the current HTTP session."""
        for device in self:
            device.is_current = request and request.session.sid.startswith(
                device.session_identifier
            )

    def _compute_linked_ip_addresses(self) -> None:
        device_group_map = {}
        for *device_info, ip_array in self.env["res.device.log"]._read_group(
            domain=[("session_identifier", "in", self.mapped("session_identifier"))],
            groupby=["session_identifier", "platform", "browser"],
            aggregates=["ip_address:array_agg"],
        ):
            device_group_map[tuple(device_info)] = ip_array
        for device in self:
            device.linked_ip_addresses = "\n".join(
                OrderedSet(
                    ip
                    for ip in device_group_map.get(
                        (
                            device.session_identifier,
                            device.platform,
                            device.browser,
                        ),
                        [],
                    )
                    if ip
                )
            )

    def _order_field_to_sql(
        self,
        alias: str,
        field_name: str,
        direction: Any,
        nulls: Any,
        query: Any,
    ) -> SQL:
        if field_name == "is_current" and request and request.session.sid:
            return SQL(
                "%s = %s %s",
                SQL.identifier(alias, "session_identifier"),
                request.session.sid[:STORED_SESSION_BYTES],
                direction,
            )
        return super()._order_field_to_sql(alias, field_name, direction, nulls, query)

    def _is_mobile(self, platform: str | None) -> bool:
        """Return whether ``platform`` denotes a known mobile platform."""
        if not platform:
            return False
        return platform.lower() in _MOBILE_PLATFORMS

    @api.model
    def _update_device(self, request: Any) -> None:
        """Update the device for the current request, leaving a trace in the session.

        :param request: Request or WebsocketRequest object
        """
        trace = request.session.update_trace(request)
        if not trace:
            return

        geoip = GeoIP(trace["ip_address"])
        user_id = request.session.uid
        session_identifier = request.session.sid[:STORED_SESSION_BYTES]

        if self.env.cr.readonly:
            # RDEV-P1: rolling back to obtain a RW cursor is safe only because
            # device logging runs before any request-scoped writes (ir.http
            # dispatch ordering); uncommitted work on the readonly cursor would
            # otherwise be lost.
            self.env.cr.rollback()
            cursor = self.env.registry.cursor(readonly=False)
        else:
            cursor = nullcontext(self.env.cr)
        with cursor as cr:
            cr.execute(
                SQL(
                    """
                INSERT INTO res_device_log (session_identifier, platform, browser, ip_address, country, city, device_type, user_id, first_activity, last_activity, revoked)
                VALUES (%(session_identifier)s, %(platform)s, %(browser)s, %(ip_address)s, %(country)s, %(city)s, %(device_type)s, %(user_id)s, %(first_activity)s, %(last_activity)s, %(revoked)s)
            """,
                    session_identifier=session_identifier,
                    platform=trace["platform"],
                    browser=trace["browser"],
                    ip_address=trace["ip_address"],
                    country=geoip.get("country_name"),
                    city=geoip.get("city"),
                    device_type=(
                        "mobile" if self._is_mobile(trace["platform"]) else "computer"
                    ),
                    user_id=user_id,
                    first_activity=datetime.fromtimestamp(
                        trace["first_activity"], tz=UTC
                    ).replace(tzinfo=None),
                    last_activity=datetime.fromtimestamp(
                        trace["last_activity"], tz=UTC
                    ).replace(tzinfo=None),
                    revoked=False,
                )
            )
        _logger.info("User %d inserts device log (%s)", user_id, session_identifier)

    @api.autovacuum
    def _gc_device_log(self) -> None:
        # Keep the last device log
        # (even if the session file no longer exists on the filesystem)
        #
        # RDEV-P3: the old correlated EXISTS self-join had no supporting index
        # (both composite indexes are partial on `revoked`, which GC doesn't
        # filter on) and degraded quadratically; a single window-function pass
        # sorts once. Deliberate change: on last_activity ties the old query kept
        # every tied row, this keeps exactly one — greatest (last_activity, id) —
        # aligning GC with the res.device view tie-break (ResDevice._where).
        #
        # RDEV-P4: partition on _DEVICE_IDENTITY_COLUMNS plus ip_address — GC
        # keeps one row per IP of a device so _compute_linked_ip_addresses
        # retains the IP history the view itself hides.
        partition_columns = SQL(", ").join(
            SQL.identifier(column) for column, _nullable in _DEVICE_IDENTITY_COLUMNS
        )
        self.env.cr.execute(
            SQL(
                """
            DELETE FROM res_device_log
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           row_number() OVER (
                               PARTITION BY %(partition_columns)s, ip_address
                               ORDER BY last_activity DESC, id DESC
                           ) AS rn
                    FROM res_device_log
                ) ranked
                WHERE ranked.rn > 1
            )
        """,
                partition_columns=partition_columns,
            )
        )
        _logger.info("GC device logs delete %d entries", self.env.cr.rowcount)

    @api.autovacuum
    def _update_revoked(self) -> None:
        """Flag ``revoked`` on device logs whose session file is gone from disk."""
        # RDEV-P2 (documented, no change): the ("revoked", "=", False) filter
        # shrinks the window as rows are flagged, and `offset -= len(to_revoke)`
        # only corrects for the current batch. On very large datasets some
        # candidates can be skipped in one run but are caught on the next; the
        # session file is already gone, so only the audit flag lags (no security
        # impact). A keyset scan would remove the write/cursor coupling but is a
        # behavioural change, left out of this minimal pass.
        batch_size = 100_000
        offset = 0

        while True:
            candidate_device_log_ids = self.env["res.device.log"].search_fetch(
                [
                    ("revoked", "=", False),
                    (
                        "last_activity",
                        "<",
                        # RDEV-T1: fields.Datetime.now() is the test-patchable
                        # clock (same naive-UTC value as datetime.now(UTC)).
                        fields.Datetime.now()
                        - timedelta(seconds=get_session_max_inactivity(self.env)),
                    ),
                ],
                ["session_identifier"],
                order="id",
                limit=batch_size,
                offset=offset,
            )
            if not candidate_device_log_ids:
                break
            offset += batch_size
            revoked_session_identifiers = (
                root.session_store.get_missing_session_identifiers(
                    set(candidate_device_log_ids.mapped("session_identifier"))
                )
            )
            if revoked_session_identifiers:
                to_revoke = candidate_device_log_ids.filtered(
                    lambda candidate, revoked=revoked_session_identifiers: (
                        candidate.session_identifier in revoked
                    )
                )
                to_revoke.write({"revoked": True})
                self.env.cr.commit()
                offset -= len(to_revoke)


class ResDevice(models.Model):
    _name = "res.device"
    _inherit = ["res.device.log"]
    _description = "Devices"
    _auto = False
    _order = "last_activity desc"

    @check_identity
    def revoke(self) -> None:
        return self._revoke()

    def _revoke(self) -> None:
        """Revoke the sessions of the devices in ``self`` (privileged action).

        Deletes the matching session files, flags the device logs ``revoked``,
        and logs out the current session if it is among them.

        :raises AccessError: when a non-system caller passes a device that does
            not belong to ``self.env.user``.
        """
        if not self:
            return
        # RDEV-L1: self-scope the privileged revoke so the invariant lives in the
        # method that escalates to sudo(), not only in the record rule (mirrors
        # res.users.apikeys._remove). Non-system callers may revoke only their own
        # devices; group_system retains full revoke.
        if not self.env.is_system() and self.mapped("user_id") != self.env.user:
            raise AccessError(_("You can only revoke your own devices."))
        ResDeviceLog = self.env["res.device.log"]
        session_identifiers = list(unique(device.session_identifier for device in self))
        root.session_store.delete_from_identifiers(session_identifiers)
        revoked_devices = ResDeviceLog.sudo().search(
            [("session_identifier", "in", session_identifiers)]
        )
        revoked_devices.write({"revoked": True})
        _logger.info(
            "User %d revokes devices (%s)",
            self.env.uid,
            ", ".join(session_identifiers),
        )

        must_logout = bool(self.filtered("is_current"))
        if must_logout:
            request.session.logout()

    @api.model
    def _select(self) -> str:
        """Return the SELECT clause of the ``res.device`` view query."""
        return "SELECT D.*"

    @api.model
    def _from(self) -> str:
        """Return the FROM clause of the ``res.device`` view query."""
        return "FROM res_device_log D"

    @api.model
    def _where(self) -> str:
        """Return the WHERE clause keeping the latest non-revoked log per device.

        The identity join derives from ``_DEVICE_IDENTITY_COLUMNS`` (RDEV-P4), the
        same constant ``_gc_device_log`` partitions on, so view and GC can't
        de-dup on diverging columns. All interpolated fragments are module-level
        literals, not user input (SQL wrapper rule, coding_guidelines §10.4).
        """
        identity_join = "\n                        AND ".join(
            f"D2.{column} IS NOT DISTINCT FROM D.{column}"
            if nullable
            else f"D2.{column} = D.{column}"
            for column, nullable in _DEVICE_IDENTITY_COLUMNS
        )
        return f"""
            WHERE
                NOT EXISTS (
                    SELECT 1
                    FROM res_device_log D2
                    WHERE
                        {identity_join}
                        AND (
                            D2.last_activity > D.last_activity
                            OR (D2.last_activity = D.last_activity AND D2.id > D.id)
                        )
                        AND D2.revoked IS NOT TRUE
                )
                AND D.revoked IS NOT TRUE
        """

    @property
    def _query(self):
        return f"{self._select()} {self._from()} {self._where()}"

    def init(self) -> None:
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            SQL(
                """
            CREATE or REPLACE VIEW %s as (%s)
        """,
                SQL.identifier(self._table),
                SQL(self._query),
            )
        )
