from __future__ import annotations

import json
import logging
import os
import typing
from dataclasses import dataclass, field

from odoo.libs.debug_log import DebugLog
from odoo.libs.sql import SQL
from odoo.tools.constants import CACHES_BY_KEY

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from odoo.db import BaseCursor

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)

GUARD_KEY = "base.sql_zone_repair"
WITNESS_TABLE = "sql_zone_repair_witness"
WITNESS_COLUMNS = ("create_date", "write_date")
NAIVE_TIMESTAMP = "timestamp without time zone"


@dataclass(frozen=True)
class ClockWrite:
    table: str
    columns: tuple[str, ...]
    source: str
    repair: bool = True


def _log_access(table: str, source: str) -> ClockWrite:
    return ClockWrite(table, ("create_date", "write_date"), source)


def _touch(table: str, source: str) -> ClockWrite:
    return ClockWrite(table, ("write_date",), source)


_PHONE_NUMBER_MIGRATIONS = (
    "odoo/odoo/addons/base/migrations/1.36/post-migrate_phone_numbers.py",
    "odoo/addons/crm/migrations/1.10/post-migrate_phone_numbers.py",
    "odoo/addons/event/migrations/1.11/post-migrate_phone_numbers.py",
    "odoo/addons/event_booth/migrations/1.2/post-migrate_phone_numbers.py",
    "odoo/addons/event_booth_sale/migrations/1.3/post-migrate_phone_numbers.py",
    "odoo/addons/hr/migrations/1.13/pre-migrate_work_channels_are_the_partys.py",
    "odoo/addons/hr/migrations/1.17/post-migrate_phone_numbers.py",
    "odoo/addons/hr_recruitment/migrations/1.4/post-migrate_phone_numbers.py",
    "odoo/addons/mass_mailing_sms/migrations/1.2/post-migrate_phone_numbers.py",
    "odoo/addons/point_of_sale/migrations/1.0.4/post-migrate_phone_numbers.py",
    "odoo/addons/project/migrations/1.21/post-migrate_phone_numbers.py",
    "odoo/addons/website_event_exhibitor/migrations/1.2/post-migrate_phone_numbers.py",
    "odoo/addons/website_event_track/migrations/1.4/post-migrate_phone_numbers.py",
    "enterprise/appointment_google_reserve/migrations/1.1/post-migrate_phone_numbers.py",
    "enterprise/frontdesk/migrations/1.1/post-migrate_phone_numbers.py",
    "enterprise/helpdesk/migrations/1.7/post-migrate_phone_numbers.py",
    "agromarin/product_msds/migrations/19.0.1.3.0/post-migrate_phone_numbers.py",
)

_MARIN_1_16_PRE = "agromarin/marin/migrations/19.0.1.16/pre-migrate.py"
_MARIN_1_16_POST = "agromarin/marin/migrations/19.0.1.16/post-migrate.py"

