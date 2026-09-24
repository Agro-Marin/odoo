from datetime import timedelta
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command, Domain
from odoo.modules.module import get_module_path, load_script
from odoo.tests import TransactionCase, new_test_user, tagged


class GrantCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Grant = cls.env["res.users.grant"]
        cls.group_user = cls.env.ref("base.group_user")
        cls.group_partner_manager = cls.env.ref("base.group_partner_manager")
        cls.group_system = cls.env.ref("base.group_system")
        cls.user = new_test_user(cls.env, login="grantee", groups="base.group_user")
        cls.other = new_test_user(cls.env, login="bystander", groups="base.group_user")

    def live(self, user, group):
        return self.Grant.search(
            self.Grant._live_domain()
            & Domain("user_id", "=", user.id)
            & Domain("group_id", "=", group.id)
        )

    def at(self, moment):
        return patch.object(type(self.env.cr), "now", lambda cr: moment)


@tagged("post_install", "-at_install")
class TestGrantProjection(GrantCase):
    def test_a_created_user_holds_a_grant_per_group(self):
        grant = self.live(self.user, self.group_user)
        self.assertEqual(len(grant), 1)
        self.assertEqual(grant.state, "active")
        self.assertEqual(grant.cause, "manual")
        self.assertEqual(grant.granted_by_id, self.env.user)

    def test_a_user_holds_the_groups_it_is_created_with(self):
        # the groups a user holds are read from its grants, which its create
        # makes after the row: whatever read the groups while the row was
        # being created must not stand as the answer
        Users = self.env["res.users"]
        follow = type(self.Grant)._follow_membership

        def read_groups_first(grants, added, removed, fresh_user_ids=()):
            # a computed field or an override reading the new user's groups
            # before its grants exist, as approval's do
            for user_id in fresh_user_ids:
                Users.browse(user_id)._get_group_ids()
            return follow(grants, added, removed, fresh_user_ids)

        with patch.object(type(self.Grant), "_follow_membership", read_groups_first):
            user = Users.create(
                {
                    "name": "Created with groups",
                    "login": "created_with_groups",
                    "group_ids": [
                        Command.link(self.group_user.id),
                        Command.link(self.group_partner_manager.id),
                    ],
                }
            )
        self.assertTrue(user.has_group("base.group_partner_manager"))
        self.assertTrue(user.has_group("base.group_user"))
        self.assertTrue(user.has_group("base.group_everyone"), "an implied group")
        self.assertTrue(user.with_user(user).env["res.partner"].has_access("create"))

    def test_linking_a_group_grants_it_and_unlinking_revokes_it(self):
        self.user.group_ids = [Command.link(self.group_partner_manager.id)]
        grant = self.live(self.user, self.group_partner_manager)
        self.assertEqual(len(grant), 1)
        self.assertTrue(self.user.has_group("base.group_partner_manager"))
        log = self.env["ir.access.log"].search(
            [("grant_id", "=", grant.id), ("event", "=", "grant_created")]
        )
        self.assertEqual(log.actor_id, self.env.user)

        self.user.group_ids = [Command.unlink(self.group_partner_manager.id)]
        self.assertEqual(grant.state, "revoked")
        self.assertFalse(self.live(self.user, self.group_partner_manager))
        self.assertFalse(self.user.has_group("base.group_partner_manager"))
        self.assertTrue(
            self.env["ir.access.log"].search_count(
                [("grant_id", "=", grant.id), ("event", "=", "grant_revoked")]
            )
        )

    def test_the_group_side_writes_through_too(self):
        self.group_partner_manager.user_ids = [Command.link(self.user.id)]
        self.assertEqual(len(self.live(self.user, self.group_partner_manager)), 1)
        self.group_partner_manager.user_ids = [Command.unlink(self.user.id)]
        self.assertFalse(self.live(self.user, self.group_partner_manager))

    def test_a_grant_projects_into_group_ids_and_its_revocation_out(self):
        grant = self.Grant._grant(
            self.user, self.group_partner_manager, cause="automation"
        )
        self.assertIn(self.group_partner_manager, self.user.group_ids)
        self.assertEqual(grant.cause, "automation")
        self.assertEqual(
            self.Grant._grant(
                self.user, self.group_partner_manager, cause="automation"
            ),
            self.Grant,
            "a second grant of a group already held is not made",
        )
        self.Grant._revoke(self.user, self.group_partner_manager)
        self.assertNotIn(self.group_partner_manager, self.user.group_ids)
        self.assertFalse(self.user.has_group("base.group_partner_manager"))

    def test_revoking_one_of_two_grants_keeps_the_membership(self):
        first = self.Grant._grant(
            self.user, self.group_partner_manager, cause="automation"
        )
        second = self.Grant.create(
            {
                "user_id": self.user.id,
                "group_id": self.group_partner_manager.id,
                "date_to": self.env.cr.now() + timedelta(days=5),
            }
        )
        first.action_revoke()
        self.assertIn(self.group_partner_manager, self.user.group_ids)
        second.action_revoke()
        self.assertNotIn(self.group_partner_manager, self.user.group_ids)

    def test_a_grant_is_ended_not_rewritten_or_deleted(self):
        grant = self.live(self.user, self.group_user)
        for vals in (
            {"state": "revoked"},
            {"user_id": self.other.id},
            {"group_id": self.group_system.id},
            {"cause": "migration"},
        ):
            with self.assertRaises(UserError):
                grant.write(vals)
        with self.assertRaises(UserError):
            grant.with_user(self.env.ref("base.user_admin")).unlink()
        grant.action_revoke("left")
        with self.assertRaises(UserError):
            grant.write({"reason": "back"})

    def test_a_cause_nothing_produces_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Grant.with_user(self.env.ref("base.user_admin")).create(
                {
                    "user_id": self.user.id,
                    "group_id": self.group_partner_manager.id,
                    "cause": "break_glass",
                }
            )


