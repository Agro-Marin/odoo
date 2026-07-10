from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo.api import SUPERUSER_ID
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.http import _request_stack
from odoo.tests import (
    Form,
    HttpCase,
    TransactionCase,
    new_test_user,
    tagged,
    users,
    warmup,
)
from odoo.tools import mute_logger


class UsersCommonCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        users = cls.env["res.users"].create(
            [
                {
                    "name": "Internal",
                    "login": "user_internal",
                    "password": "password",
                    "group_ids": [cls.env.ref("base.group_user").id],
                    "tz": "UTC",
                },
                {
                    "name": "Portal 1",
                    "login": "portal_1",
                    "password": "portal_1",
                    "group_ids": [cls.env.ref("base.group_portal").id],
                },
                {
                    "name": "Portal 2",
                    "login": "portal_2",
                    "password": "portal_2",
                    "group_ids": [cls.env.ref("base.group_portal").id],
                },
            ]
        )

        cls.user_internal, cls.user_portal_1, cls.user_portal_2 = users

        # Drop admin-fetched values so low-privileged tests don't read a polluted cache.
        users.partner_id.invalidate_recordset()
        users.invalidate_recordset()


class TestUsers(UsersCommonCase):
    def test_name_search(self):
        """Check name_search on user."""
        User = self.env["res.users"]

        test_user = User.create({"name": "Flad the Impaler", "login": "vlad"})
        like_user = User.create({"name": "Wlad the Impaler", "login": "vladi"})
        other_user = User.create(
            {"name": "Nothing similar", "login": "nothing similar"}
        )
        all_users = test_user | like_user | other_user

        res = User.name_search("vlad", operator="ilike")
        self.assertEqual(User.browse(i[0] for i in res) & all_users, test_user)

        res = User.name_search("vlad", operator="not ilike")
        self.assertEqual(User.browse(i[0] for i in res) & all_users, all_users)

        res = User.name_search("", operator="ilike")
        self.assertEqual(User.browse(i[0] for i in res) & all_users, all_users)

        res = User.name_search("", operator="not ilike")
        self.assertEqual(User.browse(i[0] for i in res) & all_users, User)

        res = User.name_search("lad", operator="ilike")
        self.assertEqual(
            User.browse(i[0] for i in res) & all_users, test_user | like_user
        )

        res = User.name_search("lad", operator="not ilike")
        self.assertEqual(User.browse(i[0] for i in res) & all_users, other_user)

    def test_user_partner(self):
        """Check that the user partner is well created"""

        User = self.env["res.users"]
        Partner = self.env["res.partner"]
        Company = self.env["res.company"]

        company_1 = Company.create({"name": "company_1"})
        company_2 = Company.create({"name": "company_2"})

        partner = Partner.create({"name": "Bob Partner", "company_id": company_2.id})

        # case 1 : the user has no partner
        test_user = User.create(
            {
                "name": "John Smith",
                "login": "jsmith",
                "company_ids": [company_1.id],
                "company_id": company_1.id,
            }
        )

        self.assertFalse(
            test_user.partner_id.company_id,
            "The partner_id linked to a user should be created without any company_id",
        )

        # case 2 : the user has a partner
        test_user = User.create(
            {
                "name": "Bob Smith",
                "login": "bsmith",
                "company_ids": [company_1.id],
                "company_id": company_1.id,
                "partner_id": partner.id,
            }
        )

        self.assertEqual(
            test_user.partner_id.company_id,
            company_1,
            "If the partner_id of a user has already a company, it is replaced by the user company",
        )

    def test_change_user_company(self):
        """Check the partner company update when the user company is changed"""

        User = self.env["res.users"]
        Company = self.env["res.company"]

        test_user = User.create({"name": "John Smith", "login": "jsmith"})
        company_1 = Company.create({"name": "company_1"})
        company_2 = Company.create({"name": "company_2"})

        test_user.company_ids += company_1
        test_user.company_ids += company_2

        # 1: the partner has no company_id, no modification
        test_user.write({"company_id": company_1.id})

        self.assertFalse(
            test_user.partner_id.company_id,
            "On user company change, if its partner_id has no company_id,"
            "the company_id of the partner_id shall NOT be updated",
        )

        # 2: the partner has a company_id different from the new one, update it
        test_user.partner_id.write({"company_id": company_1.id})

        test_user.write({"company_id": company_2.id})

        self.assertEqual(
            test_user.partner_id.company_id,
            company_2,
            "On user company change, if its partner_id has already a company_id,"
            "the company_id of the partner_id shall be updated",
        )

    @mute_logger("odoo.db")
    def test_deactivate_portal_users_access(self):
        """Test that only a portal users can deactivate his account."""
        with self.assertRaises(
            UserError,
            msg="Internal users should not be able to deactivate their account",
        ):
            self.user_internal._deactivate_portal_user()

    @mute_logger("odoo.db", "odoo.addons.base.models.res_users_deletion")
    def test_deactivate_portal_users_archive_and_remove(self):
        """An account that can't be removed is archived and its sensitive info wiped.

        Here portal_user's deletion succeeds; portal_user_2's fails.
        """
        User = self.env["res.users"]
        portal_user = User.create(
            {
                "name": "Portal",
                "login": "portal_user",
                "password": "password",
                "group_ids": [self.env.ref("base.group_portal").id],
            }
        )
        portal_partner = portal_user.partner_id

        portal_user_2 = User.create(
            {
                "name": "Portal",
                "login": "portal_user_2",
                "password": "password",
                "group_ids": [self.env.ref("base.group_portal").id],
            }
        )
        portal_partner_2 = portal_user_2.partner_id

        (portal_user | portal_user_2)._deactivate_portal_user()

        self.assertTrue(
            portal_user.exists() and not portal_user.active,
            "Should have archived the user 1",
        )

        self.assertEqual(portal_user.name, "Portal", "Should have kept the user name")
        self.assertEqual(
            portal_user.partner_id.name,
            "Portal",
            "Should have kept the partner name",
        )
        self.assertNotEqual(
            portal_user.login,
            "portal_user",
            "Should have removed the user login",
        )

        asked_deletion_1 = self.env["res.users.deletion"].search(
            [("user_id", "=", portal_user.id)]
        )
        asked_deletion_2 = self.env["res.users.deletion"].search(
            [("user_id", "=", portal_user_2.id)]
        )

        self.assertTrue(
            asked_deletion_1,
            "Should have added the user 1 in the deletion queue",
        )
        self.assertTrue(
            asked_deletion_2,
            "Should have added the user 2 in the deletion queue",
        )

        # portal_user_2's deletion fails: this cron references it without ondelete=cascade.
        self.cron = self.env["ir.cron"].create(
            {
                "name": "Test Cron",
                "user_id": portal_user_2.id,
                "model_id": self.env.ref("base.model_res_partner").id,
            }
        )

        with self.enter_registry_test_mode():
            self.env.ref("base.ir_cron_res_users_deletion").method_direct_trigger()

        self.assertFalse(portal_user.exists(), "Should have removed the user")
        self.assertFalse(portal_partner.exists(), "Should have removed the partner")
        self.assertEqual(
            asked_deletion_1.state,
            "done",
            "Should have marked the deletion as done",
        )

        self.assertTrue(portal_user_2.exists(), "Should have kept the user")
        self.assertTrue(portal_partner_2.exists(), "Should have kept the partner")
        self.assertEqual(
            asked_deletion_2.state,
            "fail",
            "Should have marked the deletion as failed",
        )

    def test_delete_public_user(self):
        """Test that the public user cannot be deleted."""
        public_user = self.env.ref("base.public_user")
        public_partner = public_user.partner_id

        with self.assertRaises(UserError, msg="Public user should not be deletable"):
            public_user.unlink()

        self.assertTrue(
            public_user.exists() and not public_user.active,
            "Public user should still exist and be inactive",
        )
        self.assertTrue(
            public_partner.exists() and not public_partner.active,
            "Public partner should still exist and be inactive",
        )

    def test_user_home_action_restriction(self):
        test_user = new_test_user(self.env, "hello world")

        # An action whose context is restricted (references 'active_id') is rejected.
        restricted_action = self.env["ir.actions.act_window"].search(
            [("context", "ilike", "active_id")], limit=1
        )
        with self.assertRaises(ValidationError):
            test_user.action_id = restricted_action.id

        allowed_action = self.env["ir.actions.act_window"].search(
            ["!", ("context", "ilike", "active_id")], limit=1
        )

        test_user.action_id = allowed_action.id
        self.assertEqual(test_user.action_id.id, allowed_action.id)

    def test_context_get_lang(self):
        self.env["res.lang"].with_context(active_test=False).search(
            [("code", "in", ["fr_FR", "es_ES", "de_DE", "en_US"])]
        ).write({"active": True})

        user = new_test_user(self.env, "jackoneill")
        user = user.with_user(user)
        user.lang = "fr_FR"

        company = user.company_id.partner_id.sudo()
        company.lang = "de_DE"

        request = SimpleNamespace()
        request.best_lang = "es_ES"
        request_patch = patch("odoo.addons.base.models.res_users.request", request)
        self.addCleanup(request_patch.stop)
        request_patch.start()

        self.assertEqual(user.context_get()["lang"], "fr_FR")
        self.env.registry.clear_cache()
        user.lang = False

        self.assertEqual(user.context_get()["lang"], "es_ES")
        self.env.registry.clear_cache()
        request_patch.stop()

        self.assertEqual(user.context_get()["lang"], "de_DE")
        self.env.registry.clear_cache()
        company.lang = False

        self.assertEqual(user.context_get()["lang"], "en_US")

    def test_context_get_request_lang_not_pinned(self):
        """The request's Accept-Language is overlaid per call, never memoised under
        the uid-wide context_get cache key (W2): otherwise a shared uid (e.g. the
        public user) would serve the first visitor's language to everyone.
        """
        self.env["res.lang"].with_context(active_test=False).search(
            [("code", "in", ["fr_FR", "es_ES", "de_DE", "en_US"])]
        ).write({"active": True})
        self.addCleanup(self.env.registry.clear_cache)

        user = new_test_user(self.env, "ctxnopin")
        user = user.with_user(user)
        user.lang = False
        user.company_id.partner_id.sudo().lang = "de_DE"

        patch_target = "odoo.addons.base.models.res_users.request"
        # A request fills the cache with its own language...
        with patch(patch_target, SimpleNamespace(best_lang="es_ES")):
            self.assertEqual(user.context_get()["lang"], "es_ES")
        # ...but without any cache clear, a request-less call still falls back to
        # the DB-derived lang, and other requests get their own language.
        self.assertEqual(user.context_get()["lang"], "de_DE")
        with patch(patch_target, SimpleNamespace(best_lang="fr_FR")):
            self.assertEqual(user.context_get()["lang"], "fr_FR")
        # A request language that is not installed is ignored.
        with patch(patch_target, SimpleNamespace(best_lang="nl_NL")):
            self.assertEqual(user.context_get()["lang"], "de_DE")
        # A valid user preference always outranks the request language.
        user.lang = "fr_FR"
        with patch(patch_target, SimpleNamespace(best_lang="es_ES")):
            self.assertEqual(user.context_get()["lang"], "fr_FR")

    def test_user_self_update(self):
        """Check that the user has access to write his phone."""
        test_user = self.env["res.users"].create(
            {"name": "John Smith", "login": "jsmith"}
        )
        self.assertFalse(test_user.phone)
        test_user.with_user(test_user).write({"phone": "2387478"})

        self.assertEqual(
            test_user.partner_id.phone,
            "2387478",
            "The phone of the partner_id shall be updated.",
        )

    def test_session_non_existing_user(self):
        """Sessions bound to a non-existing (or deleted) user are invalidated."""
        User = self.env["res.users"]
        last_user_id = User.with_context(active_test=False).search(
            [], limit=1, order="id desc"
        )
        non_existing_user = User.browse(last_user_id.id + 1)
        self.assertFalse(non_existing_user._compute_session_token("session_id"))


