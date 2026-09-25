from unittest.mock import patch

from odoo.fields import Command
from odoo.tests.common import TransactionCase

from odoo.addons.base.models.res_users_grant import GROUP_STATE_COMPUTED


class TestResUsers(TransactionCase):
    def test_a_new_users_groups_are_not_asked_before_its_grants_exist(self):
        Grant = type(self.env["res.users.grant"])
        follow = Grant._follow_membership
        asked_early = []

        def record_early_asks(grants, added, removed, fresh_user_ids=()):
            computed = grants.env.cr.cache.get(GROUP_STATE_COMPUTED, set())
            asked_early.extend(set(fresh_user_ids) & computed)
            return follow(grants, added, removed, fresh_user_ids)

        with patch.object(Grant, "_follow_membership", record_early_asks):
            self.env["res.users"].create(
                [
                    {"name": "Early internal", "login": "early_internal"},
                    {
                        "name": "Early private",
                        "login": "early_private",
                        "calendar_default_privacy": "private",
                    },
                    {
                        "name": "Early portal",
                        "login": "early_portal",
                        "calendar_default_privacy": "private",
                        "group_ids": [
                            Command.set(self.env.ref("base.group_portal").ids)
                        ],
                    },
                ]
            )
        self.assertFalse(asked_early)

    def test_creating_users_keeps_what_others_have_cached(self):
        admin = self.env.ref("base.user_admin")
        admin._get_group_ids()
        self.env["res.users"].create(
            [
                {"name": f"Cache keeper {i}", "login": f"cache_keeper_{i}"}
                for i in range(3)
            ]
        )
        with self.assertQueryCount(0):
            admin._get_group_ids()

    def test_one_create_gives_each_internal_user_its_own_privacy(self):
        self.env["ir.config_parameter"].set_param("calendar.default_privacy", "private")
        portal = self.env.ref("base.group_portal")
        internal, confidential, public, outsider = self.env["res.users"].create(
            [
                {"name": "Batch default", "login": "batch_default"},
                {
                    "name": "Batch confidential",
                    "login": "batch_confidential",
                    "calendar_default_privacy": "confidential",
                },
                {
                    "name": "Batch public",
                    "login": "batch_public",
                    "calendar_default_privacy": "public",
                },
                {
                    "name": "Batch portal",
                    "login": "batch_portal",
                    "calendar_default_privacy": "confidential",
                    "group_ids": [Command.set(portal.ids)],
                },
            ]
        )
        self.assertEqual(
            [
                user.sudo().res_users_settings_id.calendar_default_privacy
                for user in (internal, confidential, public)
            ],
            ["private", "confidential", "public"],
        )
        self.assertFalse(outsider.sudo().res_users_settings_id)
        self.assertEqual(outsider.calendar_default_privacy, "private")

    def test_same_calendar_default_privacy_as_user_template(self):
        """
        The 'calendar default privacy' variable can be set in the Default User Template
        for defining which privacy the new user's calendars will have when creating a
        user. Ensure that when creating a new user, its calendar default privacy will
        have the same value as defined in the template.
        """

        def create_user(name, login, email, privacy=None):
            vals = {"name": name, "login": login, "email": email}
            if privacy is not None:
                vals["calendar_default_privacy"] = privacy
            return self.env["res.users"].create(vals)

        # Get Default User Template and define expected outputs for each privacy update test.
        privacy_and_output = [
            (False, "public"),
            ("public", "public"),
            ("private", "private"),
            ("confidential", "confidential"),
        ]
        for privacy, expected_output in privacy_and_output:
            # Update default privacy.
            if privacy:
                self.env["ir.config_parameter"].set_param(
                    "calendar.default_privacy", privacy
                )

            # If Calendar Default Privacy isn't defined in vals: get the privacy from Default User Template.
            username = "test_%s_%s" % (str(privacy), expected_output)
            new_user = create_user(username, username, username + "@user.com")
            self.assertEqual(
                new_user.calendar_default_privacy,
                expected_output,
                "Calendar default privacy %s should be %s, same as in the Default User Template."
                % (new_user.calendar_default_privacy, expected_output),
            )

            # If Calendar Default Privacy is defined in vals: override the privacy from Default User Template.
            for custom_privacy in ["public", "private", "confidential"]:
                custom_name = str(custom_privacy) + username
                custom_user = create_user(
                    custom_name,
                    custom_name,
                    custom_name + "@user.com",
                    privacy=custom_privacy,
                )
                self.assertEqual(
                    custom_user.calendar_default_privacy,
                    custom_privacy,
                    "Custom %s privacy from in vals must override the privacy %s from Default User Template."
                    % (custom_privacy, privacy),
                )

    def test_avoid_res_users_settings_creation_portal(self):
        """
        This test ensures that 'res.users.settings' entries are not created for portal
        and public users through the new 'calendar_default_privacy' field, since it is
        not useful tracking these fields for non-internal users.
        """
        username_and_group = {
            "PORTAL": "base.group_portal",
            "PUBLIC": "base.group_public",
        }

        for username, group in username_and_group.items():
            # Create user and impersonate it as sudo for triggering the compute.
            user = self.env["res.users"].create(
                {
                    "name": username,
                    "login": username,
                    "email": username + "@email.com",
                    "group_ids": [(6, 0, [self.env.ref(group).id])],
                }
            )
            user.with_user(user).sudo()._compute_calendar_default_privacy()

            # Ensure default privacy fallback and also that no 'res.users.settings' entry got created.
            self.assertEqual(
                user.calendar_default_privacy,
                "public",
                "Calendar default privacy of %s users must fallback to 'public'."
                % (username),
            )
            self.assertFalse(
                user.sudo().res_users_settings_id,
                "No res.users.settings record must be created for '%s' users."
                % (username),
            )
