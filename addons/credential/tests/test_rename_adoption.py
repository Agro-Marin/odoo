from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..hooks import adopt_expiry_cron, adopt_renamed_module

_OLD = "base_credential_manager"
_EXPIRY_CRON = "ir_cron_check_expiring_credentials"


@tagged("post_install", "-at_install")
class TestRenameAdoption(TransactionCase):
    def _seed_ghost_module(self, state="installed"):
        self.env.cr.execute("SELECT id FROM ir_module_module WHERE name = %s", (_OLD,))
        row = self.env.cr.fetchone()
        if row:
            self.env.cr.execute(
                "UPDATE ir_module_module SET state = %s WHERE id = %s", (state, row[0])
            )
            return row[0]
        self.env.cr.execute(
            """
            INSERT INTO ir_module_module (name, state, auto_install, application)
                 VALUES (%s, %s, false, false)
              RETURNING id
            """,
            (_OLD, state),
        )
        return self.env.cr.fetchone()[0]

    def _seed_owned_row(self, name, module=_OLD):
        model_id = self.env["ir.model"]._get_id("res.partner")
        self.env.cr.execute(
            """
            INSERT INTO ir_model_data (module, name, model, res_id, noupdate)
                 VALUES (%s, %s, 'ir.model', %s, false)
              RETURNING id
            """,
            (module, name, model_id),
        )
        return self.env.cr.fetchone()[0]

    def _owner_of(self, name):
        self.env.cr.execute("SELECT module FROM ir_model_data WHERE name = %s", (name,))
        return [row[0] for row in self.env.cr.fetchall()]

    def test_records_change_module_rather_than_being_left_behind(self):
        self._seed_ghost_module()
        self._seed_owned_row("adoption_probe_group")

        adopted = adopt_renamed_module(self.env.cr)

        self.assertGreaterEqual(adopted, 1)
        self.assertEqual(self._owner_of("adoption_probe_group"), ["credential"])

    def test_dependency_rows_are_repointed(self):
        self._seed_ghost_module()
        self.env.cr.execute(
            "SELECT id FROM ir_module_module WHERE name = 'api_transport'"
        )
        consumer = self.env.cr.fetchone()
        if not consumer:
            self.skipTest("api_transport is not in this database")
        self.env.cr.execute(
            "UPDATE ir_module_module_dependency SET name = %s "
            "WHERE module_id = %s AND name = 'credential'",
            (_OLD, consumer[0]),
        )

        adopt_renamed_module(self.env.cr)

        self.env.cr.execute(
            "SELECT count(*) FROM ir_module_module_dependency WHERE name = %s", (_OLD,)
        )
        self.assertEqual(
            self.env.cr.fetchone()[0], 0, "a consumer still names the ghost"
        )

    def test_the_ghost_is_retired_not_deleted(self):
        ghost_id = self._seed_ghost_module()

        adopt_renamed_module(self.env.cr)

        self.env.cr.execute(
            "SELECT state FROM ir_module_module WHERE id = %s", (ghost_id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "uninstalled")

    def test_a_colliding_row_under_our_name_is_dropped_first(self):
        self._seed_ghost_module()
        self._seed_owned_row("adoption_collision")
        self._seed_owned_row("adoption_collision", module="credential")

        adopt_renamed_module(self.env.cr)

        self.assertEqual(
            self._owner_of("adoption_collision"),
            ["credential"],
            "the unique (module, name) index would reject two rows",
        )

    def test_a_fresh_database_is_untouched(self):
        self.env.cr.execute("DELETE FROM ir_module_module WHERE name = %s", (_OLD,))

        self.assertEqual(adopt_renamed_module(self.env.cr), 0)

    def test_an_already_retired_ghost_is_left_alone(self):
        self._seed_ghost_module(state="uninstalled")
        self._seed_owned_row("adoption_not_mine")

        self.assertEqual(adopt_renamed_module(self.env.cr), 0)
        self.assertEqual(self._owner_of("adoption_not_mine"), [_OLD])

    def test_the_expiry_cron_is_adopted_on_the_install_path_too(self):
        self.env.cr.execute(
            "UPDATE ir_model_data SET module = 'api_transport' "
            "WHERE module = 'credential' AND name = %s",
            (_EXPIRY_CRON,),
        )
        if not self.env.cr.rowcount:
            self.skipTest("the expiry cron is not in this database")

        adopt_expiry_cron(self.env.cr)

        self.assertEqual(self._owner_of(_EXPIRY_CRON), ["credential"])

    def test_the_expiry_adoption_is_idempotent(self):
        self.assertEqual(adopt_expiry_cron(self.env.cr), 0)

    def test_running_twice_changes_nothing_the_second_time(self):
        self._seed_ghost_module()
        self._seed_owned_row("adoption_idempotent")

        first = adopt_renamed_module(self.env.cr)
        second = adopt_renamed_module(self.env.cr)

        self.assertGreaterEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(self._owner_of("adoption_idempotent"), ["credential"])