@tagged("post_install", "-at_install", "groups")
class TestUsers2(UsersCommonCase):
    def test_change_user_login(self):
        """Check that partner email is updated when changing user's login"""

        User = self.env["res.users"]
        with Form(User, view="base.view_users_simple_form") as UserForm:
            UserForm.name = "Test User"
            UserForm.login = "test-user1"
            self.assertFalse(UserForm.email)

            UserForm.login = "test-user1@mycompany.example.org"
            self.assertEqual(
                UserForm.email,
                "test-user1@mycompany.example.org",
                "Setting a valid email as login should update the partner's email",
            )

    def test_default_groups(self):
        """During installation the groups handler uses the normal group_ids field,
        not the "real" view with pseudo-fields, so it always works.
        """
        default_group = self.env.ref("base.default_user_group")
        test_group = self.env["res.groups"].create({"name": "test_group"})
        default_group.implied_ids = test_group

        # use the specific views which has the pseudo-fields
        f = Form(self.env["res.users"], view="base.view_users_form")
        f.name = "bob"
        f.login = "bob"
        user = f.save()

        group_user = self.env.ref("base.group_user")

        self.assertIn(group_user, user.group_ids)
        self.assertEqual(default_group.implied_ids + group_user, user.group_ids)

    def test_selection_groups(self):
        # create 3 groups that should be in a selection
        app = self.env["res.groups.privilege"].create({"name": "Foo"})
        group_user, group_manager, group_visitor = self.env["res.groups"].create(
            [
                {"name": name, "privilege_id": app.id}
                for name in ("User", "Manager", "Visitor")
            ]
        )
        # THIS PART IS NECESSARY TO REPRODUCE AN ISSUE: group1.id < group2.id < group0.id
        self.assertLess(group_user.id, group_manager.id)
        self.assertLess(group_manager.id, group_visitor.id)
        # implication order is group0 < group1 < group2
        group_manager.implied_ids = group_user
        group_user.implied_ids = group_visitor
        groups = group_visitor + group_user + group_manager

        user = self.env["res.users"].create({"name": "foo", "login": "foo"})

        # put user in group_visitor, and check field value
        user.write({"group_ids": [Command.set([group_visitor.id])]})
        self.assertEqual(user.group_ids & groups, group_visitor)
        self.assertEqual(user.all_group_ids & groups, group_visitor)
        self.assertEqual(user.read(["group_ids"])[0]["group_ids"], [group_visitor.id])
        self.assertEqual(
            user.read(["all_group_ids"])[0]["all_group_ids"], [group_visitor.id]
        )

        # remove group_visitor
        user.write({"group_ids": [Command.unlink(group_visitor.id)]})
        self.assertEqual(user.group_ids & groups, self.env["res.groups"])

        # put user in group_manager, and check field value
        user.write({"group_ids": [Command.set([group_manager.id])]})
        self.assertEqual(user.group_ids & groups, group_manager)
        self.assertEqual(
            user.all_group_ids & groups,
            group_visitor + group_manager + group_user,
        )
        self.assertEqual(user.read(["group_ids"])[0]["group_ids"], [group_manager.id])
        self.assertEqual(
            set(user.read(["all_group_ids"])[0]["all_group_ids"]),
            set((group_visitor + group_manager + group_user).ids),
        )

        # add user in group_user, and check field value
        user.write({"group_ids": [Command.link(group_user.id)]})
        self.assertEqual(user.group_ids & groups, group_manager + group_user)
        self.assertEqual(
            user.all_group_ids & groups,
            group_visitor + group_manager + group_user,
        )
        self.assertEqual(
            set(user.read(["group_ids"])[0]["group_ids"]),
            set((group_manager + group_user).ids),
        )
        self.assertEqual(
            set(user.read(["all_group_ids"])[0]["all_group_ids"]),
            set((group_visitor + group_manager + group_user).ids),
        )

        groups = self.env["res.groups"].search([("all_user_ids", "=", user.id)])
        self.assertEqual(groups, user.all_group_ids)

    def test_implied_groups_on_change(self):
        """Test that a change on a reified fields trigger the onchange of group_ids."""
        group_public = self.env.ref("base.group_public")
        group_portal = self.env.ref("base.group_portal")
        group_user = self.env.ref("base.group_user")

        app = self.env["res.groups.privilege"].create({"name": "Foo"})
        group_contain_user = self.env["res.groups"].create(
            {
                "name": "Small user group",
                "privilege_id": app.id,
                "implied_ids": [group_user.id],
            }
        )

        user_form = Form(self.env["res.users"], view="base.view_users_form")
        user_form.name = "Test"
        user_form.login = "Test"
        self.assertFalse(user_form.share)

        user_form["group_ids"] = group_portal
        self.assertTrue(
            user_form.share, "The group_ids onchange should have been triggered"
        )

        user = user_form.save()

        # in debug mode, show the group widget for external user

        with self.debug_mode():
            user_form = Form(user, view="base.view_users_form")

            user_form["group_ids"] = group_user
            self.assertFalse(
                user_form.share,
                "The group_ids onchange should have been triggered",
            )

            user_form["group_ids"] = group_public
            self.assertTrue(
                user_form.share,
                "The group_ids onchange should have been triggered",
            )

            user_form["group_ids"] = group_user
            user_form["group_ids"] = group_user + group_contain_user

            user_form.save()

        # in debug mode, allow extra groups

        with self.debug_mode():
            user_form = Form(self.env["res.users"], view="base.view_users_form")
            user_form.name = "Test-2"
            user_form.login = "Test-2"

            user_form["group_ids"] = group_portal
            self.assertTrue(user_form.share)

            # for portal user, the view_group_extra_ids is only show in debug mode
            user_form["group_ids"] = group_portal + group_contain_user
            self.assertFalse(
                user_form.share,
                "The group_ids onchange should have been triggered",
            )

            with self.assertRaises(
                ValidationError,
                msg="The user cannot be at the same time in groups: ['Membre', 'Portal', 'Foo / Small user group']",
            ):
                user_form.save()

    def test_view_group_hierarchy(self):
        """Test that the group hierarchy shows up in the correct language of the user."""
        self.env["res.lang"]._activate_lang("fr_FR")
        group_system = self.env.ref("base.group_system")
        group_system.with_context(lang="fr_FR").name = "Administrateur"

        view_group_hierarchy_en = self.env["res.groups"]._get_view_group_hierarchy()
        view_group_hierarchy_fr = (
            self.env["res.groups"]
            .with_context(lang="fr_FR")
            ._get_view_group_hierarchy()
        )
        self.assertNotEqual(
            view_group_hierarchy_en["groups"][group_system.id]["name"],
            "Administrateur",
        )
        self.assertEqual(
            view_group_hierarchy_fr["groups"][group_system.id]["name"],
            "Administrateur",
        )

        # Should work the other way around too
        self.env.registry.clear_cache("groups")
        view_group_hierarchy_fr = (
            self.env["res.groups"]
            .with_context(lang="fr_FR")
            ._get_view_group_hierarchy()
        )
        view_group_hierarchy_en = self.env["res.groups"]._get_view_group_hierarchy()
        self.assertNotEqual(
            view_group_hierarchy_en["groups"][group_system.id]["name"],
            "Administrateur",
        )
        self.assertEqual(
            view_group_hierarchy_fr["groups"][group_system.id]["name"],
            "Administrateur",
        )

        with patch(
            "odoo.addons.base.models.res_groups.ResGroups._get_view_group_hierarchy"
        ) as mock:
            self.user_portal_1.copy_data()
            self.assertFalse(mock.called)

    @users("portal_1")
    @mute_logger("odoo.addons.base.models.ir_model")
    def test_self_writeable_fields(self):
        """Check that a portal user:
        - can write on fields in SELF_WRITEABLE_FIELDS on himself,
        - cannot write on fields not in SELF_WRITEABLE_FIELDS on himself,
        - and none of the above on another user than himself.
        """
        self.assertIn(
            "post_install",
            self.test_tags,
            "This test **must** be `post_install` to ensure the expected behavior despite other modules",
        )
        self.assertIn(
            "email",
            self.env["res.users"].SELF_WRITEABLE_FIELDS,
            "For this test to make sense, 'email' must be in the `SELF_WRITEABLE_FIELDS`",
        )
        self.assertNotIn(
            "login",
            self.env["res.users"].SELF_WRITEABLE_FIELDS,
            "For this test to make sense, 'login' must not be in the `SELF_WRITEABLE_FIELDS`",
        )

        me = self.env["res.users"].browse(self.env.user.id)
        other = self.env["res.users"].browse(self.user_portal_2.id)

        # Allow to write a field in the SELF_WRITEABLE_FIELDS
        me.email = "foo@bar.com"
        self.assertEqual(me.email, "foo@bar.com")
        # Disallow to write a field not in the SELF_WRITEABLE_FIELDS
        with self.assertRaises(AccessError):
            me.login = "foo"

        # Disallow to write a field in the SELF_WRITEABLE_FIELDS on another user
        with self.assertRaises(AccessError):
            other.email = "foo@bar.com"
        # Disallow to write a field not in the SELF_WRITEABLE_FIELDS on another user
        with self.assertRaises(AccessError):
            other.login = "foo"

    @users("user_internal")
    def test_self_readable_writeable_fields_preferences_form(self):
        """Test that a field protected by a `groups='...'` with a group the user doesn't belong to
        but part of the `SELF_WRITEABLE_FIELDS` is shown in the user profile preferences form and is editable
        """
        my_user = self.env["res.users"].browse(self.env.user.id)
        self.assertIn(
            "name",
            my_user.SELF_WRITEABLE_FIELDS,
            "This test doesn't make sense if not tested on a field part of the SELF_WRITEABLE_FIELDS",
        )
        self.patch(
            self.env.registry["res.users"]._fields["name"],
            "groups",
            "base.group_system",
        )
        with Form(my_user, view="base.view_users_form_simple_modif") as UserForm:
            UserForm.name = "Raoulette Poiluchette"
        self.assertEqual(my_user.name, "Raoulette Poiluchette")

    @warmup
    def test_write_group_ids_performance(self):
        contact_creation_group = self.env.ref("base.group_partner_manager")
        self.assertNotIn(contact_creation_group, self.user_internal.group_ids)

        # all modules: 23, base: 10; nightly: +1
        with self.assertQueryCount(24):
            self.user_internal.write(
                {
                    "group_ids": [Command.link(contact_creation_group.id)],
                }
            )

    def test_portal_user_manager_access(self):
        # groups
        group_portal = self.env.ref("base.group_portal")
        group_user = self.env.ref("base.group_user")
        group_partner_manager = self.env.ref("base.group_partner_manager")
        group_portal_user_manager = self.env["res.groups"].create(
            {
                "name": "Portal User Manager",
                "user_ids": [],
            }
        )

        # ACL
        self.env["ir.model.access"].create(
            {
                "name": "Allow user profile update",
                "model_id": self.env["ir.model"]._get("res.users").id,
                "group_id": group_portal_user_manager.id,
                "perm_write": True,
            }
        )

        # Rules
        self.env["ir.rule"].create(
            {
                "name": "Allow updates by Portal Managers on PORTAL users (only)",
                "model_id": self.env["ir.model"]._get("res.users").id,
                "groups": [group_portal_user_manager.id],
                "domain_force": [("share", "=", True)],
                "perm_write": True,
            }
        )

        # Users
        portal_user_manager = self.env["res.users"].create(
            {
                "name": "Portal User Manager",
                "login": "maintainer",
                "password": "password",
                "group_ids": [
                    group_user.id,
                    group_partner_manager.id,
                    group_portal_user_manager.id,
                ],
            }
        )
        user = self.env["res.users"].create(
            {
                "name": "User",
                "login": "user_",
                "password": "password",
                "group_ids": [group_user.id, group_partner_manager.id],
            }
        )
        portal = self.env["res.users"].create(
            {
                "name": "Portal",
                "login": "portal_",
                "password": "password",
                "group_ids": [group_portal.id],
            }
        )

        # A UPM cannot update the user profile of another USER
        with self.assertRaises(AccessError):
            user.with_user(portal_user_manager).write({"name": "New name for you"})
        # A UPM can update the user profile of a PORTAL user
        portal.with_user(portal_user_manager).write({"name": "New name for you"})

        # A UPM cannot update the partner profile of another USER
        with self.assertRaises(AccessError):
            user.partner_id.with_user(portal_user_manager).write(
                {"name": "New name for you"}
            )
        # A UPM can update the partner profile of a PORTAL user
        portal.partner_id.with_user(portal_user_manager).write(
            {"name": "New name for you"}
        )

        # A USER cannot update the user profile of another USER
        with self.assertRaises(AccessError):
            self.user_internal.with_user(user).write({"name": "New name for you"})
        # A USER cannot update the user profile of a PORTAL user
        with self.assertRaises(AccessError):
            portal.with_user(user).write({"name": "New name for you"})

        # A USER cannot update the partner profile of another USER
        with self.assertRaises(AccessError):
            self.user_internal.partner_id.with_user(user).write(
                {"name": "New name for you"}
            )
        # A USER can update the partner profile of a PORTAL user
        portal.partner_id.with_user(user).write({"name": "New name for you"})


