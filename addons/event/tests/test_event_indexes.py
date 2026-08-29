from odoo.tests import tagged

from odoo.addons.event.tests.common import EventCase


@tagged("event_internals")
class TestEventIndexes(EventCase):
    """Foreign keys the ORM searches on behind the user's back.

    A `Many2one` only gets a Postgres index when the field asks for one --
    Postgres does not index the referencing side of a foreign key by itself. So
    every column the ORM has to *search* rather than follow costs a sequential
    scan of the whole table until someone declares `index=`, and none of those
    searches appear in the code that pays for them.
    """

    def _assert_indexed(self, model_name, field_name):
        model = self.env[model_name]
        field = model._fields[field_name]
        self.assertTrue(
            field.index,
            f"{model_name}.{field_name} must declare an index",
        )
        self.env.cr.execute(
            """
            SELECT 1
              FROM pg_index i
              JOIN pg_class t ON t.oid = i.indrelid
              JOIN pg_attribute a
                ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
             WHERE t.relname = %s
               AND a.attname = %s
               AND i.indnatts = 1
            """,
            (model._table, field_name),
        )
        self.assertTrue(
            self.env.cr.fetchone(),
            f"{model._table}.{field_name} has no index in the database",
        )

    def test_event_mail_slot_event_slot_id_is_indexed(self):
        """`event.mail.slot.event_slot_id` carries a stored compute's dependency.

        `scheduled_date` is stored and depends on `event_slot_id.start_datetime`
        and `event_slot_id.end_datetime`. `event.slot` declares no One2many back
        to `event.mail.slot`, so when one of those datetimes is written the ORM
        cannot follow an inverse and falls to the `search` branch of
        `_modified_triggers` -- one query per write, filtering this table on
        this column. Rescheduling an event rewrites its slots in bulk.
        """
        self._assert_indexed("event.mail.slot", "event_slot_id")