@tagged("post_install", "-at_install")
class TestGrantWindow(GrantCase):
    def test_an_ended_grant_stops_counting_at_the_second(self):
        now = self.env.cr.now()
        grant = self.Grant.create(
            {
                "user_id": self.user.id,
                "group_id": self.group_partner_manager.id,
                "date_to": now + timedelta(hours=1),
            }
        )
        self.assertTrue(self.user.has_group("base.group_partner_manager"))
        with self.at(now + timedelta(hours=2)):
            # the cached answer knows when it goes stale, before any cron ran
            self.assertEqual(grant.state, "active")
            self.assertFalse(self.user.has_group("base.group_partner_manager"))
            self.Grant._cron_cross_boundaries()
        self.assertEqual(grant.state, "expired")
        self.assertNotIn(self.group_partner_manager, self.user.group_ids)
        self.assertTrue(
            self.env["ir.access.log"].search_count(
                [("grant_id", "=", grant.id), ("event", "=", "grant_expired")]
            )
        )

    def test_a_scheduled_grant_starts_counting_at_the_second(self):
        now = self.env.cr.now()
        grant = self.Grant.create(
            {
                "user_id": self.user.id,
                "group_id": self.group_partner_manager.id,
                "date_from": now + timedelta(hours=1),
            }
        )
        self.assertEqual(grant.state, "scheduled")
        self.assertNotIn(self.group_partner_manager, self.user.group_ids)
        self.assertFalse(self.user.has_group("base.group_partner_manager"))
        with self.at(now + timedelta(hours=2)):
            self.assertTrue(self.user.has_group("base.group_partner_manager"))
            self.Grant._cron_cross_boundaries()
        self.assertEqual(grant.state, "active")
        self.assertIn(self.group_partner_manager, self.user.group_ids)

    def test_a_boundary_triggers_the_cron(self):
        cron = self.env.ref("base.ir_cron_res_users_grant_boundaries")
        moment = self.env.cr.now() + timedelta(days=3)
        self.Grant.create(
            {
                "user_id": self.user.id,
                "group_id": self.group_partner_manager.id,
                "date_to": moment,
            }
        )
        self.assertTrue(
            self.env["ir.cron.trigger"].search_count(
                [("cron_id", "=", cron.id), ("call_at", "=", moment)]
            )
        )

    def test_an_expired_grant_cannot_be_created(self):
        with self.assertRaises(ValidationError):
            self.Grant.create(
                {
                    "user_id": self.user.id,
                    "group_id": self.group_partner_manager.id,
                    "date_to": self.env.cr.now() - timedelta(hours=1),
                }
            )