class TestEmptyPassword(TransactionCase):
    """Setting an empty password must store SQL NULL (not a verifiable hash of
    the empty string) and block any login attempt, honoring the field help
    "Keep empty if you don't want the user to be able to connect". (W2)
    """

    def _stored_password(self, user):
        self.env.cr.execute("SELECT password FROM res_users WHERE id=%s", (user.id,))
        return self.env.cr.fetchone()[0]

    def _check_credentials(self, user, password):
        env = self.env(user=user)
        return env["res.users"]._check_credentials(
            {"type": "password", "login": user.login, "password": password},
            {"interactive": True},
        )

    def test_empty_password_stores_null_and_blocks_login(self):
        user = new_test_user(self.env, "nopwd_user", password="Secret!Pwd123")
        # Sanity: a set password stores a (non-plaintext) hash and verifies.
        self.assertTrue(self._stored_password(user))
        self.assertEqual(
            self._check_credentials(user, "Secret!Pwd123")["auth_method"],
            "password",
        )

        user.password = ""

        self.assertIsNone(
            self._stored_password(user),
            "An empty password must be stored as SQL NULL.",
        )
        # Login fails cleanly: the old password, the empty string, and a
        # string matching the stored value (NULL reads back as '') all raise.
        for attempt in ("Secret!Pwd123", "", " "):
            with self.assertRaises(AccessDenied):
                self._check_credentials(user, attempt)

    def test_reset_after_empty_password(self):
        """A password set again after being emptied works normally."""
        user = new_test_user(self.env, "repwd_user", password="Secret!Pwd123")
        user.password = ""
        self.assertIsNone(self._stored_password(user))
        user.password = "New!Secret456"
        self.assertTrue(self._stored_password(user))
        self.assertEqual(
            self._check_credentials(user, "New!Secret456")["auth_method"],
            "password",
        )


