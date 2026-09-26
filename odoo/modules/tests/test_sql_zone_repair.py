import re
import unittest
from datetime import datetime
from pathlib import Path

from odoo.modules import sql_zone_repair as repair

CHECKOUT = Path(__file__).resolve().parents[3]
CLOCK_RE = re.compile(r"(?i)\b(?:now\(\)|current_timestamp|localtimestamp)")
STORED_CLOCK_RE = re.compile(
    r"(?i)(?:^|[,(=]|\bdefault|\bset)\s*(?:now\(\)|current_timestamp|localtimestamp)"
    r"\s*(?:,|\)|$|--|where\b)"
)
UTC_CLOCK_RE = re.compile(r"(?i)at time zone|timezone\(")
NOT_STORED = {
    "odoo/addons/product_margin/models/product_product.py": "reads now() as a date bound",
    "odoo/addons/l10n_pl_edi/data/neutralize.sql": "runs on neutralized copies only",
    "agromarin/asset_ledger_hr/migrations/19.0.1.1.0/pre-migration.py": (
        "now() is a comparison fallback, never stored"
    ),
    "odoo/odoo/cli/sql_zone_repair.py": "names the clocks in its help",
}
REPOS = ("odoo", "enterprise", "agromarin")


def _resolve(source: str) -> Path:
    repo, rest = source.split("/", 1)
    return (CHECKOUT if repo == "odoo" else CHECKOUT.parent / repo) / rest


def _stored_clock_files(repo: str) -> set[str]:
    root = CHECKOUT if repo == "odoo" else CHECKOUT.parent / repo
    found = set()
    for path in root.rglob("*"):
        if path.suffix not in {".py", ".sql"} or "node_modules" in path.parts:
            continue
        relative = path.relative_to(root)
        if "tests" in relative.parts or path.name.startswith("test_"):
            continue
        text = path.read_text(errors="replace")
        if not CLOCK_RE.search(text):
            continue
        if any(
            STORED_CLOCK_RE.search(line) and not UTC_CLOCK_RE.search(line)
            for line in text.splitlines()
        ):
            found.add(f"{repo}/{relative.as_posix()}")
    return found


