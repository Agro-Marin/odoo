from lxml import etree

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tools.misc import mute_logger

from odoo.addons.base.tests.common import TransactionCaseWithUserDemo


class TestACL(TransactionCaseWithUserDemo):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.TEST_GROUP = "base.base_test_group"
        cls.test_group = cls.env["res.groups"].create(
            {
                "name": "test with implied user",
                "implied_ids": [Command.link(cls.env.ref("base.group_user").id)],
            }
        )
        cls.env["ir.model.data"].create(
            {
                "module": "base",
                "name": "base_test_group",
                "model": "res.groups",
                "res_id": cls.test_group.id,
            }
        )

    def _set_field_groups(self, model, field_name, groups):
        field = model._fields[field_name]
        self.patch(field, "groups", groups)
        self.env.invalidate_all()
        self.env.registry.clear_cache("templates")

    def test_field_visibility_restriction(self):
        """Field-level ``groups`` restricts the field to members of the allowed groups."""
        currency = self.env["res.currency"].with_user(self.user_demo)

        # Add a view that adds a label for the field we are going to check
        primary = self.env["ir.ui.view"].create(
            {
                "name": "Add separate label for decimal_places",
                "model": "res.currency",
                "type": "form",
                "priority": 1,
                "arch": """<form>
                <group>
                    <group string="Price Accuracy">
                        <field name="rounding"/>
                        <label for="decimal_places"/>
                        <field name="decimal_places" nolabel="1"/>
                    </group>
                </group>
            </form>""",
            }
        )

        # Verify the test environment first
        original_fields = currency.fields_get([])
        form_view = currency.get_view(primary.id, "form")
        view_arch = etree.fromstring(form_view.get("arch"))
        has_group_test = self.user_demo.has_group(self.TEST_GROUP)
        self.assertFalse(
            has_group_test,
            "`demo` user should not belong to the restricted group before the test",
        )
        self.assertIn(
            "decimal_places",
            original_fields,
            "'decimal_places' field must be properly visible before the test",
        )
        self.assertNotEqual(
            view_arch.xpath("//field[@name='decimal_places'][@nolabel='1']"),
            [],
            "Field 'decimal_places' must be found in view definition before the test",
        )
        self.assertNotEqual(
            view_arch.xpath("//label[@for='decimal_places']"),
            [],
            "Label for 'decimal_places' must be found in view definition before the test",
        )

        # restrict access to the field and check it's gone
        self._set_field_groups(currency, "decimal_places", self.TEST_GROUP)

        fields = currency.fields_get([])
        form_view = currency.get_view(primary.id, "form")
        view_arch = etree.fromstring(form_view.get("arch"))
        self.assertNotIn(
            "decimal_places", fields, "'decimal_places' field should be gone"
        )
        self.assertEqual(
            view_arch.xpath("//field[@name='decimal_places']"),
            [],
            "Field 'decimal_places' must not be found in view definition",
        )
        self.assertEqual(
            view_arch.xpath("//label[@for='decimal_places']"),
            [],
            "Label for 'decimal_places' must not be found in view definition",
        )

        # Make demo user a member of the restricted group and check that the field is back
        self.test_group.user_ids += self.user_demo
        has_group_test = self.user_demo.has_group(self.TEST_GROUP)
        fields = currency.fields_get([])
        form_view = currency.get_view(primary.id, "form")
        view_arch = etree.fromstring(form_view.get("arch"))
        self.assertTrue(
            has_group_test,
            "`demo` user should now belong to the restricted group",
        )
        self.assertIn(
            "decimal_places",
            fields,
            "'decimal_places' field must be properly visible again",
        )
        self.assertNotEqual(
            view_arch.xpath("//field[@name='decimal_places']"),
            [],
            "Field 'decimal_places' must be found in view definition again",
        )
        self.assertNotEqual(
            view_arch.xpath("//label[@for='decimal_places']"),
            [],
            "Label for 'decimal_places' must be found in view definition again",
        )

    @mute_logger("odoo.models")
    def test_field_crud_restriction(self):
        """Read/Write RPC access to a restricted field must be forbidden."""
        partner = self.env["res.partner"].browse(1).with_user(self.user_demo)

        # Verify the test environment first
        has_group_test = self.user_demo.has_group(self.TEST_GROUP)
        self.assertFalse(
            has_group_test,
            "`demo` user should not belong to the restricted group",
        )
        self.assertTrue(partner.read(["bank_ids"]))
        self.assertTrue(partner.write({"bank_ids": []}))

        # Now restrict access to the field and check it's forbidden
        self._set_field_groups(partner, "bank_ids", self.TEST_GROUP)

        with self.assertRaises(AccessError):
            partner.search_fetch([], ["bank_ids"])
        with self.assertRaises(AccessError):
            partner.fetch(["bank_ids"])
        with self.assertRaises(AccessError):
            partner.read(["bank_ids"])
        with self.assertRaises(AccessError):
            partner.write({"bank_ids": []})

        # Add the restricted group, and check that it works again
        self.test_group.user_ids += self.user_demo
        has_group_test = self.user_demo.has_group(self.TEST_GROUP)
        self.assertTrue(
            has_group_test,
            "`demo` user should now belong to the restricted group",
        )
        self.assertTrue(partner.read(["bank_ids"]))
        self.assertTrue(partner.write({"bank_ids": []}))

    @mute_logger("odoo.models")
    def test_fields_browse_restriction(self):
        """Test access to records having restricted fields"""
        # Invalidate cache to avoid restricted value to be available
        # in the cache
        partner = self.env["res.partner"].with_user(self.user_demo)
        self._set_field_groups(partner, "email", self.TEST_GROUP)

        # accessing fields must not raise exceptions...
        partner = partner.search([], limit=1)
        _ = partner.name
        # ... except if they are restricted
        with self.assertRaises(AccessError):
            with mute_logger("odoo.models"):
                _ = partner.email

    def test_view_create_edit_button(self):
        """Create/Edit/Delete button visibility follows the model's access rights.

        Exercises a user with and without access in one transaction to check the
        views cache.
        """
        methods = ["create", "edit", "delete"]
        company = self.env["res.company"].with_user(self.user_demo)
        company_view = company.get_view(False, "form")
        view_arch = etree.fromstring(company_view["arch"])

        # demo not part of the group_test, create edit and delete must be False
        for method in methods:
            self.assertEqual(view_arch.get(method), "False")

        # demo part of the group_test, create edit and delete must not be specified
        company = self.env["res.company"].with_user(self.env.ref("base.user_admin"))
        company_view = company.get_view(False, "form")
        view_arch = etree.fromstring(company_view["arch"])
        for method in methods:
            self.assertIsNone(view_arch.get(method))

    def test_m2o_field_create_edit(self):
        """Many2one Create/Edit option visibility follows the relation's access rights.

        Exercises a user with and without access in one transaction to check the
        views cache.
        """
        methods = ["create", "write"]
        company = self.env["res.company"].with_user(self.user_demo)
        company_view = company.get_view(False, "form")
        view_arch = etree.fromstring(company_view["arch"])
        field_node = view_arch.xpath("//field[@name='currency_id']")
        self.assertTrue(
            len(field_node), "currency_id field should be in company from view"
        )
        for method in methods:
            self.assertEqual(field_node[0].get("can_" + method), "False")

        company = self.env["res.company"].with_user(self.env.ref("base.user_admin"))
        company_view = company.get_view(False, "form")
        view_arch = etree.fromstring(company_view["arch"])
        field_node = view_arch.xpath("//field[@name='currency_id']")
        for method in methods:
            self.assertEqual(field_node[0].get("can_" + method), "True")

    def test_get_views_fields(self):
        """``get_views`` hides group-restricted fields from demo but not from admin."""
        Partner = self.env["res.partner"]
        self._set_field_groups(Partner, "email", self.TEST_GROUP)
        views = Partner.with_user(self.user_demo).get_views([(False, "form")])
        self.assertFalse("email" in views["models"]["res.partner"]["fields"])
        self.user_demo.group_ids = [Command.link(self.test_group.id)]
        views = Partner.with_user(self.user_demo).get_views([(False, "form")])
        self.assertTrue("email" in views["models"]["res.partner"]["fields"])


