from odoo.exceptions import AccessError

from odoo.addons.mail.tests.common import MailCommon, mail_new_test_user


class TestSubtypeAccess(MailCommon):
    def test_subtype_access(self):
        """
        The function aims to formally verify the access restrictions on mail.message.subtype for
        normal and admin users. It ensures that normal users are unable to modify it,
        while admin users possess the necessary privileges to modify it successfully.
        """

        test_subtype = self.env["mail.message.subtype"].create(
            {
                "name": "Test",
                "description": "only description",
            }
        )

        user = mail_new_test_user(self.env, "Internal user", groups="base.group_user")

        with self.assertRaises(AccessError):
            test_subtype.with_user(user).write({"description": "changing description"})

        test_subtype.with_user(self.user_admin).write({"description": "testing"})
        self.assertEqual(test_subtype.description, "testing")


class TestSubtypeCache(MailCommon):
    def test_a_subtype_write_invalidates_only_the_subtype_caches(self):
        Subtype = self.env["mail.message.subtype"]
        lrus = self.env.registry.ormcache_lrus
        default_generation = lrus["default"].generation
        Subtype._get_auto_subscription_subtypes("mail.test.simple")
        Subtype.default_subtypes("mail.test.simple")
        subtype_generation = lrus["mail"].generation

        Subtype.create(
            {"name": "Cache probe", "res_model": "mail.test.simple", "default": True}
        )

        self.assertGreater(
            lrus["mail"].generation,
            subtype_generation,
            "the subtype caches are dropped by the write",
        )
        self.assertEqual(
            lrus["default"].generation,
            default_generation,
            "the default caches (fields, ACLs, xmlids) survive a subtype write",
        )
        self.assertIn(
            "Cache probe",
            Subtype.default_subtypes("mail.test.simple")[0].mapped("name"),
            "the new subtype is served, not the cached answer",
        )

    def test_a_bare_clear_cache_still_drops_the_subtype_caches(self):
        Subtype = self.env["mail.message.subtype"]
        lrus = self.env.registry.ormcache_lrus
        Subtype._get_auto_subscription_subtypes("mail.test.simple")
        generation = lrus["mail"].generation
        self.env.registry.clear_cache()
        self.assertGreater(lrus["mail"].generation, generation)