CLOCK_WRITES: tuple[ClockWrite, ...] = (
    *(
        ClockWrite(
            f"orm_signaling_{signal}",
            ("date",),
            "odoo/odoo/orm/runtime/_registry_signaling.py",
            repair=False,
        )
        for signal in ("registry", *CACHES_BY_KEY)
    ),
    *(_log_access("phone_number", source) for source in _PHONE_NUMBER_MIGRATIONS),
    _log_access(
        "res_partner_category",
        "odoo/addons/hr/migrations/1.5.0/pre-migrate_employee_tags.py",
    ),
    _log_access(
        "res_partner_tag",
        "odoo/addons/hr/migrations/1.5.0/pre-migrate_employee_tags.py",
    ),
    _log_access(
        "res_partner", "odoo/addons/hr/migrations/1.4.0/pre-migrate_private_address.py"
    ),
    _log_access(
        "hr_employee_bank_allocation",
        "odoo/addons/hr/migrations/1.26/post-migrate_salary_allocation_fill.py",
    ),
    _log_access(
        "workflow_edge", "odoo/addons/automation/migrations/1.6/post-migrate.py"
    ),
    _log_access(
        "automation_runtime_edge",
        "odoo/addons/automation/migrations/1.6/post-migrate.py",
    ),
    _log_access(
        "survey_survey", "odoo/addons/website_slides/migrations/2.8/pre-migrate.py"
    ),
    _log_access(
        "maintenance_profile", "odoo/addons/maintenance/migrations/1.9/post-migrate.py"
    ),
    _touch(
        "l10n_mx_edi_document",
        "enterprise/l10n_mx_edi/models/l10n_mx_edi_document.py",
    ),
    _log_access(
        "l10n_mx_edi_cfdi_relation",
        "enterprise/l10n_mx_edi/models/l10n_mx_edi_cfdi_relation.py",
    ),
    _log_access(
        "res_partner",
        "agromarin/web_scraper_efectivale/migrations/19.0.2.0.0/pre-migration.py",
    ),
    _log_access(
        "wallet_card",
        "agromarin/web_scraper_efectivale/migrations/19.0.2.0.0/pre-migration.py",
    ),
    _log_access(
        "res_partner",
        "agromarin/web_scraper_highway/migrations/19.0.3.0.0/pre-migration.py",
    ),
    _log_access("stock_location", "agromarin/document_physical/hooks.py"),
    _log_access(
        "device_profile",
        "agromarin/device_access_control/migrations/19.0.3.0.0/pre-migrate.py",
    ),
    _log_access(
        "device_device",
        "agromarin/device_access_control/migrations/19.0.3.0.0/pre-migrate.py",
    ),
    _log_access(
        "ir_config_parameter",
        "agromarin/device_gps/migrations/19.0.1.2.0/post-migrate.py",
    ),
    _log_access(
        "ir_config_parameter", "agromarin/conversation/migrations/2.0.0/pre-migrate.py"
    ),
    _log_access(
        "abc_classification_profile",
        "agromarin/product_abc_classification/migrations/1.3/pre-migrate.py",
    ),
    _log_access(
        "abc_classification_level",
        "agromarin/product_abc_classification/migrations/1.3/pre-migrate.py",
    ),
    _log_access(
        "geoengine_view_settings",
        "agromarin/geoengine/migrations/19.0.1.18.0/post-migrate.py",
    ),
    _log_access(
        "ir_model_data", "agromarin/geoengine/migrations/19.0.1.18.0/post-migrate.py"
    ),
    *(
        _log_access(table, "agromarin/agro_base/migrations/19.0.1.2.0/post-migrate.py")
        for table in (
            "agro_crop_soil_suitability",
            "agro_variety_disease_resistance",
            "agro_variety_pest_resistance",
        )
    ),
    _log_access("agro_organism", "agromarin/agro_base/hooks.py"),
    *(
        _log_access(table, "agromarin/agro_base/migrations/19.0.2.0.0/pre-migrate.py")
        for table in ("agro_organism", "agro_pathogen", "agro_interaction")
    ),
    _touch("account_asset", "agromarin/marin/migrations/19.0.1.22/pre-migrate.py"),
    _log_access(
        "ir_module_category", "agromarin/marin/migrations/19.0.1.6/post-migrate.py"
    ),
    _log_access("res_groups", "agromarin/marin/migrations/19.0.1.6/post-migrate.py"),
    _log_access(
        "res_users_role_line", "agromarin/marin/migrations/19.0.1.6/post-migrate.py"
    ),
    _touch(
        "res_users_role_line", "agromarin/marin/migrations/19.0.1.18/post-migrate.py"
    ),
    _log_access("ir_model_data", "agromarin/marin/migrations/19.0.1.13/pre-migrate.py"),
    _log_access(
        "device_state_boundary", "agromarin/marin/migrations/19.0.1.9/post-migrate.py"
    ),
    _log_access(
        "res_partner_profile", "agromarin/marin/migrations/19.0.1.12/post-migrate.py"
    ),
    _log_access(
        "res_partner_hectares_range",
        "agromarin/marin/migrations/19.0.1.12/post-migrate.py",
    ),
    ClockWrite(
        "stock_quant",
        ("in_date", "create_date", "write_date"),
        "agromarin/marin/migrations/19.0.1.11/post-migrate.py",
    ),
    _touch("stock_quant", _MARIN_1_16_PRE),
    _touch("stock_move", _MARIN_1_16_PRE),
    *(
        _touch(table, _MARIN_1_16_POST)
        for table in (
            "stock_warehouse",
            "stock_route",
            "stock_picking_type",
            "stock_location",
        )
    ),
)


@dataclass(frozen=True)
class RegisteredColumn:
    table: str
    column: str
    sources: tuple[str, ...]
    repair: bool

    @property
    def name(self) -> str:
        return f"{self.table}.{self.column}"


