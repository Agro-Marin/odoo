"""The index behind the systray's attendee lookup.

Kept in its own file rather than added to `test_attendees.py`: that file
predates the fork's ruff-format hook, so touching it rewrites three hundred
lines that have nothing to do with this test.
"""

from odoo.tests import common
from odoo.tools import SQL

# Odoo names a single-column index `<table>__<column>_index`.
PARTNER_INDEX = "calendar_attendee__partner_id_index"

# The composite this would otherwise lean on. Its LEADING column is `event_id`,
# so PostgreSQL can serve a bare `partner_id` predicate from it only as a skip
# scan -- one index search per distinct `event_id`.
COMPOSITE_INDEX = "calendar_attendee_event_id_partner_id_unique"


class TestAttendeePartnerIndex(common.TransactionCase):
    def _populate(self, events=2000, partners=200):
        """Fill `calendar_attendee` with the shape the systray meets.

        Many meetings, few attendees on each, and each partner on a small
        fraction of the total -- which is what makes the lookup selective and
        the skip scan expensive. Written as raw SQL because the ORM path would
        spend the test's whole budget computing fields nothing here reads.
        """
        self.env.cr.execute(
            """
            INSERT INTO res_partner (name, active, company_id, create_uid,
                                     write_uid, create_date, write_date)
            SELECT 'idx-partner-' || g, true, 1, 1, 1, now(), now()
            FROM generate_series(1, %s) g
            RETURNING id
            """,
            (partners,),
        )
        partner_ids = [row[0] for row in self.env.cr.fetchall()]
        self.env.cr.execute(
            """
            INSERT INTO calendar_event (name, show_as, start, stop, active,
                                        create_uid, write_uid, create_date, write_date)
            SELECT 'idx-event-' || g, 'busy', now(), now(), true, 1, 1, now(), now()
            FROM generate_series(1, %s) g
            RETURNING id
            """,
            (events,),
        )
        event_ids = [row[0] for row in self.env.cr.fetchall()]
        self.env.cr.execute(
            """
            INSERT INTO calendar_attendee (event_id, partner_id, state, create_uid,
                                           write_uid, create_date, write_date)
            SELECT e.id, p.id, 'needsAction', 1, 1, now(), now()
            FROM unnest(%s) WITH ORDINALITY AS e(id, rn)
            CROSS JOIN LATERAL (
                SELECT unnest(%s[(e.rn %% %s) + 1 : (e.rn %% %s) + 4]) AS id
            ) p
            """,
            (event_ids, partner_ids, partners - 4, partners - 4),
        )
        self.env.cr.execute("ANALYZE calendar_attendee")
        return partner_ids

    def _plan_for_systray_lookup(self, partner_id):
        """EXPLAIN the query `_get_activity_groups` issues for the systray."""
        query = self.env["calendar.attendee"]._search(
            [("partner_id", "=", partner_id), ("state", "!=", "declined")]
        )
        self.env.cr.execute(SQL("EXPLAIN %s", query.select()))
        return "\n".join(row[0] for row in self.env.cr.fetchall())

    def test_partner_id_carries_its_own_index(self):
        self.env.cr.execute(
            "SELECT 1 FROM pg_indexes WHERE tablename = %s AND indexname = %s",
            ("calendar_attendee", PARTNER_INDEX),
        )
        self.assertTrue(
            self.env.cr.fetchone(),
            f"{PARTNER_INDEX} is missing: the systray's per-request lookup on "
            f"calendar.attendee.partner_id has no index with that leading column",
        )

    def test_systray_lookup_does_not_fall_back_to_the_composite(self):
        partner_ids = self._populate()
        plan = self._plan_for_systray_lookup(partner_ids[0])
        self.assertIn(
            PARTNER_INDEX,
            plan,
            f"the systray lookup should read {PARTNER_INDEX}; plan was:\n{plan}",
        )
        self.assertNotIn(
            COMPOSITE_INDEX,
            plan,
            f"the systray lookup fell back to a skip scan on {COMPOSITE_INDEX}, "
            f"whose cost grows with the number of meetings; plan was:\n{plan}",
        )