class TestTheRegistry(unittest.TestCase):
    def test_every_name_is_an_identifier(self):
        for write in repair.CLOCK_WRITES:
            with self.subTest(source=write.source, table=write.table):
                self.assertTrue(write.table.isidentifier())
                self.assertTrue(write.columns)
                self.assertTrue(all(column.isidentifier() for column in write.columns))

    def test_no_write_is_registered_twice(self):
        keys = [(w.table, w.columns, w.source) for w in repair.CLOCK_WRITES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_columns_group_their_sources_and_report_only_wins(self):
        columns = repair.registered_columns(
            [
                repair.ClockWrite("t", ("create_date", "write_date"), "a.py"),
                repair.ClockWrite("t", ("write_date",), "b.py", repair=False),
                repair.ClockWrite("t", ("write_date",), "a.py"),
            ]
        )
        self.assertEqual(
            [(c.name, c.sources, c.repair) for c in columns],
            [
                ("t.create_date", ("a.py",), True),
                ("t.write_date", ("a.py", "b.py"), False),
            ],
        )

    def test_the_signaling_clock_is_reported_not_repaired(self):
        by_name = {c.name: c for c in repair.registered_columns()}
        self.assertFalse(by_name["orm_signaling_registry.date"].repair)
        self.assertTrue(by_name["phone_number.create_date"].repair)
        self.assertEqual(len(by_name["phone_number.create_date"].sources), 17)

    def test_every_present_source_writes_a_clock_into_its_table(self):
        for write in repair.CLOCK_WRITES:
            path = _resolve(write.source)
            if not write.source.startswith("odoo/") and not path.parent.exists():
                continue
            with self.subTest(source=write.source):
                text = path.read_text()
                self.assertTrue(CLOCK_RE.search(text), "no SQL clock left")
                self.assertTrue(
                    not write.repair or write.table in text or "{self._table}" in text,
                    f"{write.table} is not named",
                )

    def test_every_stored_sql_clock_is_registered(self):
        registered = {w.source for w in repair.CLOCK_WRITES}
        for repo in REPOS:
            if repo != "odoo" and not (CHECKOUT.parent / repo).is_dir():
                continue
            with self.subTest(repo=repo):
                unregistered = _stored_clock_files(repo) - registered - set(NOT_STORED)
                self.assertEqual(
                    unregistered,
                    set(),
                    "a SQL clock stores the session's wall clock here: register "
                    "its (table, columns) in CLOCK_WRITES, or NOT_STORED with why",
                )

    def test_the_allowlist_is_not_stale(self):
        for source in NOT_STORED:
            path = _resolve(source)
            if not source.startswith("odoo/") and not path.parent.exists():
                continue
            with self.subTest(source=source):
                self.assertTrue(CLOCK_RE.search(path.read_text()), "no SQL clock left")


class TestTheStatements(unittest.TestCase):
    until = datetime(2026, 9, 25, 20, 31, 12)

    def test_the_update_moves_only_witnessed_values_older_than_the_deploy(self):
        sql = repair.update_sql(
            "phone_number", "create_date", "America/Mexico_City", self.until
        )
        code, params = sql.code, sql.params
        self.assertEqual(
            code,
            'UPDATE "phone_number" SET "create_date" = '
            "((\"create_date\" AT TIME ZONE %s) AT TIME ZONE 'UTC')"
            ' WHERE "create_date" < %s AND '
            "((\"create_date\" AT TIME ZONE %s) AT TIME ZONE 'UTC')"
            ' IN (SELECT ts FROM pg_temp."sql_zone_repair_witness")',
        )
        self.assertEqual(
            params, ("America/Mexico_City", self.until, "America/Mexico_City")
        )

    def test_the_count_splits_the_window_by_witness(self):
        sql = repair.count_sql("t", "c", "Z", self.until)
        code, params = sql.code, sql.params
        self.assertEqual(
            code,
            "SELECT count(*), count(*) FILTER (WHERE "
            "((\"c\" AT TIME ZONE %s) AT TIME ZONE 'UTC')"
            ' IN (SELECT ts FROM pg_temp."sql_zone_repair_witness"))'
            ' FROM "t" WHERE "c" < %s',
        )
        self.assertEqual(params, ("Z", self.until))

    def test_the_unwitnessed_sample_negates_the_witness(self):
        sql = repair.sample_sql("t", "c", "Z", self.until, witnessed=False, limit=3)
        code, params = sql.code, sql.params
        self.assertEqual(
            code,
            'SELECT "c", (("c" AT TIME ZONE %s) AT TIME ZONE \'UTC\') FROM "t"'
            ' WHERE "c" < %s AND NOT ((("c" AT TIME ZONE %s) AT TIME ZONE \'UTC\')'
            ' IN (SELECT ts FROM pg_temp."sql_zone_repair_witness"))'
            ' ORDER BY "c" DESC LIMIT %s',
        )
        self.assertEqual(params, ("Z", self.until, "Z", 3))

    def test_a_witness_source_is_read_distinct(self):
        sql = repair.witness_insert_sql("ir_model_data", "write_date")
        code, params = sql.code, sql.params
        self.assertEqual(
            code,
            'INSERT INTO pg_temp."sql_zone_repair_witness" (ts) SELECT DISTINCT'
            ' "write_date" FROM "ir_model_data" WHERE "write_date" IS NOT NULL'
            " ON CONFLICT DO NOTHING",
        )
        self.assertEqual(params, ())

    def test_a_hostile_name_is_refused(self):
        with self.assertRaises(ValueError):
            repair.update_sql('t"; DROP TABLE x; --', "c", "Z", self.until)
