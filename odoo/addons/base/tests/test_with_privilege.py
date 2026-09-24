from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestWithPrivilege(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.privilege = cls.env["res.groups"].create(
            {"name": "Probe: create privileged industries", "is_privilege": True}
        )
        cls.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "probe_privilege_industries",
                "model": "res.groups",
                "res_id": cls.privilege.id,
            }
        )
        Access = cls.env["ir.access"]
        Access.create(
            [
                {
                    "name": "Probe privilege: create the privileged industries",
                    "model_id": cls.env["ir.model"]._get_id("res.partner.industry"),
                    "group_id": cls.privilege.id,
                    "kind": "permission",
                    "operation": "c",
                    "domain": "[('name', '=like', 'privileged%')]",
                },
                {
                    "name": "Probe privilege: read the system parameters",
                    "model_id": cls.env["ir.model"]._get_id("ir.config_parameter"),
                    "group_id": cls.privilege.id,
                    "kind": "permission",
                    "operation": "r",
                },
            ]
        )
        cls.name = "base.probe_privilege_industries"
        cls.user = new_test_user(cls.env, login="privileged", groups="base.group_user")
        cls.other = new_test_user(
            cls.env, login="unprivileged", groups="base.group_user"
        )
        cls.Industry = cls.env["res.partner.industry"].with_user(cls.user)

    def test_a_privilege_allows_what_its_rows_say_and_nothing_else(self):
        with self.assertRaises(AccessError):
            self.Industry.create({"name": "privileged before"})
        privileged = self.Industry.with_privilege(self.name, reason="probe")
        privileged.create({"name": "privileged industry"})
        with self.assertRaises(AccessError):
            privileged.create({"name": "another industry"})
        with self.assertRaises(AccessError):
            self.Industry.create({"name": "privileged after"})

    def test_sudo_keeps_it_and_another_user_does_not_get_it(self):
        privileged = self.Industry.with_privilege(self.name)
        self.assertTrue(privileged.env.privileges)
        self.assertEqual(
            privileged.sudo().sudo(False).env.privileges, privileged.env.privileges
        )
        self.assertFalse(privileged.with_user(self.other).env.privileges)
        self.assertFalse(self.Industry.env.privileges)
        self.assertIsNot(privileged.env, self.Industry.env)

    def test_only_the_holder_s_groups_include_it(self):
        env = self.Industry.with_privilege(self.name).env
        self.assertTrue(env.user.has_group(self.name))
        self.assertFalse(self.other.with_env(env).has_group(self.name))
        self.assertFalse(self.Industry.env.user.has_group(self.name))

    def test_the_read_verdict_and_the_caches_are_the_privilege_s_own(self):
        parameter = self.env["ir.config_parameter"].search([], limit=1)
        plain = parameter.with_user(self.user)
        privileged = plain.with_privilege(self.name)
        self.assertFalse(plain.has_access("read"))
        self.assertTrue(privileged.has_access("read"))
        self.assertFalse(plain.has_access("read"), "the verdict did not leak back")
        self.assertNotEqual(privileged.env._access_scope(), plain.env._access_scope())
        self.assertNotEqual(privileged.env._read_access_key, plain.env._read_access_key)
        depends_context = self.env.registry.field_depends_context
        uid_field = next(
            field
            for field in depends_context
            if "uid" in depends_context[field]
            and "access" not in depends_context[field]
        )
        self.assertNotEqual(
            privileged.env.get_cache_key(uid_field), plain.env.get_cache_key(uid_field)
        )

    def test_a_name_that_is_no_privilege_is_refused(self):
        with self.assertRaises(ValueError):
            self.Industry.with_privilege("base.group_system")
        with self.assertRaises(ValueError):
            self.Industry.with_privilege("base.no_such_privilege")

    def test_a_privilege_is_never_granted_nor_implied(self):
        with self.assertRaises(ValidationError):
            self.env["res.users.grant"].create(
                {"user_id": self.user.id, "group_id": self.privilege.id}
            )
        with self.assertRaises(ValidationError):
            self.env.ref("base.group_user").implied_ids = [
                Command.link(self.privilege.id)
            ]

    def test_a_privileged_write_on_an_audited_model_is_logged(self):
        self.privilege.audit_privilege = True
        self.Industry.with_privilege(self.name, reason="probe audit").create(
            {"name": "privileged audited"}
        )
        log = self.env["ir.access.log"].search(
            [("event", "=", "privilege_used"), ("group_id", "=", self.privilege.id)]
        )
        self.assertEqual(len(log), 1)
        self.assertEqual(log.model_name, "res.partner.industry")
        self.assertEqual(log.operation, "create")
        self.assertEqual(log.reason, "probe audit")
        self.assertEqual(log.actor_id, self.user)

    def test_the_access_error_names_no_privilege(self):
        names = self.env["ir.access"]._group_names_with_access(
            "res.partner.industry", "create"
        )
        self.assertFalse([name for name in names if "Probe" in name])