class TestUsersTweaks(TransactionCase):
    def test_superuser(self):
        """The superuser is inactive and must remain as such."""
        user = self.env["res.users"].browse(SUPERUSER_ID)
        self.assertFalse(user.active)
        with self.assertRaises(UserError):
            user.write({"active": True})


@tagged("post_install", "-at_install")
class TestUsersIdentitycheck(HttpCase):
    @users("admin")
    def test_revoke_all_devices(self):
        """Revoking all devices (via a password re-entry) invalidates other sessions."""
        # 8-char password required for security.
        self.env.user.password = "admin@odoo"

        # First session: kept, and used to revoke the others.
        session = self.authenticate(
            "admin", "admin@odoo", session_extra={"_trace_disable": False}
        )

        # Second session: expected to be revoked.
        self.authenticate(
            "admin", "admin@odoo", session_extra={"_trace_disable": False}
        )
        # Valid session -> not redirected from /web to /web/login.
        self.assertTrue(self.url_open("/web").url.endswith("/web"))

        # @check_identity needs a request; push the first session (the one kept).
        _request_stack.push(SimpleNamespace(session=session, env=self.env))
        self.addCleanup(_request_stack.pop)
        action = self.env.user.action_revoke_all_devices()
        form = Form(
            self.env[action["res_model"]].browse(action["res_id"]),
            action.get("view_id"),
        )
        form.password = "admin@odoo"
        # save() then run_check() = clicking "Log out from all devices".
        user_identity_check = form.save()
        action = user_identity_check.with_context(password=form.password).run_check()

        # Invalid session -> redirected from /web to /web/login.
        self.assertTrue(
            self.url_open("/web").url.endswith("/web/login?redirect=%2Fweb%3F")
        )

        # The wizard must also have blanked the password.
        self.assertFalse(user_identity_check.password)