class TestIrRule(TransactionCaseWithUserDemo):
    def test_ir_rule(self):
        model_res_partner = self.env.ref("base.model_res_partner")
        group_user = self.env.ref("base.group_user")

        # create an ir_rule for the Employee group with an blank domain
        rule1 = self.env["ir.rule"].create(
            {
                "name": "test_rule1",
                "model_id": model_res_partner.id,
                "domain_force": False,
                "groups": [Command.set(group_user.ids)],
            }
        )

        # read as demo user the partners (one blank domain)
        partners_demo = self.env["res.partner"].with_user(self.user_demo)
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # same with domain 1=1
        rule1.domain_force = "[(1,'=',1)]"
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # same with domain []
        rule1.domain_force = "[]"
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # create another ir_rule for the Employee group (to test multiple rules)
        rule2 = self.env["ir.rule"].create(
            {
                "name": "test_rule2",
                "model_id": model_res_partner.id,
                "domain_force": False,
                "groups": [Command.set(group_user.ids)],
            }
        )

        # read as demo user with domains [] and blank
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # same with domains 1=1 and blank
        rule1.domain_force = "[(1,'=',1)]"
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # same with domains 1=1 and 1=1
        rule2.domain_force = "[(1,'=',1)]"
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # create another ir_rule for the Employee group (to test multiple rules)
        rule3 = self.env["ir.rule"].create(
            {
                "name": "test_rule3",
                "model_id": model_res_partner.id,
                "domain_force": False,
                "groups": [Command.set(group_user.ids)],
            }
        )

        # read the partners as demo user
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # same with domains 1=1, 1=1 and 1=1
        rule3.domain_force = "[(1,'=',1)]"
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # modify the global rule on res_company which triggers a recursive check
        # of the rules on company
        global_rule = self.env.ref("base.res_company_rule_employee")
        global_rule.domain_force = "[('id','in', company_ids)]"

        # read as demo user (exercising the global company rule)
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # Modify the ir_rule for employee to have a rule that fordids seeing any
        # record. We use a domain with implicit AND operator for later tests on
        # normalization.
        rule2.domain_force = "[('id','=',False),('name','=',False)]"

        # check that demo user still sees partners, because group-rules are OR'ed
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partner.")

        # create a new group with demo user in it, and a complex rule
        group_test = self.env["res.groups"].create(
            {
                "name": "Test Group",
                "user_ids": [Command.set(self.user_demo.ids)],
            }
        )

        # add the rule to the new group, with a domain containing an implicit
        # AND operator, which is more tricky because it will have to be
        # normalized before combining it
        rule3.write(
            {
                "domain_force": "[('name','!=',False),('id','!=',False)]",
                "groups": [Command.set(group_test.ids)],
            }
        )

        # read the partners again as demo user, which should give results
        partners = partners_demo.search([])
        self.assertTrue(
            partners,
            "Demo user should see partners even with the combined rules.",
        )

        # delete global domains (to combine only group domains)
        self.env["ir.rule"].search([("groups", "=", False)]).unlink()

        # read the partners as demo user (several group domains, no global domain)
        partners = partners_demo.search([])
        self.assertTrue(partners, "Demo user should see some partners.")

    def test_ir_rule_superuser_bypass(self):
        """Pin the env.su superuser bypass: a restrictive global rule yields no
        rules and an unrestricted (TRUE) domain under sudo, but is restrictive
        for a non-superuser user. (IRU-T1)
        """
        model_res_partner = self.env.ref("base.model_res_partner")
        # restrictive *global* rule (no group) -> AND-combined with everything
        self.env["ir.rule"].create(
            {
                "name": "test_rule_su_bypass",
                "model_id": model_res_partner.id,
                "domain_force": "[('id', '=', False)]",
            }
        )

        # superuser: rules bypassed entirely
        su_rule = self.env(su=True)["ir.rule"]
        self.assertFalse(
            su_rule._get_rules("res.partner", "read"),
            "Superuser must get no record rules (env.su bypass).",
        )
        self.assertTrue(
            su_rule._compute_domain("res.partner", "read").is_true(),
            "Superuser domain must be unrestricted (Domain.TRUE).",
        )

        # non-superuser demo user: the global rule applies and is restrictive
        demo_rule = self.env(user=self.user_demo)["ir.rule"]
        self.assertTrue(
            demo_rule._get_rules("res.partner", "read"),
            "Demo user must get the global rule.",
        )
        self.assertFalse(
            demo_rule._compute_domain("res.partner", "read").is_true(),
            "Demo user domain must be restricted by the global rule.",
        )

    def test_ir_rule_get_rules_modes(self):
        """``_get_rules`` selects the rule for the requested perm mode only and
        rejects an invalid mode. (IRU-T2)
        """
        model_res_partner = self.env.ref("base.model_res_partner")
        group_user = self.env.ref("base.group_user")
        unlink_rule = self.env["ir.rule"].create(
            {
                "name": "test_rule_unlink_only",
                "model_id": model_res_partner.id,
                "domain_force": "[('id', '!=', False)]",
                "groups": [Command.set(group_user.ids)],
                "perm_read": False,
                "perm_write": False,
                "perm_create": False,
                "perm_unlink": True,
            }
        )

        demo_rule = self.env(user=self.user_demo)["ir.rule"]
        self.assertIn(
            unlink_rule,
            demo_rule._get_rules("res.partner", "unlink"),
            "Rule with only perm_unlink must appear for the 'unlink' mode.",
        )
        for mode in ("read", "write", "create"):
            self.assertNotIn(
                unlink_rule,
                demo_rule._get_rules("res.partner", mode),
                f"Unlink-only rule must not appear for the {mode!r} mode.",
            )

        with self.assertRaises(ValueError):
            demo_rule._get_rules("res.partner", "bogus")

    @mute_logger("odoo.addons.base.models.ir_rule", "odoo.models")
    def test_ir_rule_access_error_message(self):
        """Forcing a denial raises AccessError; the debug (group_no_one +
        internal) message names the blaming rule. (IRU-T3, IRU-C3)
        """
        model_res_partner = self.env.ref("base.model_res_partner")
        group_user = self.env.ref("base.group_user")

        # a real, accessible partner to deny access to
        partner = self.env["res.partner"].create({"name": "T3 partner"})

        # group rule that forbids every record for the employee group
        self.env["ir.rule"].create(
            {
                "name": "test_rule_t3_deny",
                "model_id": model_res_partner.id,
                "domain_force": "[('id', '=', False)]",
                "groups": [Command.set(group_user.ids)],
            }
        )

        partner_demo = partner.with_user(self.user_demo)
        with self.assertRaises(AccessError):
            partner_demo.check_access("read")

        # In a group_no_one debug context the message must name the rule.
        # Force the debug branch of _make_access_error by patching has_group.
        UserCls = type(self.env.user)
        original_has_group = UserCls.has_group

        def fake_has_group(user, group_ext_id):
            if group_ext_id == "base.group_no_one":
                return True
            return original_has_group(user, group_ext_id)

        rule_env = self.env(user=self.user_demo)["ir.rule"]
        self.patch(UserCls, "has_group", fake_has_group)
        exception = rule_env._make_access_error("read", partner_demo)
        self.assertIn(
            "test_rule_t3_deny",
            str(exception),
            "Debug access-error message should name the blaming rule.",
        )


