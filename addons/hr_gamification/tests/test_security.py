from odoo.tests import common, tagged

from odoo.addons.mail.tests.common import mail_new_test_user


class TestSecurity(common.TransactionCase):
    """The module owns its ACL/rule reach through app tiers, not base.group_user."""

    ALLOWED_GROUPS = (
        "gamification.group_gamification_user",
        "gamification.group_gamification_manager",
        "hr.group_hr_user",
    )

    def _module_acls(self):
        """Return the ir.model.access records this module owns.

        :rtype: recordset of ir.model.access
        """
        xmlids = self.env["ir.model.data"].search(
            [("module", "=", "hr_gamification"), ("model", "=", "ir.model.access")]
        )
        return self.env["ir.model.access"].browse(xmlids.mapped("res_id"))

    def _module_rules(self):
        """Return the ir.rule records this module owns.

        :rtype: recordset of ir.rule
        """
        xmlids = self.env["ir.model.data"].search(
            [("module", "=", "hr_gamification"), ("model", "=", "ir.rule")]
        )
        return self.env["ir.rule"].browse(xmlids.mapped("res_id"))

    def test_no_acl_or_rule_still_points_at_base_group_user(self):
        """Every ACL row and record rule names an app tier, not base.group_user."""
        base_group_user = self.env.ref("base.group_user")
        allowed = {self.env.ref(xmlid) for xmlid in self.ALLOWED_GROUPS}

        acls = self._module_acls()
        for acl in acls:
            with self.subTest(acl=acl.name):
                self.assertNotEqual(acl.group_id, base_group_user)
                self.assertIn(acl.group_id, allowed)
        self.assertEqual(len(acls), 5)

        rules = self._module_rules()
        for rule in rules:
            with self.subTest(rule=rule.name):
                self.assertNotIn(base_group_user, rule.groups)
                self.assertTrue(set(rule.groups.ids) <= {g.id for g in allowed})
        self.assertEqual(len(rules), 4)


@tagged("post_install", "-at_install")
class TestMenuRemoval(common.TransactionCase):
    """The HR-anchored branch is gone once the upgrade finishes.

    Split from TestSecurity and tagged post_install for a mechanical reason,
    not a stylistic one: the menuitems are removed by the orphan sweep in
    _process_end, which runs after every module is loaded, whereas at_install
    tests run right after their own module. Measured on this database, the
    sweep landed 52 seconds after the at_install pass had already read the
    menus as still present. Tagged at_install, this test is red on any
    `-u hr_gamification --test-enable` run and green only when the tests are
    invoked separately from the upgrade that does the deleting.
    """

    def test_no_gamification_menu_under_hr(self):
        """HR keeps its Configuration branch, minus every gamification entry.

        Phrased against the live branch rather than against what this module
        declares. "The module owns no ir.ui.menu" is the weaker claim: it also
        holds on a tree that lost HR Configuration altogether, and it goes on
        holding if the branch comes back under someone else's xmlid. What has
        to stay true is that an HR manager opening Configuration finds its
        other entries and no gamification action among them.
        """
        manager = mail_new_test_user(
            self.env,
            login="hr_gam_menu_manager",
            name="HR Gamification Menu Manager",
            email="hr_gam_menu_mgr@example.com",
            groups="base.group_user,hr.group_hr_manager",
        )
        menus = self.env["ir.ui.menu"].with_user(manager).load_menus(False)
        loaded_ids = {key for key in menus if isinstance(key, int)}

        hr_config = self.env.ref("hr.menu_human_resources_configuration")
        self.assertIn(hr_config.id, loaded_ids)

        descendants = (
            self.env["ir.ui.menu"]
            .browse(sorted(loaded_ids))
            .filtered(
                lambda menu: (
                    menu != hr_config
                    and menu.parent_path.startswith(hr_config.parent_path)
                )
            )
        )
        # Vacuity guard: an empty branch would satisfy the loop below for the
        # wrong reason, the way an emptied app satisfied the Phase 3 hiding test.
        self.assertTrue(descendants, "HR Configuration lost every child")
        for menu in descendants:
            with self.subTest(menu=menu.complete_name):
                res_model = getattr(menu.action, "res_model", "") or ""
                self.assertFalse(res_model.startswith("gamification."))

        # The branch this phase removed is gone by xmlid too, so a stale
        # ir.model.data row cannot resurrect it on the next upgrade.
        self.assertFalse(
            self.env.ref(
                "hr_gamification.menu_hr_gamification", raise_if_not_found=False
            )
        )
        self.assertFalse(
            self.env["ir.model.data"].search_count(
                [("module", "=", "hr_gamification"), ("model", "=", "ir.ui.menu")]
            )
        )
