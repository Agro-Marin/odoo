# Part of Odoo. See LICENSE file for full copyright and licensing details.

from types import SimpleNamespace

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import new_test_user, tagged

from odoo.addons.product.tests.common import ProductCommon


@tagged("post_install", "-at_install")
class TestProductAuditFixes(ProductCommon):
    """Regression net for the defects found in the `product` audit.

    Every test below was written from a reproduction that *failed* before the
    corresponding fix; the docstrings state the observed broken behaviour so the
    intent survives if the implementation changes.
    """

    # -- pricelist feature toggle --------------------------------------------

    def test_settings_save_does_not_archive_pricelists_when_already_disabled(self):
        """Saving settings while the pricelist feature is already off used to
        run `sudo().search([]).action_archive()` on *every* save, silently
        re-archiving pricelists an admin had reactivated.
        """
        pricelist = self.env["product.pricelist"].create({"name": "SurvivorPL"})
        group = self.env.ref("product.group_product_pricelist")
        self.env.user.write({"group_ids": [Command.unlink(group.id)]})
        self.env.invalidate_all()

        settings = self.env["res.config.settings"].create({})
        self.assertFalse(
            settings.group_product_pricelist, "sanity: feature is already off"
        )
        settings.set_values()

        self.assertTrue(
            pricelist.active,
            "an unrelated settings save must not archive existing pricelists",
        )

    def test_disabling_pricelist_feature_still_archives(self):
        """The enabled -> disabled transition must keep archiving."""
        self.env["res.config.settings"].create(
            {"group_product_pricelist": True}
        ).execute()
        pricelist = self.env["product.pricelist"].create({"name": "ToArchivePL"})

        settings = self.env["res.config.settings"].create({})
        self.assertTrue(settings.group_product_pricelist, "sanity: feature is on")
        settings.group_product_pricelist = False
        settings.set_values()

        self.assertFalse(
            pricelist.active, "disabling the feature must archive active pricelists"
        )

    # -- attribute line reactivation -----------------------------------------

    def test_archived_attribute_line_is_reactivated_not_duplicated(self):
        """`create` reuses an archived line for the same (template, attribute)
        instead of inserting a second one, so existing variants keep their
        configuration."""
        attribute = self.env["product.attribute"].create(
            {"name": "ReuseColor", "value_ids": [Command.create({"name": "R"})]}
        )
        template = self.env["product.template"].create(
            {
                "name": "ReuseProbe",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        line = template.attribute_line_ids
        line.active = False
        self.env.flush_all()

        # Re-adding the same attribute reactivates the archived line instead of
        # tripping the index.
        template.write(
            {
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ]
            }
        )
        self.env.flush_all()
        self.assertEqual(
            len(
                template.attribute_line_ids.filtered(
                    lambda l: l.attribute_id == attribute
                )
            ),
            1,
        )

    # -- product tag name uniqueness -----------------------------------------

    def test_duplicate_tag_name_rejected(self):
        """`unique (name)` on a translated (jsonb) column compares whole
        translation dicts, so two tags with the same visible name inserted
        cleanly as soon as one of them had a second translation.
        """
        self.env["product.tag"].create({"name": "DupTag"})
        with self.assertRaises(ValidationError):
            self.env["product.tag"].create({"name": "DupTag"})
            self.env.flush_all()

    def test_duplicate_tag_name_rejected_across_translations(self):
        """The exact reproduction: a second translation on the first tag used to
        make the SQL unique index blind to the collision."""
        self.env["res.lang"]._activate_lang("es_MX")
        tag = self.env["product.tag"].create({"name": "TransTag"})
        tag.with_context(lang="es_MX").name = "Frágil"
        self.env.flush_all()

        with self.assertRaises(ValidationError):
            self.env["product.tag"].create({"name": "TransTag"})
            self.env.flush_all()

    # -- combo integrity ------------------------------------------------------

    def test_unlinking_last_combo_item_rejected(self):
        """`product.combo`'s "at least 1 choice" constraint only fires on writes
        to the combo, so deleting the items directly left an empty combo whose
        `base_price` is 0.
        """
        product = (
            self.env["product.template"]
            .create({"name": "ComboChoice", "list_price": 5.0})
            .product_variant_id
        )
        combo = self.env["product.combo"].create(
            {
                "name": "AuditCombo",
                "combo_item_ids": [Command.create({"product_id": product.id})],
            }
        )
        with self.assertRaises(ValidationError):
            combo.combo_item_ids.unlink()
            # The guard runs at precommit (see `product.combo.item.unlink`), which
            # `cr.flush()` drives -- the same path a real request takes on commit.
            self.env.cr.flush()

    def test_replacing_all_combo_items_in_one_write_is_allowed(self):
        """The guard must not break the normal edit flow, where the form sends
        delete-then-create for the same combo in a single write."""
        products = (
            self.env["product.template"]
            .create(
                [
                    {"name": "ComboA", "list_price": 5.0},
                    {"name": "ComboB", "list_price": 7.0},
                ]
            )
            .product_variant_id
        )
        combo = self.env["product.combo"].create(
            {
                "name": "SwapCombo",
                "combo_item_ids": [Command.create({"product_id": products[0].id})],
            }
        )
        combo.write(
            {
                "combo_item_ids": [
                    Command.delete(combo.combo_item_ids.id),
                    Command.create({"product_id": products[1].id}),
                ]
            }
        )
        self.env.cr.flush()
        self.assertEqual(combo.combo_item_ids.product_id, products[1])

    def test_deleting_combo_cascades_to_its_items(self):
        """Deleting the combo itself must still work (the guard only protects
        against emptying a surviving combo)."""
        product = (
            self.env["product.template"]
            .create({"name": "ComboGone", "list_price": 5.0})
            .product_variant_id
        )
        combo = self.env["product.combo"].create(
            {
                "name": "DoomedCombo",
                "combo_item_ids": [Command.create({"product_id": product.id})],
            }
        )
        combo.unlink()
        self.env.cr.flush()
        self.assertFalse(combo.exists())

    # -- category product_count invalidation ----------------------------------

    def test_product_count_refreshes_when_product_changes_category(self):
        """`product_count` is a non-stored compute that declared no dependency,
        so it stayed cached for the whole transaction and reported pre-move
        counts."""
        Category = self.env["product.category"]
        source = Category.create({"name": "CountSource"})
        target = Category.create({"name": "CountTarget"})
        template = self.env["product.template"].create(
            {"name": "CountProbe", "categ_id": source.id}
        )
        self.assertEqual(source.product_count, 1)
        self.assertEqual(target.product_count, 0)

        template.categ_id = target
        self.env.flush_all()

        self.assertEqual(source.product_count, 0, "source count must drop")
        self.assertEqual(target.product_count, 1, "target count must rise")

    # -- packaging barcode uniqueness ----------------------------------------

    def test_packaging_barcode_is_unique_per_company_not_globally(self):
        """A global `unique(barcode)` contradicted `product.product`, whose
        barcodes are explicitly per-company."""
        company_a = self.env["res.company"].create({"name": "PkgCoA"})
        company_b = self.env["res.company"].create({"name": "PkgCoB"})
        uom = self.env.ref("uom.product_uom_unit")
        products = {}
        for company in (company_a, company_b):
            template = self.env["product.template"].create(
                {"name": f"Pkg-{company.name}", "company_id": company.id}
            )
            products[company] = template.product_variant_id

        self.env["product.uom"].create(
            {
                "product_id": products[company_a].id,
                "uom_id": uom.id,
                "barcode": "SHARED-BC",
                "company_id": company_a.id,
            }
        )
        # Same barcode, other company: allowed, exactly like product barcodes.
        self.env["product.uom"].create(
            {
                "product_id": products[company_b].id,
                "uom_id": uom.id,
                "barcode": "SHARED-BC",
                "company_id": company_b.id,
            }
        )
        self.env.flush_all()

    def test_packaging_barcode_still_unique_within_a_company(self):
        company = self.env["res.company"].create({"name": "PkgCoSolo"})
        uom = self.env.ref("uom.product_uom_unit")
        template = self.env["product.template"].create(
            {"name": "PkgSolo", "company_id": company.id}
        )
        self.env["product.uom"].create(
            {
                "product_id": template.product_variant_id.id,
                "uom_id": uom.id,
                "barcode": "SOLO-BC",
                "company_id": company.id,
            }
        )
        self.env.flush_all()
        with self.assertRaises(Exception):
            self.env["product.uom"].create(
                {
                    "product_id": template.product_variant_id.id,
                    "uom_id": uom.id,
                    "barcode": "SOLO-BC",
                    "company_id": company.id,
                }
            )
            self.env.flush_all()

    def test_product_barcode_collides_with_same_company_packaging(self):
        """The product-side and packaging-side checks must agree: within one
        company a product may not take a barcode a packaging already uses."""
        company = self.env["res.company"].create({"name": "PkgCoSym"})
        uom = self.env.ref("uom.product_uom_unit")
        template = self.env["product.template"].create(
            {"name": "SymHolder", "company_id": company.id}
        )
        self.env["product.uom"].create(
            {
                "product_id": template.product_variant_id.id,
                "uom_id": uom.id,
                "barcode": "SYM-BC",
                "company_id": company.id,
            }
        )
        self.env.flush_all()
        with self.assertRaises(ValidationError):
            self.env["product.template"].create(
                {
                    "name": "SymProduct",
                    "company_id": company.id,
                    "barcode": "SYM-BC",
                }
            )
            self.env.flush_all()

    # -- multi-company record rules -------------------------------------------

    def test_packaging_not_visible_across_companies(self):
        """`product.uom` has a real `company_id` and employee read access, but
        no record rule -- packaging barcodes leaked across companies."""
        company_a = self.env["res.company"].create({"name": "RuleCoA"})
        company_b = self.env["res.company"].create({"name": "RuleCoB"})
        uom = self.env.ref("uom.product_uom_unit")
        template = self.env["product.template"].create(
            {"name": "SecretPkg", "company_id": company_b.id}
        )
        packaging = self.env["product.uom"].create(
            {
                "product_id": template.product_variant_id.id,
                "uom_id": uom.id,
                "barcode": "SECRET-PKG",
                "company_id": company_b.id,
            }
        )
        self.env.flush_all()

        user = new_test_user(self.env, login="rule_emp", groups="base.group_user")
        user.write(
            {"company_ids": [Command.set([company_a.id])], "company_id": company_a.id}
        )

        self.assertFalse(
            self.env["product.uom"].with_user(user).search([("id", "=", packaging.id)]),
            "another company's packaging must not be visible",
        )

    def test_combo_item_not_visible_across_companies(self):
        company_a = self.env["res.company"].create({"name": "RuleComboA"})
        company_b = self.env["res.company"].create({"name": "RuleComboB"})
        choice = (
            self.env["product.template"]
            .create(
                {"name": "ComboChoiceB", "company_id": company_b.id, "list_price": 9.0}
            )
            .product_variant_id
        )
        combo = (
            self.env["product.combo"]
            .with_company(company_b)
            .create(
                {
                    "name": "SecretCombo",
                    "company_id": company_b.id,
                    "combo_item_ids": [Command.create({"product_id": choice.id})],
                }
            )
        )
        self.env.flush_all()

        user = new_test_user(self.env, login="rule_emp2", groups="base.group_user")
        user.write(
            {"company_ids": [Command.set([company_a.id])], "company_id": company_a.id}
        )

        self.assertFalse(
            self.env["product.combo.item"]
            .with_user(user)
            .search([("id", "=", combo.combo_item_ids.id)]),
            "another company's combo items must not be visible",
        )

    def test_label_layout_wizard_is_private_to_its_creator(self):
        """Transient models get no implicit per-user isolation and the wizard is
        reachable by id from the report payload, so any employee could read or
        overwrite another user's in-flight wizard."""
        user_a = new_test_user(self.env, login="label_a", groups="base.group_user")
        user_b = new_test_user(self.env, login="label_b", groups="base.group_user")
        wizard = (
            self.env["product.label.layout"]
            .with_user(user_a)
            .create({"print_format": "4x7xprice"})
        )
        self.env.flush_all()

        with self.assertRaises(AccessError):
            self.env["product.label.layout"].with_user(user_b).browse(wizard.id).read(
                ["print_format"]
            )

    # -- variant combination integrity ---------------------------------------

    def test_variant_value_alias_keeps_combination_indices_in_sync(self):
        """`product_template_variant_value_ids` shares the
        `product_variant_combination` table with
        `product_template_attribute_value_ids`, but only the latter fed
        `combination_indices`. Writing through the alias moved the relation
        while the stored index kept its old value, so two *active* variants
        could end up on the same combination despite `_combination_unique`.
        """
        attribute = self.env["product.attribute"].create(
            {
                "name": "AliasColor",
                "value_ids": [
                    Command.create({"name": "R"}),
                    Command.create({"name": "B"}),
                ],
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "AliasProbe",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        first, second = template.product_variant_ids
        target = second.product_template_attribute_value_ids

        # A direct write (as an RPC could do) must either be refused or keep the
        # index consistent -- never leave the two out of sync.
        try:
            first.write(
                {"product_template_variant_value_ids": [Command.set(target.ids)]}
            )
            self.env.flush_all()
        except Exception:
            return  # refused outright: invariant preserved
        self.env.invalidate_all()
        self.assertEqual(
            first.combination_indices,
            first.product_template_attribute_value_ids._ids2str(),
            "combination_indices must match the relation it indexes",
        )

    def test_variant_value_alias_is_readonly(self):
        """The alias is a display-only view of the combination."""
        field = self.env["product.product"]._fields[
            "product_template_variant_value_ids"
        ]
        self.assertTrue(field.readonly)

    # -- price/UoM compatibility ---------------------------------------------

    def test_price_in_incompatible_uom_raises(self):
        """`uom._compute_price` scales by the factor ratio with no compatibility
        check, so pricing a Units product "in Liters" returned list_price x 1000
        instead of failing."""
        liter = self.env.ref("uom.product_uom_litre", raise_if_not_found=False)
        if not liter:
            self.skipTest("liter UoM not available")
        template = self.env["product.template"].create(
            {"name": "UomProbe", "list_price": 10.0}
        )
        self.assertFalse(
            template.uom_id._has_common_reference(liter), "sanity: incompatible units"
        )
        with self.assertRaises(UserError):
            template._compute_price("list_price", uom=liter)
        with self.assertRaises(UserError):
            template.product_variant_id._compute_price("list_price", uom=liter)

    def test_price_in_compatible_uom_still_converts(self):
        """The guard must not disturb legitimate conversions."""
        dozen = self.env.ref("uom.product_uom_dozen")
        unit = self.env.ref("uom.product_uom_unit")
        template = self.env["product.template"].create(
            {"name": "UomOk", "list_price": 12.0, "uom_id": unit.id}
        )
        self.assertAlmostEqual(
            template._compute_price("list_price", uom=dozen)[template.id],
            unit._compute_price(12.0, dozen),
            places=6,
        )

    # -- variant limit config parameter --------------------------------------

    def test_invalid_variant_limit_parameter_is_tolerated(self):
        """A non-numeric `product.dynamic_variant_limit` (free-text system
        parameter) used to abort variant generation with a bare ValueError."""
        self.env["ir.config_parameter"].sudo().set_param(
            "product.dynamic_variant_limit", "not-a-number"
        )
        attribute = self.env["product.attribute"].create(
            {"name": "LimitAttr", "value_ids": [Command.create({"name": "x"})]}
        )
        template = self.env["product.template"].create(
            {
                "name": "LimitProbe",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        self.assertTrue(template.product_variant_ids)

    # -- catalog action context ----------------------------------------------

    def test_catalog_action_drops_caller_defaults(self):
        """The catalog action forwarded the order form's whole context, so a
        product created from it inherited `default_*` keys belonging to a
        sale/purchase order."""
        order = self.env["product.catalog.mixin"]
        context = {
            "default_partner_id": 42,
            "default_name": "SO0001",
            "allowed_company_ids": [self.env.company.id],
        }
        forwarded = order.with_context(**context)._get_catalog_action_context()
        self.assertNotIn("default_partner_id", forwarded)
        self.assertNotIn("default_name", forwarded)
        self.assertIn(
            "allowed_company_ids", forwarded, "non-default keys must be preserved"
        )

    # -- pricelist report -----------------------------------------------------

    def test_pricelist_report_rejects_oversized_product_list(self):
        """`quantities` was capped but `active_ids` was not, so one request could
        request millions of price computations."""
        Report = self.env["report.product.report_pricelist"]
        with self.assertRaises(UserError):
            Report._get_report_data(
                {
                    "active_model": "product.template",
                    "active_ids": list(range(Report.MAX_PRODUCTS + 1)),
                    "quantities": [1],
                }
            )

    def test_pricelist_report_batches_price_computation(self):
        """Pricing was done one (product, quantity) pair at a time, costing a
        full rule search per cell. Adding products must not add queries
        proportionally.
        """
        Report = self.env["report.product.report_pricelist"]
        pricelist = self.env["product.pricelist"].create({"name": "ReportPL"})
        templates = self.env["product.template"].create(
            [{"name": f"ReportProbe{i}", "list_price": 10.0 + i} for i in range(20)]
        )
        self.env.flush_all()

        def query_count(products):
            self.env.invalidate_all()
            before = self.env.cr.sql_log_count
            Report._get_report_data(
                {
                    "active_model": "product.template",
                    "active_ids": products.ids,
                    "pricelist_id": pricelist.id,
                    "quantities": [1, 2, 3, 4, 5],
                }
            )
            return self.env.cr.sql_log_count - before

        few = query_count(templates[:5])
        many = query_count(templates)
        self.assertLess(
            many,
            few * 2,
            "query count must not scale with the number of products "
            f"(5 products: {few} queries, 20 products: {many})",
        )

    def test_pricelist_report_prices_are_unchanged_by_batching(self):
        """Behaviour lock: the batched path must return the same prices as
        pricing each product individually."""
        Report = self.env["report.product.report_pricelist"]
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "ReportValuesPL",
                "item_ids": [
                    Command.create(
                        {
                            "applied_on": "3_global",
                            "compute_price": "percentage",
                            "percent_price": 10,
                        }
                    )
                ],
            }
        )
        templates = self.env["product.template"].create(
            [{"name": f"ValueProbe{i}", "list_price": 100.0 + i} for i in range(3)]
        )
        self.env.flush_all()

        data = Report._get_report_data(
            {
                "active_model": "product.template",
                "active_ids": templates.ids,
                "pricelist_id": pricelist.id,
                "quantities": [1, 4],
            }
        )
        by_id = {row["id"]: row for row in data["products"]}
        for template in templates:
            for qty in (1, 4):
                self.assertAlmostEqual(
                    by_id[template.id]["price"][qty],
                    pricelist._get_product_price(template, qty),
                    places=6,
                )

    # -- attribute value deletion --------------------------------------------

    def test_deleting_value_used_on_archived_template_archives_it(self):
        """`_unlink_except_used_on_product` only looks at lines of *active*
        templates, so a value used solely on an archived template passed every
        Python guard and then hit the restrict FK on the attribute-line relation
        -- surfacing a raw RestrictViolation traceback instead of a handled
        outcome."""
        attribute = self.env["product.attribute"].create(
            {
                "name": "ArchAttr",
                "create_variant": "no_variant",
                "value_ids": [
                    Command.create({"name": "Engraving"}),
                    Command.create({"name": "Plain"}),
                ],
            }
        )
        template = self.env["product.template"].create(
            {
                "name": "ArchProbe",
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        template.action_archive()
        self.env.flush_all()

        value = attribute.value_ids[0]
        value.unlink()
        self.env.flush_all()

        # Archived rather than deleted, and above all: no database error.
        self.assertTrue(value.exists(), "the value must survive as archived")
        self.assertFalse(value.active)

    def test_deleting_unused_value_still_deletes(self):
        """The archive fallback must not swallow ordinary deletions."""
        attribute = self.env["product.attribute"].create(
            {
                "name": "FreeAttr",
                "value_ids": [
                    Command.create({"name": "A"}),
                    Command.create({"name": "B"}),
                ],
            }
        )
        value = attribute.value_ids[0]
        value.unlink()
        self.env.flush_all()
        self.assertFalse(value.exists(), "an unused value must be deleted outright")

    # -- catalog controller ---------------------------------------------------

    def _catalog_controller(self):
        """`_get_order` reads `request.env`, so it needs a request. The catalog
        routes have no concrete order model inside `product` itself (sale /
        purchase provide one), which is why this guard had no coverage at all --
        stub the request instead of pulling in a dependency.
        """
        from unittest.mock import patch

        from odoo.addons.product.controllers import catalog

        return patch.object(
            catalog, "request", SimpleNamespace(env=self.env)
        ), catalog.ProductCatalogController

    def test_catalog_get_order_rejects_unknown_model(self):
        """Only models implementing `product.catalog.mixin` are valid targets;
        `res_model` comes straight from the client."""
        request_patch, controller = self._catalog_controller()
        with request_patch, self.assertRaises(UserError):
            controller._get_order("res.partner", 1)

    def test_catalog_get_order_rejects_non_numeric_id(self):
        """A non-numeric id is client-provided input: it must produce a normal
        user error, not a bare ValueError (HTTP 500)."""
        request_patch, controller = self._catalog_controller()
        with request_patch, self.assertRaises(UserError):
            controller._get_order("product.catalog.mixin", "not-an-int")

    # -- multi-variant template cost ------------------------------------------

    def _template_with_two_costed_variants(self, name):
        attribute = self.env["product.attribute"].create(
            {
                "name": f"{name}Attr",
                "value_ids": [
                    Command.create({"name": "one"}),
                    Command.create({"name": "two"}),
                ],
            }
        )
        template = self.env["product.template"].create(
            {
                "name": name,
                "list_price": 0.0,
                "attribute_line_ids": [
                    Command.create(
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [Command.set(attribute.value_ids.ids)],
                        }
                    )
                ],
            }
        )
        self.assertEqual(len(template.product_variant_ids), 2)
        return template

    def test_multi_variant_template_cost_falls_back_to_first_variant(self):
        """Contract lock, not a bug report.

        `standard_price` is stored per variant, so a multi-variant template
        reads 0 and `_compute_price` falls back to the first variant's cost --
        otherwise a cost-based pricelist would price the template free.
        """
        template = self._template_with_two_costed_variants("CostFallback")
        first, second = template.product_variant_ids
        first.standard_price = 10.0
        second.standard_price = 999.0
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertEqual(template.standard_price, 0.0, "template mirrors no variant")
        self.assertAlmostEqual(
            template._compute_price("standard_price")[template.id], 10.0, places=2
        )

    def test_multi_variant_template_cost_follows_variant_order(self):
        """The sharp edge of the fallback, pinned so it cannot regress unnoticed:
        "first variant" means `product.product._order` ("default_code, name,
        id"), so changing an internal reference changes which variant's cost the
        template is priced from -- without any cost being edited.
        """
        template = self._template_with_two_costed_variants("CostOrder")
        first, second = template.product_variant_ids
        first.standard_price = 10.0
        second.standard_price = 999.0
        self.env.flush_all()
        self.env.invalidate_all()
        self.assertAlmostEqual(
            template._compute_price("standard_price")[template.id], 10.0, places=2
        )

        # Give the *other* variant an internal reference that sorts first.
        second.default_code = "AAA-first"
        self.env.flush_all()
        self.env.invalidate_all()

        self.assertAlmostEqual(
            template._compute_price("standard_price")[template.id],
            999.0,
            places=2,
            msg="cost basis follows variant ordering, not any cost edit",
        )

    # -- variant cache scoping ------------------------------------------------

    def _warm_caches(self, template):
        """Fill one product-variant cache entry and several 'default' ones."""
        self.env["ir.rule"]._compute_domain("product.template", "read")
        self.env["ir.rule"]._compute_domain("res.partner", "read")
        self.env["ir.model.access"].check("product.template", "read", False)
        template._get_first_possible_variant_id()

    def test_variant_cache_invalidation_spares_unrelated_caches(self):
        """Variant churn used to clear the whole "default" ormcache group -- so
        archiving one variant evicted record-rule domains, ACL checks and xmlid
        lookups in this and every other worker. Those live in "default"; the two
        variant lookups now live in "product_variants".
        """
        lrus = self.env.registry.ormcache_lrus
        template = self.env["product.template"].create({"name": "CacheScopeProbe"})
        self.env.flush_all()
        self._warm_caches(template)

        default_before = len(lrus["default"])
        variants_before = len(lrus["product_variants"])
        self.assertTrue(default_before, "sanity: 'default' is warm")
        self.assertTrue(variants_before, "sanity: 'product_variants' is warm")

        template.product_variant_id.write({"active": False})

        self.assertEqual(
            len(lrus["default"]),
            default_before,
            "archiving a variant must not evict unrelated 'default' caches",
        )
        self.assertEqual(
            len(lrus["product_variants"]), 0, "variant lookups must be invalidated"
        )

    def test_clearing_default_still_clears_variant_caches(self):
        """Backward compatibility: "product_variants" is a member of the
        "default" composite, so code clearing the broad group (outside this
        module) keeps invalidating variant lookups as it did before."""
        lrus = self.env.registry.ormcache_lrus
        template = self.env["product.template"].create({"name": "CacheCompatProbe"})
        self.env.flush_all()
        self._warm_caches(template)
        self.assertTrue(len(lrus["product_variants"]), "sanity: warm")

        self.env.registry.clear_cache()

        self.assertEqual(len(lrus["product_variants"]), 0)

    # -- multi-company pricing contract ---------------------------------------

    def test_pricing_follows_the_environment_company_not_the_pricelist_owner(self):
        """Contract lock, not a bug report.

        Company-specific currency rates and the company-dependent
        `standard_price` are resolved against `self.env.company`, so the *same*
        pricelist can return different prices to readers in different companies.
        That is by design: `company_id` on a pricelist marks ownership, and every
        caller sets the company of the document being priced first (e.g.
        `order.with_company(order.company_id)` in `sale.order`, `sale.order.line`
        and the catalog controller).

        This test exists so that a future "fix" making pricing prefer
        `pricelist.company_id` fails loudly here instead of silently changing
        inter-company prices.
        """
        usd = self.env.ref("base.USD")
        usd.active = True
        company_a = self.env["res.company"].create(
            {"name": "PriceCtxA", "currency_id": usd.id}
        )
        company_b = self.env["res.company"].create(
            {"name": "PriceCtxB", "currency_id": usd.id}
        )
        template = self.env["product.template"].create(
            {"name": "PriceCtxProbe", "list_price": 5.0}
        )
        product = template.product_variant_id
        product.with_company(company_a).standard_price = 10.0
        product.with_company(company_b).standard_price = 70.0
        self.env.flush_all()

        # A cost-based pricelist owned by company B.
        pricelist = self.env["product.pricelist"].create(
            {
                "name": "CtxPL",
                "company_id": company_b.id,
                "currency_id": usd.id,
                "item_ids": [
                    Command.create(
                        {
                            "applied_on": "3_global",
                            "base": "standard_price",
                            "compute_price": "formula",
                            "price_discount": 0.0,
                        }
                    )
                ],
            }
        )
        self.env.flush_all()

        self.env.invalidate_all()
        price_from_a = pricelist._get_product_price(
            product.with_company(company_a), 1.0
        )
        self.env.invalidate_all()
        price_from_b = pricelist._get_product_price(
            product.with_company(company_b), 1.0
        )

        self.assertAlmostEqual(price_from_a, 10.0, places=2)
        self.assertAlmostEqual(price_from_b, 70.0, places=2)

    # -- duplication of a translated name -------------------------------------

    def _spanish_product(self):
        self.env["res.lang"]._activate_lang("es_MX")
        template = self.env["product.template"].create({"name": "Blue Widget"})
        template.with_context(lang="es_MX").name = "Artilugio Azul"
        self.env.flush_all()
        return template

    def test_duplicating_in_one_language_suffixes_every_language(self):
        """`copy_data` rewrites `name` to "<name> (copy)" using only the
        duplicating user's language; `copy_translations` then restored the
        source record's translations for every *other* language, so a copy made
        by a Spanish user kept the original's exact en_US name -- an English
        user saw two products with identical names.
        """
        template = self._spanish_product()

        copy = template.with_context(lang="es_MX").copy()
        self.env.flush_all()

        name_en = copy.with_context(lang="en_US").name
        name_es = copy.with_context(lang="es_MX").name
        self.assertNotEqual(
            name_en,
            "Blue Widget",
            "the copy must not reuse the source product's English name verbatim",
        )
        self.assertIn("Blue Widget", name_en, "the English name keeps its own term")
        self.assertNotEqual(name_es, "Artilugio Azul")
        self.assertIn("Artilugio Azul", name_es, "the Spanish name keeps its own term")

    def test_duplicating_in_the_base_language_also_suffixes_translations(self):
        """The mirror case: duplicating as an en_US user used to leave the
        Spanish translation as the source product's unsuffixed name.
        """
        template = self._spanish_product()

        copy = template.with_context(lang="en_US").copy()
        self.env.flush_all()

        self.assertNotEqual(copy.with_context(lang="es_MX").name, "Artilugio Azul")
        self.assertIn("Artilugio Azul", copy.with_context(lang="es_MX").name)

    def test_renaming_a_copy_in_one_language_leaves_the_others_distinguishable(self):
        """Writing a translated field in one language only ever updates that
        language -- by design.  What must not happen is the other languages
        falling back to the *source* product's name.
        """
        template = self._spanish_product()

        copy = template.with_context(lang="es_MX").copy()
        copy.with_context(lang="es_MX").name = "Artilugio Rojo"
        self.env.flush_all()

        self.assertEqual(copy.with_context(lang="es_MX").name, "Artilugio Rojo")
        self.assertNotEqual(copy.with_context(lang="en_US").name, "Blue Widget")

    def test_explicit_default_name_wins_in_every_language(self):
        """A caller-supplied `name` default must not be suffixed or
        per-language patched: `copy_translations` has to leave it alone.
        """
        template = self._spanish_product()

        copy = template.with_context(lang="es_MX").copy({"name": "Fixed Name"})
        self.env.flush_all()

        self.assertEqual(copy.with_context(lang="en_US").name, "Fixed Name")
        self.assertEqual(copy.with_context(lang="es_MX").name, "Fixed Name")

    def test_duplicating_a_variant_suffixes_every_language(self):
        """`product.product.copy` delegates to the template, so it must inherit
        the same per-language suffixing.
        """
        template = self._spanish_product()

        variant = template.product_variant_id.with_context(lang="es_MX").copy()
        self.env.flush_all()

        self.assertNotEqual(variant.with_context(lang="en_US").name, "Blue Widget")
        self.assertIn("Blue Widget", variant.with_context(lang="en_US").name)
        self.assertIn("Artilugio Azul", variant.with_context(lang="es_MX").name)