def registered_columns(
    writes: Iterable[ClockWrite] = CLOCK_WRITES,
) -> list[RegisteredColumn]:
    sources: dict[tuple[str, str], list[str]] = {}
    repair: dict[tuple[str, str], bool] = {}
    for write in writes:
        for column in write.columns:
            key = (write.table, column)
            if write.source not in sources.setdefault(key, []):
                sources[key].append(write.source)
            repair[key] = repair.get(key, True) and write.repair
    return [
        RegisteredColumn(
            table, column, tuple(sources[table, column]), repair[table, column]
        )
        for table, column in sorted(sources)
    ]


@dataclass(frozen=True)
class ZoneProbe:
    zone: str
    source: str
    sourcefile: str | None
    sourceline: int | None
    role_settings: tuple[str, ...]
    options: str
    pgtz: str | None


def probe_session_zone(dbname: str) -> ZoneProbe:
    import psycopg

    from odoo.db import pool, pool_settings
    from odoo.db.utils import get_connection_info_for_database

    settings = pool_settings.current()
    _db, info = get_connection_info_for_database(dbname, settings=settings)
    kwargs = dict(info)
    conninfo = kwargs.pop("dsn", "")
    forced = f"-c {pool._SESSION_ZONE_GUC}"
    options = pool._prepare_connection_options(
        conninfo, kwargs, 0, session_gucs=settings.session_gucs
    )
    if not options.endswith(forced):
        raise RuntimeError(
            f"the pool no longer ends its startup options with {forced!r}; "
            "the pre-fix session cannot be replayed"
        )
    kwargs["options"] = options.removesuffix(forced).rstrip()
    with psycopg.connect(conninfo, autocommit=True, **kwargs) as conn:
        zone_row = conn.execute("SHOW TimeZone").fetchone()
        setting_row = conn.execute(
            "SELECT source, sourcefile, sourceline FROM pg_settings"
            " WHERE name = 'TimeZone'"
        ).fetchone()
        role_rows = conn.execute("""
            SELECT coalesce(r.rolname, '*') || '@' || coalesce(d.datname, '*')
                   || ': ' || cfg
              FROM pg_db_role_setting s
         LEFT JOIN pg_roles r ON r.oid = s.setrole
         LEFT JOIN pg_database d ON d.oid = s.setdatabase
             CROSS JOIN unnest(s.setconfig) cfg
             WHERE cfg ILIKE 'timezone=%'
               AND (s.setdatabase = 0 OR d.datname = current_database())
               AND (s.setrole = 0 OR r.rolname = current_user)
          ORDER BY 1
        """).fetchall()
    assert zone_row is not None and setting_row is not None
    probe = ZoneProbe(
        zone=zone_row[0],
        source=setting_row[0],
        sourcefile=setting_row[1],
        sourceline=setting_row[2],
        role_settings=tuple(row[0] for row in role_rows),
        options=kwargs["options"],
        pgtz=os.environ.get("PGTZ"),
    )
    _debug.logic(
        "modules.sql_zone_repair.probe", db=dbname, zone=probe.zone, source=probe.source
    )
    return probe


@dataclass
class ColumnPlan:
    column: RegisteredColumn
    status: str
    in_window: int = 0
    witnessed: int = 0
    samples: list[tuple[datetime, datetime]] = field(default_factory=list)
    unwitnessed_samples: list[datetime] = field(default_factory=list)
    repaired: int | None = None
    error: str | None = None

    @property
    def unwitnessed(self) -> int:
        return self.in_window - self.witnessed


@dataclass
class RepairPlan:
    zone: str
    until: datetime
    until_local: datetime
    witnesses: int
    columns: list[ColumnPlan]
    default_clocks: list[tuple[str, str, str, bool]]

    @property
    def to_repair(self) -> int:
        return sum(plan.witnessed for plan in self.columns if plan.column.repair)


def repaired_expr(column: SQL, zone: str) -> SQL:
    return SQL("((%s AT TIME ZONE %s) AT TIME ZONE 'UTC')", column, zone)


def witness_insert_sql(table: str, column: str) -> SQL:
    col = SQL.identifier(column)
    return SQL(
        "INSERT INTO pg_temp.%s (ts) SELECT DISTINCT %s FROM %s WHERE %s IS NOT NULL"
        " ON CONFLICT DO NOTHING",
        SQL.identifier(WITNESS_TABLE),
        col,
        SQL.identifier(table),
        col,
    )