class TestIrModelAccess(TransactionCaseWithUserDemo):
    def test_invalid_access_mode(self):
        """The three mode guards reject an invalid access mode. (IMA-T1)"""
        Access = self.env["ir.model.access"]
        with self.assertRaises(ValueError):
            Access._get_allowed_models("foo")
        with self.assertRaises(ValueError):
            Access.group_names_with_access("res.partner", "foo")
        with self.assertRaises(ValueError):
            Access._get_access_groups("res.partner", "foo")

    # odoo.db.cursor: the create below deliberately violates the NOT NULL
    # constraint on ir_model_access.name; without the mute the cursor's
    # "bad query" ERROR line pollutes the test log even though the test passes.
    @mute_logger("odoo.addons.base.models.ir_model_access", "odoo.db.cursor")
    def test_create_missing_name_raises_field_error(self):
        """A group-less access-granting ACL without ``name`` raises the
        required-field validation, not a KeyError from the warning. (IMA-C3)
        """
        model_partner = self.env.ref("base.model_res_partner")
        with self.assertRaises(Exception) as cm:
            self.env["ir.model.access"].create(
                [
                    {
                        "model_id": model_partner.id,
                        "group_id": False,
                        "perm_read": True,
                    }
                ]
            )
        self.assertNotIsInstance(
            cm.exception, KeyError, "Missing 'name' must not raise KeyError."
        )

    def test_create_omitted_group_warns(self):
        """An access-granting ACL that OMITS ``group_id`` is a global grant,
        exactly like an explicit falsy ``group_id``, and must warn too. (IMA-C4)
        """
        model_partner = self.env.ref("base.model_res_partner")
        with self.assertLogs(
            "odoo.addons.base.models.ir_model_access", level="WARNING"
        ) as log_cm:
            self.env["ir.model.access"].create(
                {
                    "name": "acl_no_group_omitted",
                    "model_id": model_partner.id,
                    "perm_read": True,
                }
            )
        self.assertTrue(
            any("has no group" in msg for msg in log_cm.output),
            "Omitting group_id on an access-granting ACL must warn.",
        )

    def test_cache_clearing_invalidates_both_acl_caches(self):
        """``call_cache_clearing_methods`` must evict BOTH ``_get_allowed_models``
        (in the 'default' cache bucket) and ``_get_access_groups`` (in the
        'stable' bucket). Pins the invariant that clearing 'stable' cascades to
        'default'; narrowing it would silently serve stale ACLs. (IMA-C5)
        """
        Access = self.env["ir.model.access"]
        registry = self.env.registry
        caches = registry._Registry__caches

        def cached(bucket, method_name):
            return [
                key
                for key in caches[bucket].snapshot
                if getattr(key[1], "__name__", None) == method_name
            ]

        registry.clear_all_caches()
        Access._get_allowed_models("read")
        Access._get_access_groups("res.partner", "read")
        self.assertTrue(
            cached("default", "_get_allowed_models"),
            "_get_allowed_models should populate the 'default' bucket.",
        )
        self.assertTrue(
            cached("stable", "_get_access_groups"),
            "_get_access_groups should populate the 'stable' bucket.",
        )

        Access.call_cache_clearing_methods()
        self.assertFalse(
            cached("default", "_get_allowed_models"),
            "_get_allowed_models (default bucket) must be invalidated.",
        )
        self.assertFalse(
            cached("stable", "_get_access_groups"),
            "_get_access_groups (stable bucket) must be invalidated.",
        )

    def test_allowed_models_cache_shared_across_same_group_users(self):
        """``_get_allowed_models`` is keyed on the user's group set (plus the
        mode), not on the uid: two users with identical groups must share the
        same cache entry, so per-user churn cannot evict each other's ACL
        computation. (W2)
        """
        self.addCleanup(self.env.registry.clear_cache)
        group_user = self.env.ref("base.group_user")
        user_a, user_b = self.env["res.users"].create(
            [
                {
                    "name": f"acl cache twin {letter}",
                    "login": f"acl_cache_twin_{letter}",
                    "group_ids": [Command.set(group_user.ids)],
                }
                for letter in "ab"
            ]
        )
        # Precondition of the cache key: same groups -> same (stable, hashable)
        # tuple from _get_group_ids.
        self.assertEqual(user_a._get_group_ids(), user_b._get_group_ids())
        Access = self.env["ir.model.access"]
        allowed_a = Access.with_user(user_a)._get_allowed_models("read")
        allowed_b = Access.with_user(user_b)._get_allowed_models("read")
        self.assertIs(
            allowed_a,
            allowed_b,
            "Same-group users must share one _get_allowed_models cache entry.",
        )
        # Different mode -> different entry (mode is part of the key).
        self.assertIsNot(
            allowed_a, Access.with_user(user_a)._get_allowed_models("write")
        )

    def test_check_unknown_model_warns(self):
        """``check`` on an unknown model denies, logs a WARNING, and does not
        raise when ``raise_exception=False``. (IMA-C2)
        """
        Access = self.env["ir.model.access"].with_user(self.user_demo)
        with self.assertLogs(
            "odoo.addons.base.models.ir_model_access", level="WARNING"
        ) as log_cm:
            result = Access.check("no.such.model", "read", raise_exception=False)
        self.assertFalse(result, "Access to an unknown model must be denied.")
        self.assertTrue(
            any("no.such.model" in msg for msg in log_cm.output),
            "Unknown model must be logged at WARNING.",
        )

    def test_group_names_with_access_localized_ordering(self):
        """``group_names_with_access`` orders groups alphabetically by their
        localized (translated) name, not by raw jsonb structure. (IMA-C1)
        """
        self.env["res.lang"]._activate_lang("fr_FR")
        model_partner = self.env.ref("base.model_res_partner")
        Groups = self.env["res.groups"]

        # en_US names sort as ZZZ_alpha < ZZZ_beta; fr_FR names invert that
        # order (ZZZ_zulu > ZZZ_mike) so a localized ORDER BY is observable.
        group_a = Groups.create({"name": "ZZZ_alpha"})
        group_b = Groups.create({"name": "ZZZ_beta"})
        group_a.with_context(lang="fr_FR").name = "ZZZ_zulu"
        group_b.with_context(lang="fr_FR").name = "ZZZ_mike"

        for group in (group_a, group_b):
            self.env["ir.model.access"].create(
                {
                    "name": f"acl_{group.name}",
                    "model_id": model_partner.id,
                    "group_id": group.id,
                    "perm_read": True,
                }
            )

        Access = self.env["ir.model.access"].with_context(lang="fr_FR")
        names = Access.group_names_with_access("res.partner", "read")
        ours = [n for n in names if n in ("ZZZ_zulu", "ZZZ_mike")]
        # Under fr_FR, "ZZZ_mike" < "ZZZ_zulu" -> beta's translation comes first.
        self.assertEqual(
            ours,
            ["ZZZ_mike", "ZZZ_zulu"],
            "Groups must be ordered by localized (fr_FR) name.",
        )


