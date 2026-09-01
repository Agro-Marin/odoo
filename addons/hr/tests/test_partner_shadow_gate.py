from odoo.tests import TransactionCase, tagged

# Magic columns collide for every pair of models in the registry.
MAGIC = frozenset(
    {"id", "create_date", "create_uid", "write_date", "write_uid", "display_name"}
)

# The names hr.employee shadows on res.partner today, with what ADR-0086 says
# becomes of each. Shrinking this set is step 7; growing it is the regression
# this test exists to catch.
KEEP_SHADOWED = frozenset(
    {
        "parent_id",  # Manager, not the partner's Related Company
        "child_ids",  # subordinates, not the partner's addresses
        "user_id",  # the login account, not the partner's Salesperson
        "company_id",  # employment is company-scoped; the party is company-less
        "active",  # ending an employment must not archive the person
        # An employee's tags are not their contact's tags. ADR-0086 step 6
        # merged the two VOCABULARIES into res.partner.tag but deliberately kept
        # two ASSIGNMENTS: employee_tag_rel beside
        # res_partner_res_partner_tag_rel. The collision is newly visible rather
        # than new -- these were category_ids and category_id until the field
        # rename, so they differed by name while already differing in storage.
        # Whether they should converge is step 7's question, not the rename's.
        "tag_ids",
    }
)
SEPARATE_DESTINATION = frozenset(
    {
        "barcode",  # a Badge ID, and goes to res.partner.identifier
        "country_id",  # Nationality, not the partner's ADDRESS country
    }
)
DELEGATION_PROVIDES = frozenset(
    {"name", "tz", "lang", "phone", "email", "im_status", "color"}
)
# inherited=True today, but from hr.version -- so it satisfies a naive
# "is it inherited" check while resolving to the wrong parent.
WRONG_PARENT = frozenset({"country_code"})

# Names that shadow only once another module contributes them to res.partner.
# The gate reads the registry, so its answer is a property of the INSTALLED SET,
# not of the source: an hr-only lane cannot see a shadow account creates. Listing
# these separately keeps that limit visible rather than silent, and keeps the
# recorded set honest in a narrow lane where they genuinely do not collide.
CONDITIONAL = {
    # account adds currency_id to res.partner, computed from its pricelist or
    # company; hr.employee's own is the EMPLOYMENT currency the wage is
    # expressed in. Same name, different subject -- so keep-shadowed when both
    # are present.
    "currency_id": "account",
}

EXPECTED = (
    KEEP_SHADOWED | SEPARATE_DESTINATION | DELEGATION_PROVIDES | WRONG_PARENT
) | set(CONDITIONAL)


@tagged("post_install", "-at_install")
class TestPartnerShadowGate(TransactionCase):
    """ADR-0086: a field hr.employee declares itself is NOT delegated.

    `_add_inherited_fields` skips any name the child already declares and logs
    nothing, so once hr.employee delegates to res.partner every name in this set
    silently keeps reading the employee's own column. res.users already shipped
    that failure: it declares `active` itself and needed `active_partner` to
    reach the value delegation was meant to provide.
    """

    @classmethod
    def _shadowed(cls):
        employee = cls.env["hr.employee"]._fields
        partner = cls.env["res.partner"]._fields
        found = set()
        for name in set(employee) & set(partner):
            if name in MAGIC:
                continue
            shared = set(employee[name]._modules or ()) & set(
                partner[name]._modules or ()
            )
            if shared:
                # Both models inherit the same mixin. An employee's chatter is
                # not the contact's chatter; delegating these would be wrong.
                continue
            field = employee[name]
            if field.inherited and field.inherited_field.model_name == "res.partner":
                continue
            found.add(name)
        return found

    def test_no_field_shadows_the_partner_beyond_the_recorded_set(self):
        unexpected = self._shadowed() - EXPECTED
        self.assertFalse(
            unexpected,
            "hr.employee gained %s, which res.partner also declares. Delegation "
            "will not move it and no error will say so -- either delete it, or "
            "add it to this test with the reason it must stay shadowed."
            % sorted(unexpected),
        )

    @classmethod
    def _expected_here(cls):
        """EXPECTED, minus conditionals whose contributing module is absent."""
        installed = set(
            cls.env["ir.module.module"]
            .search([("state", "=", "installed")])
            .mapped("name")
        )
        return EXPECTED - {
            name for name, module in CONDITIONAL.items() if module not in installed
        }

    def test_the_recorded_set_has_not_silently_shrunk(self):
        """Every recorded name must still shadow, or the record is stale."""
        gone = self._expected_here() - self._shadowed()
        self.assertFalse(
            gone,
            "%s no longer shadows res.partner. If step 7 resolved it, remove it "
            "from this test in the same commit." % sorted(gone),
        )

    def test_the_recorded_set_is_complete_only_for_the_installed_modules(self):
        """The gate reads the registry, so its answer depends on what is installed.

        `currency_id` collides only once `account` is installed, because account
        is what adds it to res.partner -- an hr-only lane cannot see a shadow
        contributed by a module outside hr. Recording that here makes the limit
        a stated absence rather than a silent one: a lane narrower than this
        list under-reports, and the fix is to install more, not to trust it.
        """
        installed = set(
            self.env["ir.module.module"]
            .search([("state", "=", "installed")])
            .mapped("name")
        )
        if "account" not in installed:
            self.skipTest("account is not installed; currency_id cannot collide here")
        self.assertIn("currency_id", self._shadowed())

    def test_inherited_alone_does_not_satisfy_the_gate(self):
        """country_code is inherited=True -- from hr.version, not res.partner.

        After step 7 hr.employee carries two delegations, so the check has to
        name the parent model rather than trust the flag.
        """
        field = self.env["hr.employee"]._fields["country_code"]
        self.assertTrue(field.inherited)
        self.assertEqual(field.inherited_field.model_name, "hr.version")
        self.assertIn("country_code", self._shadowed())