@tagged("post_install", "-at_install")
class TestContextGetPartnerInvalidation(TransactionCase):
    """RU-L01: context_get (a uid-keyed ormcache reading lang/tz, which live on
    res.partner via _inherits) must be invalidated when lang/tz is written directly
    on the partner, bypassing res.users.write's own invalidation.
    """

    def test_partner_lang_write_invalidates_context_get(self):
        self.env["res.lang"].with_context(active_test=False).search(
            [("code", "in", ["fr_FR", "en_US"])]
        ).write({"active": True})
        self.addCleanup(self.env.registry.clear_cache)

        user = new_test_user(self.env, "rul01_lang_user", lang="en_US")
        user = user.with_user(user)
        self.assertEqual(user.context_get()["lang"], "en_US")

        # Direct partner write bypasses res.users.write; only the partner-side
        # invalidation can catch it.
        user.partner_id.sudo().write({"lang": "fr_FR"})

        self.assertEqual(
            user.context_get()["lang"],
            "fr_FR",
            "context_get cache was not invalidated by a direct partner lang write",
        )


@tagged("post_install", "-at_install")
class TestLoginCooldown(TransactionCase):
    """Brute-force login cooldown (RU-T01).

    _assert_can_auth records failures per source IP and, after
    base.login_cooldown_after failures within base.login_cooldown_duration, refuses
    further attempts at context-manager entry. A success resets the counter,
    cooldown_after=0 disables the feature, and with no request the guard is a no-op.
    """

    _REQUEST = "odoo.addons.base.models.res_users.request"

    def setUp(self):
        super().setUp()
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("base.login_cooldown_after", "2")
        icp.set_param("base.login_cooldown_duration", "60")
        # _login_failures lives on the registry singleton (not rolled back with the
        # transaction); drop it so tests don't leak into each other.
        self.addCleanup(self.env.registry.__dict__.pop, "_login_failures", None)

    @staticmethod
    def _request(addr):
        return SimpleNamespace(httprequest=SimpleNamespace(remote_addr=addr))

    def _fail_once(self, users):
        with self.assertRaises(AccessDenied), users._assert_can_auth(user=self.env.uid):
            raise AccessDenied

    @mute_logger("odoo.addons.base.models.res_users")
    def test_cooldown_after_threshold(self):
        users = self.env["res.users"]
        with patch(self._REQUEST, self._request("8.8.8.8")):
            self._fail_once(users)  # failures = 1
            self._fail_once(users)  # failures = 2 (== threshold)
            # now on cooldown: entry raises even with a clean body
            with (
                self.assertRaises(AccessDenied),
                users._assert_can_auth(user=self.env.uid),
            ):
                pass

    def test_success_resets_counter(self):
        users = self.env["res.users"]
        with patch(self._REQUEST, self._request("8.8.4.4")):
            self._fail_once(users)  # failures = 1 (below threshold)
            with users._assert_can_auth(user=self.env.uid):  # success pops the counter
                pass
            self._fail_once(users)  # back to failures = 1, still below threshold
            with users._assert_can_auth(user=self.env.uid):  # not on cooldown
                pass

    def test_disabled_when_cooldown_after_zero(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "base.login_cooldown_after", "0"
        )
        users = self.env["res.users"]
        with patch(self._REQUEST, self._request("1.1.1.1")):
            for _ in range(5):
                self._fail_once(users)
            with users._assert_can_auth(user=self.env.uid):  # cooldown disabled
                pass

    def test_no_request_is_noop(self):
        users = self.env["res.users"]
        with patch(self._REQUEST, None):
            with users._assert_can_auth(user=self.env.uid):
                pass

    @mute_logger("odoo.addons.base.models.res_users")
    def test_cooldown_with_non_numeric_login(self):
        # NEW-2: a cooldown for a non-numeric login (e.g. an email) must raise
        # AccessDenied, not ValueError from the i18n uid frame-walker
        # (_get_uid does int(frame_local 'user') when rendering the _() message).
        users = self.env["res.users"]
        login = "bob@example.com"
        with patch(self._REQUEST, self._request("9.9.9.9")):
            for _ in range(2):
                with (
                    self.assertRaises(AccessDenied),
                    users._assert_can_auth(user=login),
                ):
                    raise AccessDenied
            with (
                self.assertRaises(AccessDenied),
                users._assert_can_auth(user=login),
            ):
                pass

    @mute_logger("odoo.addons.base.models.res_users")
    def test_stale_failure_entries_are_pruned(self):
        """RU-M4: entries are only popped on a successful login from the same source,
        so one-shot scanning IPs accumulate forever. Once the map grows past
        LOGIN_FAILURES_PRUNE_THRESHOLD, recording a failure must drop entries older
        than the cooldown window and keep the fresh ones.
        """
        users = self.env["res.users"]
        with patch(self._REQUEST, self._request("203.0.113.7")):
            self._fail_once(users)  # seed the registry map with a fresh entry
        failures_map = self.env.registry._login_failures

        now = datetime.now(UTC)
        stale = now - timedelta(seconds=120)  # cooldown_duration is 60 (setUp)
        stale_sources = [f"198.51.100.{i}" for i in range(4)]
        for source in stale_sources:
            failures_map[source] = (3, stale)
        fresh_source = "198.51.100.200"
        failures_map[fresh_source] = (1, now)

        with (
            patch(
                "odoo.addons.base.models.res_users.LOGIN_FAILURES_PRUNE_THRESHOLD",
                3,
            ),
            patch(self._REQUEST, self._request("203.0.113.8")),
        ):
            self._fail_once(users)  # map size > threshold -> prune stale

        for source in stale_sources:
            self.assertNotIn(source, failures_map, "stale entry must be pruned")
        self.assertIn(fresh_source, failures_map, "in-window entry must survive")
        self.assertIn("203.0.113.7", failures_map)
        self.assertIn(
            "203.0.113.8", failures_map, "the just-failed source must be recorded"
        )


