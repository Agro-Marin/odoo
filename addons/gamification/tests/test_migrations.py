from odoo.fields import Command
from odoo.modules.module import get_module_path, load_script
from odoo.tests import common


class TestPostMigrate11(common.TransactionCase):
    """Tests for ``gamification/migrations/1.1/post-migrate.py``.

    The script is loaded through :func:`~odoo.modules.module.load_script`, the
    same loader Odoo uses, and run against the test cursor: unlike the SQL-only
    pre-migrate scripts elsewhere in the tree it drives the ORM, so a mocked
    cursor would test nothing.
    """

    # The rules the data file cannot re-point on -u, because
    # security/gamification_security.xml opens with <odoo noupdate="1">.
    REPOINTED = {
        "gamification.goal_user_visibility": (
            "gamification.group_gamification_user",
            "base.group_portal",
        ),
        "gamification.goal_gamification_manager_visibility": (
            "gamification.group_gamification_manager",
        ),
        "gamification.streak_user_write": ("gamification.group_gamification_user",),
        "gamification.kudos_user_write": ("gamification.group_gamification_user",),
        "gamification.mentorship_own_only": ("gamification.group_gamification_user",),
        "gamification.mentorship_manager_rule": (
            "gamification.group_gamification_manager",
        ),
        "gamification.activity_visibility": ("gamification.group_gamification_user",),
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = load_script(
            f"{get_module_path('gamification')}/migrations/1.1/post-migrate.py",
            "gamification_1_1_post_migrate",
        )

    def _revert_to_base_tiers(self):
        """Put the pre-t24520 groups back on the seven rules.

        Reproduces what an existing database looks like the moment the upgrade
        starts: the data file has been skipped as noupdate, so the rules still
        carry the base.* groups.
        """
        old_groups = {
            "gamification.group_gamification_user": "base.group_user",
            "gamification.group_gamification_manager": "base.group_erp_manager",
        }
        for rule_xmlid, group_xmlids in self.REPOINTED.items():
            ids = [
                self.env.ref(old_groups.get(xmlid, xmlid)).id for xmlid in group_xmlids
            ]
            self.env.ref(rule_xmlid).groups = [Command.set(ids)]

    def test_post_migrate_repoints_rules(self):
        """Every noupdate rule ends up on the app tier it belongs to."""
        self._revert_to_base_tiers()

        self.script.migrate(self.env.cr, "19.0.1.0")

        for rule_xmlid, group_xmlids in self.REPOINTED.items():
            with self.subTest(rule=rule_xmlid):
                expected = self.env["res.groups"].browse(
                    [self.env.ref(x).id for x in group_xmlids]
                )
                self.assertEqual(self.env.ref(rule_xmlid).groups, expected)

    def test_post_migrate_is_idempotent(self):
        """Running the script twice leaves the same groups, not duplicates."""
        self._revert_to_base_tiers()

        self.script.migrate(self.env.cr, "19.0.1.0")
        first_pass = {xmlid: self.env.ref(xmlid).groups for xmlid in self.REPOINTED}
        self.script.migrate(self.env.cr, "19.0.1.0")

        for rule_xmlid, groups in first_pass.items():
            with self.subTest(rule=rule_xmlid):
                self.assertEqual(self.env.ref(rule_xmlid).groups, groups)

    def test_post_migrate_cleans_root_menu_groups(self):
        """The root ends up on the app tier alone, with no base.group_no_one left.

        <menuitem groups="..."> emits Command.link, so on an existing database
        the old gate survives next to the new one and the tile stays invisible
        outside developer mode. Reproduced here by re-linking it.
        """
        root = self.env.ref("gamification.gamification_menu")
        app_group = self.env.ref("gamification.group_gamification_user")
        root.group_ids = [
            Command.set([self.env.ref("base.group_no_one").id, app_group.id])
        ]

        self.script.migrate(self.env.cr, "19.0.1.0")

        self.assertEqual(root.group_ids, app_group)

    def test_post_migrate_survives_a_hand_deleted_rule(self):
        """A rule someone removed by hand is skipped, not an upgrade failure."""
        self._revert_to_base_tiers()
        self.env.ref("gamification.kudos_user_write").unlink()

        self.script.migrate(self.env.cr, "19.0.1.0")

        survivor = self.env.ref("gamification.streak_user_write")
        self.assertEqual(
            survivor.groups,
            self.env.ref("gamification.group_gamification_user"),
        )
