from odoo.db import schema as sql
from odoo.tests.common import TransactionCase, tagged

_IR_LOGGING_LOGGER = "odoo.addons.base.models.ir_logging"


@tagged("post_install", "-at_install")
class TestIrLoggingInit(TransactionCase):
    CONSTRAINT = "ir_logging_write_uid_fkey"

    def test_write_uid_fkey_absent_after_install(self):
        self.assertIsNone(
            sql.constraint_definition(self.env.cr, "ir_logging", self.CONSTRAINT),
            "ir.logging.init must drop the legacy write_uid foreign key",
        )

    def test_init_is_idempotent(self):
        model = self.env["ir.logging"]
        model.init()
        self.assertIsNone(
            sql.constraint_definition(self.env.cr, "ir_logging", self.CONSTRAINT),
            "a second init() must not recreate the FK",
        )
        model.init()
        self.assertIsNone(
            sql.constraint_definition(self.env.cr, "ir_logging", self.CONSTRAINT)
        )


@tagged("post_install", "-at_install")
class TestIrLoggingRawInsert(TransactionCase):
    INJECTION = "'); DROP TABLE ir_logging; --"

    def test_raw_insert_is_parameterised(self):
        before = self.env["ir.logging"].search_count([])
        self.env.cr.execute(
            """
            INSERT INTO ir_logging(create_date, type, dbname, name, level, message, path, line, func)
            VALUES (NOW() at time zone 'UTC', %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                "server",
                self.env.cr.dbname,
                "ilog.t2",
                "ERROR",
                self.INJECTION,
                self.INJECTION,
                "1",
                "test_raw_insert_is_parameterised",
            ),
        )
        self.assertEqual(self.env["ir.logging"].search_count([]), before + 1)
        record = self.env["ir.logging"].search([("name", "=", "ilog.t2")], limit=1)
        self.assertEqual(
            record.message,
            self.INJECTION,
            "the injection payload must be stored verbatim, not executed",
        )
        self.assertEqual(record.path, self.INJECTION)


@tagged("post_install", "-at_install")
class TestIrLoggingRetention(TransactionCase):
    def _insert_log(self, age_days, name="ilog.t3"):
        self.env.cr.execute(
            """
            INSERT INTO ir_logging(create_date, type, dbname, name, level, message, path, line, func)
            VALUES ((NOW() AT TIME ZONE 'UTC') - %s * interval '1 day',
                    'server', %s, %s, 'INFO', 'message', 'path', '1', 'func')
            RETURNING id
            """,
            (age_days, self.env.cr.dbname, name),
        )
        return self.env["ir.logging"].browse(self.env.cr.fetchone()[0])

    def test_gc_default_retention(self):
        stale = self._insert_log(200)
        fresh = self._insert_log(10)
        result = self.env["ir.logging"]._gc_logging()
        self.assertIsNotNone(result)
        done, more_may_remain = result
        self.assertGreaterEqual(done, 1)
        self.assertFalse(more_may_remain)
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())

    def test_gc_custom_retention(self):
        self.env["ir.config_parameter"].set_param("base.logging_retention_days", "30")
        stale = self._insert_log(40)
        fresh = self._insert_log(20)
        self.env["ir.logging"]._gc_logging()
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())

    def test_gc_zero_retention_skips(self):
        self.env["ir.config_parameter"].set_param("base.logging_retention_days", "0")
        stale = self._insert_log(4000)
        with self.assertLogs(_IR_LOGGING_LOGGER, level="WARNING") as capture:
            self.assertIsNone(self.env["ir.logging"]._gc_logging())
        self.assertTrue(stale.exists())
        self.assertTrue(
            any("logging_retention_days" in line for line in capture.output)
        )

    def test_gc_invalid_retention_skips(self):
        self.env["ir.config_parameter"].set_param(
            "base.logging_retention_days", "not-a-number"
        )
        stale = self._insert_log(4000)
        with self.assertLogs(_IR_LOGGING_LOGGER, level="WARNING") as capture:
            self.assertIsNone(self.env["ir.logging"]._gc_logging())
        self.assertTrue(stale.exists())
        self.assertTrue(any("not-a-number" in line for line in capture.output))