@tagged("post_install", "-at_install")
class TestResUsersInitPasswordMigration(TransactionCase):
    """res.users.init plaintext-password migration (RU-L09).

    init() hashes any plaintext password and must invalidate the cached `password`
    for EVERY migrated user, not just the last (the bug: a `uid` loop variable leaked
    from a comprehension that browsed only the last migrated row).
    """

    def test_init_invalidates_all_migrated_passwords(self):
        User = self.env["res.users"]
        password_field = User._fields["password"]
        user_a = new_test_user(self.env, login="rul09_a")
        user_b = new_test_user(self.env, login="rul09_b")

        # Plant plaintext passwords directly in the DB (bypassing ORM hashing) so
        # init() treats them as not-yet-MCF and migrates them.
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_users SET password=%s WHERE id = ANY(%s)",
            ("plaintext-secret", [user_a.id, user_b.id]),
        )
        # Warm the ORM cache so BOTH users hold a cached `password` entry init() must
        # invalidate. `password` is blanked on read, so assert on cache *presence*
        # (env.cache.contains), not value; invalidate first to force a re-fetch.
        (user_a + user_b).invalidate_recordset(["password"])
        _ = user_a.sudo().password
        _ = user_b.sudo().password
        self.assertTrue(self.env.cache.contains(user_a, password_field))
        self.assertTrue(self.env.cache.contains(user_b, password_field))

        User.init()

        # RU-L09: the old code leaked the comprehension variable, evicting only
        # user_b's cache and leaving user_a's stale.
        self.assertFalse(
            self.env.cache.contains(user_a, password_field),
            "init() must invalidate every migrated user's cached password (RU-L09)",
        )
        self.assertFalse(self.env.cache.contains(user_b, password_field))

        # And both stored hashes are now real MCF hashes that verify the secret.
        ctx = User._crypt_context()
        self.env.cr.execute(
            "SELECT password FROM res_users WHERE id = ANY(%s)",
            ([user_a.id, user_b.id],),
        )
        for (stored,) in self.env.cr.fetchall():
            self.assertTrue(stored.startswith("$"), "stored hash must be MCF")
            self.assertTrue(ctx.verify("plaintext-secret", stored))


@tagged("post_install", "-at_install")
class TestCheckUidPasswdCacheContract(TransactionCase):
    """_check_uid_passwd_cached invalidation contract (RU-T3).

    The cache is keyed on (uid, sha256(passwd)) and only memoises successes:
      - an ORM password change MUST invalidate the cache (old password stops
        authenticating);
      - a raw-SQL change WITHOUT registry.clear_cache() leaves it stale (old
        password keeps authenticating) -- hence raw-SQL mutations must clear it.
    """

    def setUp(self):
        super().setUp()
        # The ormcache lives on the registry singleton (not rolled back with the
        # transaction); clear it so a stale entry can't leak across tests.
        self.addCleanup(self.env.registry.clear_cache)
        self.env.registry.clear_cache()

    def test_orm_password_change_invalidates_cache(self):
        Users = self.env["res.users"]
        user = new_test_user(self.env, login="rut3_orm", password="old-password")

        # Warm the cache: old password is valid -> memoised.
        Users._check_uid_passwd(user.id, "old-password")

        # ORM write carries `password` in vals -> registry.clear_cache().
        user.password = "new-password"

        # Old password must no longer authenticate (cache was invalidated).
        with self.assertRaises(AccessDenied):
            Users._check_uid_passwd(user.id, "old-password")
        # And the new password works.
        Users._check_uid_passwd(user.id, "new-password")

    def test_raw_sql_change_without_clear_keeps_cache_stale(self):
        Users = self.env["res.users"]
        user = new_test_user(self.env, login="rut3_rawsql", password="old-password")

        # Warm the cache with the old password.
        Users._check_uid_passwd(user.id, "old-password")

        # Mutate the hash directly in the DB WITHOUT clearing the cache.
        new_hash = Users._crypt_context().hash("new-password")
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_users SET password=%s WHERE id=%s", (new_hash, user.id)
        )
        self.env.invalidate_all()  # ORM record cache, NOT the ormcache

        # Documented contract: the (uid, sha256('old-password')) ormcache entry
        # survives, so the OLD password still authenticates from cache.
        Users._check_uid_passwd(user.id, "old-password")
        # Clearing the registry cache restores correctness.
        self.env.registry.clear_cache()
        with self.assertRaises(AccessDenied):
            Users._check_uid_passwd(user.id, "old-password")