class TestIrExportsLineAcl(TransactionCaseWithUserDemo):
    """Audit finding IEXP-L1: ``ir.exports.line`` must be gated on
    ``base.group_allow_export`` (same as its parent ``ir.exports``), not on
    ``base.group_user``. A plain internal user without the export privilege must
    not be able to create/write/unlink export-line rows; an export-group user can.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.export_group = cls.env.ref("base.group_allow_export")
        # demo is a plain internal user; ensure it is NOT in the export group.
        cls.user_demo.write({"group_ids": [Command.unlink(cls.export_group.id)]})
        cls.user_exporter = cls.env["res.users"].create(
            {
                "name": "Exporter",
                "login": "exporter_iexp_l1",
                "group_ids": [
                    Command.link(cls.env.ref("base.group_user").id),
                    Command.link(cls.export_group.id),
                ],
            }
        )
        cls.preset = cls.env["ir.exports"].create(
            {"name": "preset", "resource": "res.partner"}
        )

    def test_non_export_user_cannot_create_line(self):
        with self.assertRaises(AccessError):
            self.env["ir.exports.line"].with_user(self.user_demo).create(
                {"name": "name", "export_id": self.preset.id}
            )

    def test_non_export_user_cannot_write_line(self):
        line = self.env["ir.exports.line"].create(
            {"name": "name", "export_id": self.preset.id}
        )
        with self.assertRaises(AccessError):
            line.with_user(self.user_demo).write({"name": "other"})

    def test_non_export_user_cannot_unlink_line(self):
        line = self.env["ir.exports.line"].create(
            {"name": "name", "export_id": self.preset.id}
        )
        with self.assertRaises(AccessError):
            line.with_user(self.user_demo).unlink()

    def test_export_user_can_crud_line(self):
        Line = self.env["ir.exports.line"].with_user(self.user_exporter)
        line = Line.create({"name": "name", "export_id": self.preset.id})
        self.assertTrue(line)
        line.write({"name": "renamed"})
        self.assertEqual(line.name, "renamed")
        line.unlink()
        self.assertFalse(line.exists())


class TestIrModelAccessUnknownModel(TransactionCaseWithUserDemo):
    """check() on a non-existent model (IMA-C5).

    A typo'd/unknown model name is a programming error: with
    raise_exception=True check() raises a clear ValueError naming the model
    instead of the generic AccessError. The lenient path is preserved for
    raise_exception=False callers (ir.ui.menu / ir.actions probe models that
    may not be loaded) and for the superuser fast-path.
    """

    def test_unknown_model_raises_clear_error(self):
        Access = self.env["ir.model.access"].with_user(self.user_demo)
        with self.assertRaises(ValueError) as capture:
            Access.check("no.such.model")
        self.assertIn("no.such.model", str(capture.exception))

    @mute_logger("odoo.addons.base.models.ir_model_access")
    def test_unknown_model_lenient_path_returns_false(self):
        Access = self.env["ir.model.access"].with_user(self.user_demo)
        self.assertFalse(Access.check("no.such.model", raise_exception=False))

    def test_unknown_model_superuser_short_circuit(self):
        # env.su returns True before any model lookup, as before
        self.assertTrue(self.env["ir.model.access"].sudo().check("no.such.model"))
