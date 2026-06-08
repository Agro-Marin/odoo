from odoo.fields import Domain
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPropertiesBaseDefinitionAudit(TransactionCase):
    """Audit coverage for the fork-modified properties base definition lookup.

    ``res.partner`` inherits ``properties.base.definition.mixin`` and exposes a
    ``properties`` field, so it is used here as the concrete model under test.
    """

    def setUp(self):
        super().setUp()
        self.PropertiesDefinition = self.env["properties.base.definition"]

    def test_fork_raw_select_lookup_returns_existing_definition(self):
        """The fork raw-SELECT branch returns the existing definition for a field.

        ``res.partner.properties`` is a real stored field, so ``_get_ids`` finds
        its id and the lookup goes through the fork's direct
        ``SELECT id FROM properties_base_definition WHERE properties_field_id``
        path instead of the upstream ORM ``search``.
        """
        definition = self.PropertiesDefinition._get_definition_for_property_field(
            "res.partner", "properties"
        )
        self.assertTrue(definition, "A definition should be resolved or created")
        self.assertEqual(
            definition.properties_field_id.model,
            "res.partner",
            "Definition must be linked to the res.partner properties field",
        )
        self.assertEqual(
            definition.properties_field_id.name,
            "properties",
        )

        # The backing field id is known, so a second call must hit the raw
        # SELECT branch (not the create branch) and return the same record.
        field_ids = self.env["ir.model.fields"]._get_ids("res.partner")
        self.assertIn("properties", field_ids)

        definition_id = self.PropertiesDefinition._get_definition_id_for_property_field(
            "res.partner", "properties"
        )
        self.assertEqual(definition_id, definition.id)

        # Verify the raw SELECT used by the fork resolves to the same row,
        # pinning the exact query path that replaced the ORM search.
        self.env.cr.execute(
            "SELECT id FROM properties_base_definition WHERE properties_field_id = %s LIMIT 1",
            [field_ids["properties"]],
        )
        row = self.env.cr.fetchone()
        self.assertEqual(row[0], definition.id)

    def test_cache_invalidation_clears_stale_definition_id(self):
        """Clearing the stable cache forces a fresh, non-stale re-lookup.

        The lookup id is memoized on the ``stable`` ormcache group. Field
        create/unlink runs ``_setup_models__`` which clears registry caches;
        this test simulates that invalidation explicitly (deleting the live
        ``res.partner.properties`` field in a test is not safe) and asserts the
        re-lookup is consistent and never serves a dangling id.
        """
        first_id = self.PropertiesDefinition._get_definition_id_for_property_field(
            "res.partner", "properties"
        )
        self.assertTrue(first_id)

        # Simulate the cache clear that field create/unlink triggers via
        # _setup_models__ (which clears every registry cache group).
        self.registry.clear_cache("stable")

        second_id = self.PropertiesDefinition._get_definition_id_for_property_field(
            "res.partner", "properties"
        )
        self.assertEqual(
            first_id,
            second_id,
            "Re-lookup after cache clear must resolve to the same valid record",
        )
        # The id served after invalidation must point to a live row, never a
        # dangling reference.
        self.assertTrue(self.PropertiesDefinition.browse(second_id).exists())

    def test_search_unsupported_operator_raises(self):
        """The mixin search helper rejects any operator other than ``in``.

        This pins the documented brittle contract: a future refactor that wants
        to support ``=`` (or any other operator) is forced to acknowledge and
        remove this guard rather than break silently.
        """
        partner_model = self.env["res.partner"]
        with self.assertRaises(NotImplementedError):
            partner_model._search_properties_base_definition_id("=", 1)

        with self.assertRaises(NotImplementedError):
            partner_model._search_properties_base_definition_id("not in", [1])

    def test_search_in_operator_returns_constant_domain(self):
        """The supported ``in`` operator resolves to a constant TRUE/FALSE domain."""
        partner_model = self.env["res.partner"]
        definition_id = self.PropertiesDefinition._get_definition_id_for_property_field(
            "res.partner", "properties"
        )

        match_domain = partner_model._search_properties_base_definition_id(
            "in", [definition_id]
        )
        self.assertEqual(match_domain, Domain.TRUE)

        miss_domain = partner_model._search_properties_base_definition_id(
            "in", [definition_id + 10**9]
        )
        self.assertEqual(miss_domain, Domain.FALSE)

    def test_field_to_sql_export_branch(self):
        """``_field_to_sql`` renders the non-stored definition field as a constant.

        The override lets the non-stored ``properties_base_definition_id`` field
        be exported/read; it returns the resolved definition id as a literal SQL
        fragment instead of delegating to the column-based default.
        """
        partner_model = self.env["res.partner"]
        definition_id = self.PropertiesDefinition._get_definition_id_for_property_field(
            "res.partner", "properties"
        )

        sql = partner_model._field_to_sql(
            partner_model._table, "properties_base_definition_id"
        )
        # The rendered fragment must carry the resolved definition id as its
        # single parameter value.
        self.assertIn(definition_id, sql.params)
