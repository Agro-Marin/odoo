from odoo.exceptions import AccessError
from odoo.tests import common

from odoo.addons.mail.tests.common import mail_new_test_user


class TestMenuSecurity(common.TransactionCase):
    """The app surface: one root tile, management branches closed to employees.

    Every assertion runs against ``load_menus()``, never ``_visible_menu_ids()``.
    The two disagree on purpose: a leaf whose only gate is its parent's still
    passes ``_visible_menu_ids`` and is dropped later by the orphan sweep
    (ir_ui_menu.py:342). Asserting on the wrong one produces a false red.
    """

    # Gated by their parent alone, so they must vanish with it.
    MANAGER_ONLY_LEAVES = (
        "gamification.gamification_activity_feed_menu",
        "gamification.gamification_engagement_menu",
        "gamification.gamification_definition_menu",
        "gamification.gamification_karma_ranks_menu",
        "gamification.gamification_karma_tracking_menu",
        "gamification.gamification_streak_type_menu",
        "gamification.gamification_kudos_category_menu",
        "gamification.gamification_skill_tree_menu",
    )
    MANAGER_ONLY_PARENTS = (
        "gamification.gamification_config_parent_menu",
        "gamification.gamification_analytics_parent_menu",
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.root = cls.env.ref("gamification.gamification_menu")
        cls.employee = mail_new_test_user(
            cls.env,
            login="gam_menu_employee",
            name="Menu Employee",
            email="gam_menu_emp@example.com",
            groups="base.group_user",
        )
        cls.manager = mail_new_test_user(
            cls.env,
            login="gam_menu_manager",
            name="Menu Manager",
            email="gam_menu_mgr@example.com",
            groups="base.group_user,gamification.group_gamification_manager",
        )

    def _loaded_menu_ids(self, user):
        """Return the menu ids ``user`` actually gets in the web client.

        :param user: the ``res.users`` record to load the menus for
        :rtype: set[int]
        """
        menus = self.env["ir.ui.menu"].with_user(user).load_menus(False)
        return {key for key in menus if isinstance(key, int)}

    def _module_menu_ids(self):
        """Return the ids of every ir.ui.menu this module owns.

        :rtype: set[int]
        """
        xmlids = self.env["ir.model.data"].search(
            [("module", "=", "gamification"), ("model", "=", "ir.ui.menu")]
        )
        return set(xmlids.mapped("res_id"))

    def test_root_menu_is_app(self):
        """The root is a top-level tile, not a branch of Settings."""
        self.assertFalse(self.root.parent_id)
        self.assertTrue(self.root.web_icon)
        self.assertEqual(self.root.name, "Gamification")

    def test_dashboard_label_omits_the_app_name(self):
        """Inside an app named Gamification, the leaf says Dashboard.

        The label lives on the client action, not on the menuitem, so the same
        string is the breadcrumb: renaming it in one place fixes both. 10 menus
        and 7 actions in this database are named exactly "Dashboard"; the four
        "<X> Dashboard" labels all qualify between sibling dashboards instead of
        repeating their app's name.
        """
        dashboard = self.env.ref("gamification.gamification_dashboard_menu")
        self.assertEqual(dashboard.name, "Dashboard")
        self.assertEqual(
            self.env.ref("gamification.gamification_dashboard_action").name,
            "Dashboard",
        )

    def test_root_visible_for_plain_user(self):
        """A plain employee reaches the app without developer mode."""
        self.assertIn(self.root.id, self._loaded_menu_ids(self.employee))

    def test_config_and_analytics_hidden_for_user(self):
        """Neither management branch, nor any of its leaves, reaches employees."""
        loaded = self._loaded_menu_ids(self.employee)
        for xmlid in self.MANAGER_ONLY_PARENTS + self.MANAGER_ONLY_LEAVES:
            with self.subTest(menu=xmlid):
                self.assertNotIn(self.env.ref(xmlid).id, loaded)

    def test_employee_still_sees_the_participation_branches(self):
        """Hiding the management branches must not empty the app."""
        loaded = self._loaded_menu_ids(self.employee)
        for xmlid in (
            "gamification.gamification_dashboard_menu",
            "gamification.gamification_activity_parent_menu",
            "gamification.gamification_recognition_parent_menu",
            "gamification.gamification_teams_parent_menu",
        ):
            with self.subTest(menu=xmlid):
                self.assertIn(self.env.ref(xmlid).id, loaded)

    def test_config_visible_and_writable_for_manager(self):
        """The manager's branches open *and* save, not open read-only.

        gamification.karma.tracking is the deliberate exception: it stays
        system-only (karma audit trail), so its menu is filtered out for a
        manager without base.group_system. Asserted rather than skipped, so the
        day someone widens that ACL this test says so.
        """
        loaded = self._loaded_menu_ids(self.manager)
        tracking_menu = self.env.ref("gamification.gamification_karma_tracking_menu")

        for xmlid in self.MANAGER_ONLY_PARENTS:
            with self.subTest(menu=xmlid):
                self.assertIn(self.env.ref(xmlid).id, loaded)

        for xmlid in self.MANAGER_ONLY_LEAVES:
            menu = self.env.ref(xmlid)
            if menu == tracking_menu:
                continue
            with self.subTest(menu=xmlid):
                self.assertIn(menu.id, loaded)
                res_model = menu.action.res_model
                records = self.env[res_model].with_user(self.manager).browse()
                self.assertTrue(records.has_access("write"))

        self.assertFalse(self.manager.has_group("base.group_system"))
        self.assertNotIn(tracking_menu.id, loaded)

    def test_portal_and_public_see_no_gamification_menus(self):
        """Promoting the tree to an app must not leak it to external audiences."""
        module_menus = self._module_menu_ids()
        portal = mail_new_test_user(
            self.env,
            login="gam_menu_portal",
            name="Menu Portal",
            email="gam_menu_portal@example.com",
            groups="base.group_portal",
        )
        for user in (portal, self.env.ref("base.public_user")):
            with self.subTest(user=user.login):
                # The substantive gate: the root hangs off the app tier, which
                # only base.group_user hands out.
                self.assertFalse(user.has_group("gamification.group_gamification_user"))
                try:
                    loaded = self._loaded_menu_ids(user)
                except AccessError:
                    # Measured, not assumed: these audiences cannot read
                    # ir.ui.menu at all, so there is no backend tree for the
                    # promotion to leak into. Should that ever change, the
                    # assertion below starts running instead of being skipped.
                    continue
                self.assertFalse(loaded & module_menus)