def _witnessed(column: str, zone: str) -> SQL:
    return SQL(
        "%s IN (SELECT ts FROM pg_temp.%s)",
        repaired_expr(SQL.identifier(column), zone),
        SQL.identifier(WITNESS_TABLE),
    )


def count_sql(table: str, column: str, zone: str, until_local: datetime) -> SQL:
    col = SQL.identifier(column)
    return SQL(
        "SELECT count(*), count(*) FILTER (WHERE %s) FROM %s WHERE %s < %s",
        _witnessed(column, zone),
        SQL.identifier(table),
        col,
        until_local,
    )


def sample_sql(
    table: str,
    column: str,
    zone: str,
    until_local: datetime,
    *,
    witnessed: bool,
    limit: int,
) -> SQL:
    col = SQL.identifier(column)
    clause = _witnessed(column, zone)
    return SQL(
        "SELECT %s, %s FROM %s WHERE %s < %s AND %s ORDER BY %s DESC LIMIT %s",
        col,
        repaired_expr(col, zone),
        SQL.identifier(table),
        col,
        until_local,
        clause if witnessed else SQL("NOT (%s)", clause),
        col,
        limit,
    )


def update_sql(table: str, column: str, zone: str, until_local: datetime) -> SQL:
    col = SQL.identifier(column)
    return SQL(
        "UPDATE %s SET %s = %s WHERE %s < %s AND %s",
        SQL.identifier(table),
        col,
        repaired_expr(col, zone),
        col,
        until_local,
        _witnessed(column, zone),
    )


def _one(cr: BaseCursor) -> tuple:
    row = cr.fetchone()
    assert row is not None, "an aggregate returned no row"
    return row


def check_zone(cr: BaseCursor, zone: str) -> None:
    cr.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = %s)", [zone]
    )
    if not _one(cr)[0]:
        raise ValueError(f"PostgreSQL does not know the time zone {zone!r}")


def local_wall_clock(cr: BaseCursor, until: datetime, zone: str) -> datetime:
    if until.tzinfo is None:
        raise ValueError("the deploy instant needs an explicit UTC offset")
    cr.execute("SELECT %s::timestamptz AT TIME ZONE %s", [until, zone])
    return _one(cr)[0]


def build_witnesses(cr: BaseCursor) -> int:
    cr.execute(
        SQL(
            "CREATE TEMP TABLE %s (ts timestamp PRIMARY KEY) ON COMMIT DROP",
            SQL.identifier(WITNESS_TABLE),
        )
    )
    cr.execute(
        r"""
        SELECT c.table_name, c.column_name
          FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema AND t.table_name = c.table_name
         WHERE c.table_schema = current_schema()
           AND t.table_type = 'BASE TABLE'
           AND c.table_name LIKE 'ir\_%%'
           AND c.column_name = ANY(%s)
           AND c.data_type = %s
      ORDER BY 1, 2
        """,
        [list(WITNESS_COLUMNS), NAIVE_TIMESTAMP],
    )
    for table, column in cr.fetchall():
        cr.execute(witness_insert_sql(table, column))
    cr.execute(SQL("ANALYZE pg_temp.%s", SQL.identifier(WITNESS_TABLE)))
    cr.execute(SQL("SELECT count(*) FROM pg_temp.%s", SQL.identifier(WITNESS_TABLE)))
    count = _one(cr)[0]
    _debug.perf.count("modules.sql_zone_repair.witnesses", witnesses=count)
    return count


def _naive_columns(cr: BaseCursor, tables: list[str]) -> dict[tuple[str, str], str]:
    cr.execute(
        """
        SELECT c.table_name, c.column_name, c.data_type
          FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema AND t.table_name = c.table_name
         WHERE c.table_schema = current_schema()
           AND t.table_type = 'BASE TABLE'
           AND c.table_name = ANY(%s)
        """,
        [tables],
    )
    return {(table, column): data_type for table, column, data_type in cr.fetchall()}