@tagged("post_install", "-at_install")
class TestSelfWriteCompanyGuard(UsersCommonCase):
    """Self-write company_id range guard (RU-T4).

    res.users.write silently drops a self-written company_id outside the user's own
    company_ids (not an error), and applies one that is a member.
    """

    def test_self_write_company_id_non_member_is_dropped(self):
        user = new_test_user(self.env, login="rut4_company", groups="base.group_user")
        other_company = self.env["res.company"].create({"name": "RU-T4 Other Co"})
        self.assertNotIn(other_company.id, user.company_ids.ids)
        original_company = user.company_id

        me = user.with_user(user)
        # Non-member company_id is dropped; vals becomes empty so write
        # short-circuits (RU-C2) and the company is unchanged.
        self.assertTrue(me.write({"company_id": other_company.id}))
        self.assertEqual(
            user.company_id,
            original_company,
            "a self-written company_id outside company_ids must be dropped, "
            "not applied (RU-T4)",
        )

    def test_self_write_company_id_member_is_applied(self):
        company_b = self.env["res.company"].create({"name": "RU-T4 Co B"})
        user = new_test_user(self.env, login="rut4_member", groups="base.group_user")
        user.sudo().write({"company_ids": [Command.link(company_b.id)]})
        self.assertIn(company_b.id, user.company_ids.ids)

        me = user.with_user(user)
        me.write({"company_id": company_b.id})
        self.assertEqual(
            user.company_id,
            company_b,
            "a self-written company_id that IS a member company must be applied",
        )


@tagged("post_install", "-at_install")
class TestAtLeastOneAdministrator(TransactionCase):
    """The at-least-one-administrator constraint must count *effective*
    administrators — users holding base.group_system through an implying
    group — not only direct members of base.group_system (audit RU-M3).
    """

    def test_admin_via_implying_group_only(self):
        group_system = self.env.ref("base.group_system")
        implying_group = self.env["res.groups"].create(
            {
                "name": "RU-M3 Implied Admins",
                "implied_ids": [Command.link(group_system.id)],
            }
        )
        indirect_admin = self.env["res.users"].create(
            {
                "name": "RU-M3 Indirect Admin",
                "login": "ru_m3_indirect_admin",
                "group_ids": [Command.set(implying_group.ids)],
            }
        )
        self.assertNotIn(group_system, indirect_admin.group_ids)
        self.assertIn(group_system, indirect_admin.all_group_ids)

        # Strip DIRECT group_system membership from every direct member. The
        # pre-RU-M3 constraint only looked at group_system.user_ids and raised a
        # spurious ValidationError, ignoring the still-effective indirect_admin.
        direct_admins = group_system.user_ids
        self.assertTrue(direct_admins, "the test DB must have a direct admin")
        direct_admins.write({"group_ids": [Command.unlink(group_system.id)]})

        self.assertFalse(group_system.user_ids, "no direct member must remain")
        self.assertTrue(
            self.env["res.users"].search_count(
                [
                    ("all_group_ids", "in", group_system.ids),
                    ("active", "=", True),
                ],
                limit=1,
            ),
            "the implied-only admin must still be an effective administrator",
        )


@tagged("post_install", "-at_install")
class TestDeviceLogGC(TransactionCase):
    """Keep-semantics of res.device.log._gc_device_log (audit RDEV-P3).

    The GC keeps exactly one row per device group (session_identifier,
    platform, browser, ip_address) — the greatest (last_activity, id), the
    same tie-break as the res.device view — and groups NULL platform/browser
    together, as the previous IS NOT DISTINCT FROM self-join did.
    """

    def _log(self, **vals):
        base = {
            "session_identifier": "sid_rdev_p3_a",
            "platform": "linux",
            "browser": "firefox",
            "ip_address": "127.0.0.1",
            "user_id": self.env.uid,
            "first_activity": "2026-07-01 10:00:00",
            "last_activity": "2026-07-01 10:00:00",
        }
        base.update(vals)
        return self.env["res.device.log"].create(base)

    def test_gc_keeps_latest_log_per_device(self):
        DeviceLog = self.env["res.device.log"]

        # Group A: three logs, distinct last_activity -> keep the newest.
        self._log(last_activity="2026-07-01 10:00:00")
        self._log(last_activity="2026-07-01 11:00:00")
        keep_a = self._log(last_activity="2026-07-01 12:00:00")

        # Group B: same session, NULL platform/browser must group together
        # (PARTITION BY, like the old IS NOT DISTINCT FROM joins) -> keep the
        # newest of the two NULL-device rows, independently of group A.
        self._log(platform=False, browser=False, last_activity="2026-07-01 10:00:00")
        keep_b = self._log(
            platform=False, browser=False, last_activity="2026-07-01 11:00:00"
        )

        # Group C: tie on last_activity -> keep exactly one, the highest id
        # (view-aligned tie-break; the pre-RDEV-P3 query kept every tied row).
        self._log(
            session_identifier="sid_rdev_p3_c", last_activity="2026-07-01 09:00:00"
        )
        keep_c = self._log(
            session_identifier="sid_rdev_p3_c", last_activity="2026-07-01 09:00:00"
        )

        # Group D: a lone (old) log is its group's latest -> always kept.
        keep_d = self._log(
            session_identifier="sid_rdev_p3_d",
            ip_address="10.0.0.8",
            last_activity="2020-01-01 00:00:00",
        )

        self.env.flush_all()
        DeviceLog._gc_device_log()
        self.env.invalidate_all()

        survivors = DeviceLog.search(
            [
                (
                    "session_identifier",
                    "in",
                    ["sid_rdev_p3_a", "sid_rdev_p3_c", "sid_rdev_p3_d"],
                )
            ],
            order="id",
        )
        self.assertEqual(survivors, keep_a | keep_b | keep_c | keep_d)


