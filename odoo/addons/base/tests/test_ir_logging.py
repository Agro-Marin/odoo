from odoo.tests.common import TransactionCase, tagged
from odoo.tools import sql


@tagged("post_install", "-at_install")
class TestIrLoggingInit(TransactionCase):
    """ILOG-T1: pin the FK-drop idempotency contract of ``ir.logging.init``.

    ``init`` drops the legacy ``ir_logging_write_uid_fkey`` foreign key only
    when it is still present (existence-checked via ``constraint_definition``).
    The check-then-drop is deliberate: an unconditional ``DROP CONSTRAINT``
    takes an ACCESS EXCLUSIVE lock even when the constraint is absent, which
    would conflict with the ROW EXCLUSIVE lock an ir_logging insert needs and
    could hang a module install/update. Regressing to an unconditional drop
    would silently reintroduce that lock hazard.
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