def default_clocks(
    cr: BaseCursor, registered: Iterable[RegisteredColumn]
) -> list[tuple[str, str, str, bool]]:
    known = {(col.table, col.column) for col in registered}
    cr.execute(
        """
        SELECT table_name, column_name, column_default
          FROM information_schema.columns
         WHERE table_schema = current_schema()
           AND data_type = %s
           AND column_default ~* %s
           AND column_default !~* %s
      ORDER BY 1, 2
        """,
        [
            NAIVE_TIMESTAMP,
            r"now\(\)|current_timestamp|localtimestamp|'now'",
            r"timezone\(|at time zone",
        ],
    )
    return [
        (table, column, default, (table, column) in known)
        for table, column, default in cr.fetchall()
    ]


def plan_repair(
    cr: BaseCursor,
    zone: str,
    until: datetime,
    *,
    samples: int = 3,
    registered: list[RegisteredColumn] | None = None,
) -> RepairPlan:
    registered = registered_columns() if registered is None else registered
    check_zone(cr, zone)
    until_local = local_wall_clock(cr, until, zone)
    witnesses = build_witnesses(cr)
    types = _naive_columns(cr, sorted({col.table for col in registered}))
    plans = []
    for col in registered:
        data_type = types.get((col.table, col.column))
        if data_type is None:
            plans.append(ColumnPlan(col, "absent"))
            continue
        if data_type != NAIVE_TIMESTAMP:
            plans.append(ColumnPlan(col, f"unaffected ({data_type})"))
            continue
        plan = ColumnPlan(col, "repair" if col.repair else "report")
        cr.execute(count_sql(col.table, col.column, zone, until_local))
        plan.in_window, plan.witnessed = _one(cr)
        if samples and plan.witnessed:
            cr.execute(
                sample_sql(
                    col.table,
                    col.column,
                    zone,
                    until_local,
                    witnessed=True,
                    limit=samples,
                )
            )
            plan.samples = [(before, after) for before, after in cr.fetchall()]
        if samples and col.repair and plan.unwitnessed:
            cr.execute(
                sample_sql(
                    col.table,
                    col.column,
                    zone,
                    until_local,
                    witnessed=False,
                    limit=samples,
                )
            )
            plan.unwitnessed_samples = [before for before, _after in cr.fetchall()]
        _debug.logic(
            "modules.sql_zone_repair.planned",
            column=col.name,
            in_window=plan.in_window,
            witnessed=plan.witnessed,
            repair=col.repair,
        )
        plans.append(plan)
    return RepairPlan(
        zone=zone,
        until=until,
        until_local=until_local,
        witnesses=witnesses,
        columns=plans,
        default_clocks=default_clocks(cr, registered),
    )


def read_guard(cr: BaseCursor) -> dict | None:
    cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", [GUARD_KEY])
    row = cr.fetchone()
    return json.loads(row[0]) if row else None


def apply_repair(cr: BaseCursor, plan: RepairPlan) -> bool:
    if (guard := read_guard(cr)) is not None:
        raise RuntimeError(
            f"the repair already ran on this database ({GUARD_KEY} = {guard}); "
            "a second run is refused"
        )
    for column_plan in plan.columns:
        col = column_plan.column
        if column_plan.status != "repair" or not column_plan.witnessed:
            continue
        try:
            with cr.savepoint(flush=False):
                cr.execute(
                    update_sql(col.table, col.column, plan.zone, plan.until_local)
                )
                column_plan.repaired = cr.rowcount
        # Every failing column is reported in one run; the caller then rolls
        # the whole transaction back.
        except Exception as exc:
            column_plan.error = f"{type(exc).__name__}: {exc}"
            _debug.logic(
                "modules.sql_zone_repair.column_failed",
                column=col.name,
                error=type(exc).__name__,
            )
            continue
        _logger.info("%s: %d value(s) moved to UTC", col.name, column_plan.repaired)
    if any(column_plan.error for column_plan in plan.columns):
        return False
    record = {
        "zone": plan.zone,
        "until": plan.until.isoformat(),
        "repaired": {
            p.column.name: p.repaired for p in plan.columns if p.repaired is not None
        },
    }
    cr.execute(
        "INSERT INTO ir_config_parameter"
        " (key, value, create_uid, write_uid, create_date, write_date)"
        " VALUES (%s, %s, 1, 1, now() AT TIME ZONE 'UTC', now() AT TIME ZONE 'UTC')",
        [GUARD_KEY, json.dumps(record, sort_keys=True)],
    )
    return True
