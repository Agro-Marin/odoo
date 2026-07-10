from odoo.tests.common import TransactionCase, tagged
from odoo.tools import sql

_IR_LOGGING_LOGGER = "odoo.addons.base.models.ir_logging"


@tagged("post_install", "-at_install")
class TestIrLoggingInit(TransactionCase):
    """ILOG-T1: pin the FK-drop idempotency contract of ``ir.logging.init``.

    ``init`` drops the legacy ``ir_logging_write_uid_fkey`` foreign key only
    when present (checked via ``constraint_definition``). The check-then-drop
    is deliberate: an unconditional ``DROP CONSTRAINT`` takes an ACCESS
    EXCLUSIVE lock even when the constraint is absent, conflicting with the
    ROW EXCLUSIVE lock an ir_logging insert needs and hanging a module
    install/update.
    """

    CONSTRAINT = "ir_logging_write_uid_fkey"

    def test_write_uid_fkey_absent_after_install(self):
        """The legacy write_uid FK is gone after the module is installed."""
        self.assertIsNone(
            sql.constraint_definition(self.env.cr, "ir_logging", self.CONSTRAINT),
            "ir.logging.init must drop the legacy write_uid foreign key",
        )

    def test_init_is_idempotent(self):
        """Re-running ``init`` is a no-op: the FK stays absent and no error is
        raised (the existence check short-circuits the DROP)."""
        model = self.env["ir.logging"]
        model.init()
        self.assertIsNone(
            sql.constraint_definition(self.env.cr, "ir_logging", self.CONSTRAINT),
            "a second init() must not recreate the FK",
        )
        # A third call is equally inert.
        model.init()
        self.assertIsNone(
            sql.constraint_definition(self.env.cr, "ir_logging", self.CONSTRAINT)
        )


@tagged("post_install", "-at_install")
class TestIrLoggingRawInsert(TransactionCase):
    """ILOG-T2: pin that the raw (ORM-bypass) ir_logging insert path is
    parameterised, so attacker-derived log fields cannot inject SQL.

    The production writer is ``logutils.PostgreSQLHandler.emit``, which issues
    a parameterised ``INSERT INTO ir_logging`` on a dedicated cursor. This test
    reproduces that statement shape with a SQL-injection payload as the message
    and asserts it is stored verbatim (a bound parameter, never executed) and
    the table survives intact.
    """

    INJECTION = "'); DROP TABLE ir_logging; --"

    def test_raw_insert_is_parameterised(self):
        """A message containing SQL metacharacters is stored literally and the
        ir_logging table is not dropped."""
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
        # The table still exists and the row count increased by exactly one.
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
    """ILOG-T3: pin the ``_gc_logging`` retention contract.

    ir_logging rows (server-action ``log()``, ``--log-db``) have no other
    cleanup path; ``_gc_logging`` must delete entries older than the
    ``base.logging_retention_days`` parameter (default 180) using the
    ``(done, more_may_remain)`` autovacuum convention, and must skip the
    collection -- with a warning -- when the parameter is zero, negative or
    unparsable (deployments archiving the table externally).
    """

    def _insert_log(self, age_days, name="ilog.t3"):
        """Insert a row the production way (raw SQL, ORM bypass) with a
        create_date ``age_days`` in the past, relative to the transaction
        clock used by the GC cutoff."""
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
        """Without a parameter set, entries older than 180 days are removed
        and newer ones are kept."""
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
        """A custom ``base.logging_retention_days`` value drives the cutoff."""
        self.env["ir.config_parameter"].set_param("base.logging_retention_days", "30")
        stale = self._insert_log(40)
        fresh = self._insert_log(20)
        self.env["ir.logging"]._gc_logging()
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())

    def test_gc_zero_retention_skips(self):
        """A zero value disables the collection with a warning."""
        self.env["ir.config_parameter"].set_param("base.logging_retention_days", "0")
        stale = self._insert_log(4000)
        with self.assertLogs(_IR_LOGGING_LOGGER, level="WARNING") as capture:
            self.assertIsNone(self.env["ir.logging"]._gc_logging())
        self.assertTrue(stale.exists())
        self.assertTrue(
            any("logging_retention_days" in line for line in capture.output)
        )

    def test_gc_invalid_retention_skips(self):
        """An unparsable value disables the collection with a warning instead
        of crashing the autovacuum method."""
        self.env["ir.config_parameter"].set_param(
            "base.logging_retention_days", "not-a-number"
        )
        stale = self._insert_log(4000)
        with self.assertLogs(_IR_LOGGING_LOGGER, level="WARNING") as capture:
            self.assertIsNone(self.env["ir.logging"]._gc_logging())
        self.assertTrue(stale.exists())
        self.assertTrue(any("not-a-number" in line for line in capture.output))
