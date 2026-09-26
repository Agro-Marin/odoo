import argparse
import logging
import sys
from datetime import datetime

import odoo.db
from odoo.libs.debug_log import DebugLog
from odoo.modules import sql_zone_repair as repair

from . import DatabaseCommand

_logger = logging.getLogger(__name__)
_debug = DebugLog(__name__)


def _parse_instant(value: str) -> datetime:
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if instant.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"{value!r} carries no UTC offset; write it as ...Z or ...-06:00"
        )
    return instant


class SqlZoneRepair(DatabaseCommand):
    name = "sql_zone_repair"
    description = """
        Move timestamps that SQL clocks (now(), CURRENT_TIMESTAMP, LOCALTIMESTAMP,
        DEFAULT now()) wrote in the cluster's zone, before sessions were forced to
        UTC, back to UTC. Dry run unless --apply.
    """
    epilog = """
        Only the (table, column) pairs of the reviewed registry in
        odoo/modules/sql_zone_repair.py are considered, and within them only values
        older than --until whose UTC reading equals, to the microsecond, a
        create_date/write_date of an ir_* table: the ORM row written by the same
        transaction. Everything else is reported, never touched.
    """

    def __init__(self) -> None:
        super().__init__()
        self.add_config_arguments(self.parser)
        self.parser.add_argument(
            "--until",
            required=True,
            type=_parse_instant,
            help="the instant the UTC-session build went live, with its offset "
            "(e.g. 2026-09-26T02:31:12Z); only older values are considered",
        )
        self.parser.add_argument(
            "--zone",
            help="the zone sessions ran in before the fix; defaults to the zone a "
            "session opened without the forced UTC reads today",
        )
        self.parser.add_argument(
            "--apply",
            action="store_true",
            help="perform the repair in one transaction and record it; "
            "without it nothing is written",
        )
        self.parser.add_argument(
            "--samples", type=int, default=3, help="sample values shown per column"
        )

    def run(self, args: list[str]) -> None:
        parsed_args, unknown = self.parse_args(args)
        dbname = self.bootstrap_config(parsed_args, extra_args=unknown)
        _debug.lifecycle("cli.sql_zone_repair", db=dbname, apply=parsed_args.apply)

        probe = repair.probe_session_zone(dbname)
        _print_probe(probe)
        zone = parsed_args.zone or probe.zone
        if zone.upper() in {"UTC", "ETC/UTC", "UCT", "ZULU", "GMT"}:
            print(
                f"\nSessions ran in {zone}: no SQL clock wrote a local wall clock. "
                "Nothing to repair; pass --zone if the cluster's zone changed since."
            )
            return
        if parsed_args.zone and parsed_args.zone != probe.zone:
            print(
                f"\n--zone {parsed_args.zone} differs from today's {probe.zone}: the "
                "witness check below confirms or refutes it."
            )

        with odoo.db.db_connect(dbname).cursor() as cr:
            guard = repair.read_guard(cr)
            plan = repair.plan_repair(
                cr, zone, parsed_args.until, samples=parsed_args.samples
            )
            _print_plan(plan, guard)
            if not parsed_args.apply:
                cr.rollback()
                print("\nDry run: nothing written. Review, then re-run with --apply.")
                return
            if guard is not None:
                cr.rollback()
                sys.exit(f"Refused: the repair already ran ({repair.GUARD_KEY}).")
            if not repair.apply_repair(cr, plan):
                cr.rollback()
                for column_plan in plan.columns:
                    if column_plan.error:
                        print(f"FAILED {column_plan.column.name}: {column_plan.error}")
                sys.exit("Rolled back: no value was changed.")
            cr.commit()
        repaired = sum(p.repaired or 0 for p in plan.columns)
        _logger.info(
            "sql_zone_repair: %d value(s) moved to UTC on %s", repaired, dbname
        )
        print(
            f"\nApplied: {repaired} value(s) moved to UTC, recorded as {repair.GUARD_KEY}."
        )
        _debug.lifecycle("cli.sql_zone_repair.done", db=dbname, repaired=repaired)


def _print_probe(probe: repair.ZoneProbe) -> None:
    print("Session zone without the forced UTC:", probe.zone)
    where = f" ({probe.sourcefile}:{probe.sourceline})" if probe.sourcefile else ""
    print(f"  source: {probe.source}{where}")
    for setting in probe.role_settings:
        print(f"  ALTER ROLE/DATABASE: {setting}")
    if probe.options:
        print(f"  startup options replayed: {probe.options}")
    if probe.pgtz:
        print(f"  PGTZ={probe.pgtz} in this process's environment")


def _print_plan(plan: repair.RepairPlan, guard: dict | None) -> None:
    print(
        f"\nZone {plan.zone}; deploy {plan.until.isoformat()} = "
        f"{plan.until_local.isoformat(sep=' ')} local wall clock; "
        f"{plan.witnesses} witness instants from ir_* tables."
    )
    if guard is not None:
        print(f"Already applied: {guard}")
    print(f"\n{'column':<48} {'status':<24} {'window':>8} {'witnessed':>10}")
    for p in plan.columns:
        print(f"{p.column.name:<48} {p.status:<24} {p.in_window:>8} {p.witnessed:>10}")
        for before, after in p.samples:
            print(f"    {before.isoformat(sep=' ')} -> {after.isoformat(sep=' ')}")
        for before in p.unwitnessed_samples:
            print(f"    unwitnessed, left: {before.isoformat(sep=' ')}")
    unregistered = [c for c in plan.default_clocks if not c[3]]
    if unregistered:
        print("\nColumns with a SQL clock DEFAULT that the registry does not list:")
        for table, column, default, _known in unregistered:
            print(f"    {table}.{column} DEFAULT {default}")
    print(f"\nTo repair: {plan.to_repair} value(s).")