@tagged("post_install", "-at_install")
class TestGrantDelegation(GrantCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = cls.env["res.groups"]
        cls.admins = groups.create({"name": "Grant probe: administrators"})
        cls.delegable = groups.create(
            {"name": "Grant probe: delegable", "admin_group_id": cls.admins.id}
        )
        cls.escalating = groups.create(
            {
                "name": "Grant probe: implies settings",
                "admin_group_id": cls.admins.id,
                "implied_ids": [Command.link(cls.group_system.id)],
            }
        )
        cls.admin = new_test_user(
            cls.env, login="delegated_admin", groups="base.group_user"
        )
        cls.admin.group_ids = [Command.link(cls.admins.id)]

    def grant_as(self, actor, user, group):
        return self.Grant.with_user(actor).create(
            {"user_id": user.id, "group_id": group.id, "reason": "probe"}
        )

    def test_a_member_of_the_admin_group_grants_and_revokes(self):
        grant = self.grant_as(self.admin, self.user, self.delegable)
        self.assertIn(self.delegable, self.user.group_ids)
        self.assertEqual(grant.granted_by_id, self.admin)
        grant.with_user(self.admin).action_revoke("done")
        self.assertEqual(grant.state, "revoked")

    def test_a_non_member_is_refused(self):
        with self.assertRaises(AccessError):
            self.grant_as(self.other, self.user, self.delegable)

    def test_nobody_grants_themselves(self):
        with self.assertRaises(AccessError):
            self.grant_as(self.admin, self.admin, self.delegable)

    def test_an_implication_the_admin_does_not_administer_is_refused(self):
        with self.assertRaises(AccessError):
            self.grant_as(self.admin, self.user, self.escalating)

    def test_a_grantee_in_other_companies_is_refused(self):
        company = self.env["res.company"].create({"name": "Grant probe company"})
        self.user.write({"company_ids": [Command.link(company.id)]})
        with self.assertRaises(AccessError):
            self.grant_as(self.admin, self.user, self.delegable)

    def test_the_grantee_cannot_extend_their_own_grant(self):
        grant = self.grant_as(self.admin, self.user, self.delegable)
        grant.date_to = self.env.cr.now() + timedelta(days=1)
        with self.assertRaises(AccessError):
            grant.with_user(self.user).write(
                {"date_to": self.env.cr.now() + timedelta(days=30)}
            )


@tagged("post_install", "-at_install")
class TestAccessLog(GrantCase):
    def test_the_log_is_append_only_and_read_by_its_subject(self):
        self.user.group_ids = [Command.link(self.group_partner_manager.id)]
        Log = self.env["ir.access.log"]
        mine = Log.with_user(self.user).search([])
        self.assertTrue(mine)
        self.assertEqual(mine.subject_user_id, self.user)
        self.assertFalse(
            Log.with_user(self.other).search([("subject_user_id", "=", self.user.id)])
        )
        with self.assertRaises(UserError):
            mine[:1].write({"reason": "edited"})
        with self.assertRaises(UserError):
            mine[:1].with_user(self.env.ref("base.user_admin")).unlink()
        with self.assertRaises(AccessError):
            Log.with_user(self.user).create({"event": "grant_created"})


@tagged("post_install", "-at_install")
class TestMembershipMigration(GrantCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        path = f"{get_module_path('base')}/migrations/1.101"
        cls.pre = load_script(
            f"{path}/pre-migrate_memberships_become_grants.py",
            "base_1_101_pre_migrate_memberships_become_grants",
        )
        cls.post = load_script(
            f"{path}/post-migrate_grants_are_logged_and_administered.py",
            "base_1_101_post_migrate_grants_are_logged_and_administered",
        )

    def test_every_membership_becomes_one_grant_once(self):
        # a membership written below the ORM, as a database before 1.101 holds it
        self.env.flush_all()
        self.env.cr.execute(
            "INSERT INTO res_groups_users_rel (uid, gid) VALUES (%s, %s)",
            [self.user.id, self.group_partner_manager.id],
        )
        for _run in range(2):
            self.pre.migrate(self.env.cr, "1.100")
            self.post.migrate(self.env.cr, "1.100")
        self.env.invalidate_all()
        grant = self.live(self.user, self.group_partner_manager)
        self.assertEqual(len(grant), 1)
        self.assertEqual(grant.cause, "migration")
        self.assertEqual(len(self.live(self.user, self.group_user)), 1)
        self.assertEqual(
            self.env["ir.access.log"].search_count([("event", "=", "grant_migrated")]),
            1,
        )