class TestAccessesCount(UsersCommonCase):
    """accesses_count / rules_count computed via search_count (RU-P5).

    The compute must not materialize every reachable ir.model.access /
    ir.rule record into the ORM cache; the counts must keep matching the
    x2many reads they replaced, which filter archived ACLs/rules at access
    time under the caller's active_test (RelationalMulti._make_corecords).
    """

    def test_counts_match_relational_reads(self):
        user = self.user_internal
        groups = user.all_group_ids
        self.assertEqual(user.groups_count, len(groups))
        self.assertEqual(user.accesses_count, len(groups.model_access))
        self.assertEqual(user.rules_count, len(groups.rule_groups))
        self.assertGreater(user.accesses_count, 0)
        self.assertGreater(user.rules_count, 0)

    def test_counts_follow_active_test_like_the_relational_reads(self):
        group = self.env["res.groups"].create({"name": "accesses count group"})
        model_partner = self.env.ref("base.model_res_partner")
        rule = self.env["ir.rule"].create(
            {
                "name": "accesses count rule",
                "model_id": model_partner.id,
                "groups": [Command.link(group.id)],
                "domain_force": "[(1, '=', 1)]",
            }
        )
        acl = self.env["ir.model.access"].create(
            {
                "name": "accesses count acl",
                "model_id": model_partner.id,
                "group_id": group.id,
                "perm_read": True,
            }
        )
        self.user_internal.write({"group_ids": [Command.link(group.id)]})
        user = self.user_internal
        groups = user.all_group_ids
        self.assertIn(acl, groups.model_access)
        self.assertIn(rule, groups.rule_groups)
        active_accesses = user.accesses_count
        active_rules = user.rules_count
        self.assertEqual(active_accesses, len(groups.model_access))
        self.assertEqual(active_rules, len(groups.rule_groups))

        # Archiving removes them from the default-context counts, exactly
        # like the x2many recordsets (filtered at access time)...
        rule.action_archive()
        acl.action_archive()
        self.env.invalidate_all()
        self.assertNotIn(acl, groups.model_access)
        self.assertNotIn(rule, groups.rule_groups)
        self.assertEqual(user.accesses_count, active_accesses - 1)
        self.assertEqual(user.rules_count, active_rules - 1)
        self.assertEqual(user.accesses_count, len(groups.model_access))
        self.assertEqual(user.rules_count, len(groups.rule_groups))

        # ... while an active_test=False context keeps seeing them, as the
        # relational reads did (invalidate first: the non-stored integer
        # cache is context-independent, for the old compute too).
        self.env.invalidate_all()
        user_no_active_test = user.with_context(active_test=False)
        groups_no_active_test = user_no_active_test.all_group_ids
        self.assertIn(acl, groups_no_active_test.model_access)
        self.assertIn(rule, groups_no_active_test.rule_groups)
        self.assertEqual(
            user_no_active_test.accesses_count,
            len(groups_no_active_test.model_access),
        )
        self.assertEqual(
            user_no_active_test.rules_count,
            len(groups_no_active_test.rule_groups),
        )


class TestWriteCacheInvalidation(UsersCommonCase):
    """Cache invalidation contract of res.users.write (RU-P6).

    A group_ids write clears the "stable" cache group, whose cascade already
    covers the "default" group; the invalidation-fields branch is skipped in
    that case (no double clear). These tests pin that the cascade keeps
    invalidating the default-cached per-uid context — with and without
    group_ids in the same write.
    """

    def _user_context_lang(self, user):
        return self.env["res.users"].with_user(user).context_get()["lang"]

    def test_lang_only_write_invalidates_context_cache(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        user = self.user_internal
        self.assertEqual(self._user_context_lang(user), "en_US")  # prime cache
        user.write({"lang": "fr_FR"})
        self.assertEqual(self._user_context_lang(user), "fr_FR")

    def test_combined_group_and_lang_write_invalidates_context_cache(self):
        # group_ids takes the call_cache_clearing_methods() branch; the lang
        # invalidation must still happen through the stable->default cascade.
        self.env["res.lang"]._activate_lang("fr_FR")
        user = self.user_internal
        self.assertEqual(self._user_context_lang(user), "en_US")  # prime cache
        group = self.env["res.groups"].create({"name": "cache inval group"})
        user.write({"group_ids": [Command.link(group.id)], "lang": "fr_FR"})
        self.assertEqual(self._user_context_lang(user), "fr_FR")
        self.assertIn(group, user.all_group_ids)


class TestInstalledLangCodes(TransactionCase):
    """Memoised installed-language codes used by context_get (RU-P7)."""

    def test_codes_match_get_installed_and_track_activation(self):
        Users = self.env["res.users"]
        codes = Users._get_installed_lang_codes()
        self.assertIsInstance(codes, frozenset)
        self.assertIn("en_US", codes)
        self.assertEqual(
            codes,
            frozenset(code for code, _name in self.env["res.lang"].get_installed()),
        )
        if "fr_FR" in codes:
            self.skipTest("fr_FR already installed; cannot test invalidation")
        # activating a language must invalidate the memoised set
        self.env["res.lang"]._activate_lang("fr_FR")
        self.assertIn("fr_FR", Users._get_installed_lang_codes())


class TestDeviceIdentityAlignment(TransactionCase):
    """GC / res.device view shared device identity (audit RDEV-P4).

    Both the view de-dup and the GC derive their grouping from
    _DEVICE_IDENTITY_COLUMNS; the GC additionally keeps one row per
    ip_address so linked_ip_addresses retains the IP history of rows the
    view hides.
    """

    def _log(self, **vals):
        base = {
            "session_identifier": "sid_rdev_p4",
            "platform": "linux",
            "browser": "firefox",
            "ip_address": "10.0.0.1",
            "user_id": self.env.uid,
            "first_activity": "2026-07-01 10:00:00",
            "last_activity": "2026-07-01 10:00:00",
        }
        base.update(vals)
        return self.env["res.device.log"].create(base)

    def test_view_identity_derives_from_constant(self):
        from odoo.addons.base.models.res_device import _DEVICE_IDENTITY_COLUMNS

        where = self.env["res.device"]._where()
        for column, _nullable in _DEVICE_IDENTITY_COLUMNS:
            self.assertIn(f"D2.{column}", where)
        # ip_address is deliberately NOT part of the view identity
        self.assertNotIn("ip_address", where)

    def test_gc_keeps_ip_history_view_shows_latest(self):
        old_ip = self._log(last_activity="2026-07-01 10:00:00")
        new_ip = self._log(ip_address="10.0.0.2", last_activity="2026-07-01 11:00:00")
        self.env.flush_all()
        devices = (
            self.env["res.device"]
            .sudo()
            .search([("session_identifier", "=", "sid_rdev_p4")])
        )
        self.assertEqual(devices.ids, [new_ip.id], "view shows only the latest row")
        self.env["res.device.log"]._gc_device_log()
        survivors = self.env["res.device.log"].search(
            [("session_identifier", "=", "sid_rdev_p4")]
        )
        self.assertEqual(
            survivors,
            old_ip | new_ip,
            "GC keeps one row per IP for linked_ip_addresses history",
        )

    def test_null_user_rows_dedup_consistently(self):
        # NULL user_id groups together in both queries: the view shows only
        # the latest NULL-user row (NULL-safe identity join) and the GC
        # deletes the very rows the view hides — no invisible immortal rows.
        old = self._log(user_id=False, last_activity="2026-07-01 10:00:00")
        newest = self._log(user_id=False, last_activity="2026-07-01 11:00:00")
        self.env.flush_all()
        devices = (
            self.env["res.device"]
            .sudo()
            .search([("session_identifier", "=", "sid_rdev_p4")])
        )
        self.assertEqual(devices.ids, [newest.id])
        self.env["res.device.log"]._gc_device_log()
        survivors = self.env["res.device.log"].search(
            [("session_identifier", "=", "sid_rdev_p4")]
        )
        self.assertEqual(survivors, newest, f"GC must delete hidden row {old.id}")
