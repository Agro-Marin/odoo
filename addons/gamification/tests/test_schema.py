"""Schema guards for the columns the ORM walks on its own."""

import re

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestGamificationSchema(TransactionCase):
    """Every Many2one that a `related` field traverses must carry an index.

    A non-stored `related` is not read record by record: `_traverse_related_sql`
    (odoo/orm/models/mixins/_query.py) compiles it to a `LEFT JOIN` on the
    comodel, joined on the Many2one column. The challenge cron adds a second
    reader on the same columns, filtering goals on `definition_id.computation_mode`
    on every `_update_all` (models/gamification_challenge.py).

    Our own index lint (odoo/addons/test_lint/tests/test_index.py) only demands
    an index on the inverse of a One2many, which is exactly why these four
    columns were left without one while their siblings got theirs.
    """

    # (table, column) -> what traverses it, quoted in the failure message.
    TRAVERSED = {
        ("gamification_goal", "definition_id"): (
            "five related fields on gamification.goal (computation_mode, "
            "definition_description, definition_condition, definition_suffix, "
            "definition_display) plus the cron's "
            "('definition_id.computation_mode', '!=', 'manually')"
        ),
        ("gamification_goal", "line_id"): (
            "the stored related gamification.goal.challenge_id, which the ORM "
            "re-reads by searching goals on line_id"
        ),
        ("gamification_challenge_line", "definition_id"): (
            "five related fields on gamification.challenge.line, including the "
            "_rec_name `name`, which every name_search on a challenge line joins"
        ),
        ("gamification_goal_definition", "model_id"): (
            "the related gamification.goal.definition.model_inherited_ids"
        ),
    }

    def _index_definitions(self, table):
        self.env.cr.execute(
            """
            SELECT indexdef
              FROM pg_indexes
             WHERE schemaname = current_schema()
               AND tablename = %s
            """,
            [table],
        )
        return [indexdef for [indexdef] in self.env.cr.fetchall()]

    def test_related_many2one_columns_are_indexed(self):
        for (table, column), traversed_by in self.TRAVERSED.items():
            with self.subTest(table=table, column=column):
                definitions = self._index_definitions(table)
                # Pin the exact single-column list. A loose `%definition_id%`
                # would also match a composite index that leads with another
                # column, which Postgres cannot use for this join.
                self.assertTrue(
                    any(
                        re.search(rf"USING btree \({column}\)", indexdef)
                        for indexdef in definitions
                    ),
                    f"{table}.{column} must carry a btree index: it is "
                    f"traversed by {traversed_by}.",
                )
