# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.addons.product.tests.common import ProductCommon


class SavepointCounter:
    """Count the ``SAVEPOINT`` statements issued while deleting.

    The property under test is not a timing but a shape: deleting records that
    are all deletable must not cost one savepoint per record.
    """

    def __init__(self, cr):
        self.cr = cr
        self.count = 0

    def __enter__(self):
        self._original = self.cr.execute

        def counting(query, params=None, log_exceptions=True):
            if "SAVEPOINT" in str(query).upper():
                self.count += 1
            return self._original(query, params, log_exceptions)

        self.cr.execute = counting
        return self

    def __exit__(self, *exc_info):
        self.cr.execute = self._original


class TestUnlinkWherePossible(ProductCommon):
    """Deleting product master data is best-effort: whatever the database
    refuses is archived. The batch must be attempted as a whole and split only
    on failure.
    """

    def _template_with_values(self, name, count, create_variant="no_variant"):
        attribute = self.env["product.attribute"].create(
            {
                "name": f"{name} attribute",
                "create_variant": create_variant,
                "display_type": "radio",
            }
        )
        values = self.env["product.attribute.value"].create(
            [
                {"name": f"{name} v{i}", "attribute_id": attribute.id}
                for i in range(count)
            ]
        )
        template = self.env["product.template"].create(
            {
                "name": name,
                "uom_id": self.uom_unit.id,
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [(6, 0, values.ids)],
                        },
                    )
                ],
            }
        )
        self.env.flush_all()
        return template, template.attribute_line_ids.product_template_value_ids

    def test_deletable_values_are_deleted_in_one_batch(self):
        """Nothing blocked: one attempt, not one savepoint per value."""
        count = 20
        _template, ptavs = self._template_with_values("Batch delete", count)
        self.assertEqual(len(ptavs), count)

        with SavepointCounter(self.env.cr) as counter:
            ptavs.unlink()
            self.env.flush_all()

        self.assertFalse(ptavs.exists(), "every deletable value should be gone")
        self.assertLess(
            counter.count,
            count,
            "the batch must be attempted as a whole, not one savepoint per value",
        )

    def test_blocked_value_is_archived_and_the_rest_deleted(self):
        """One blocked value must not stop the others from being deleted."""
        template, ptavs = self._template_with_values(
            "Mixed delete", 8, create_variant="always"
        )
        pinned_variant = template.product_variant_ids[0]
        # `product.combo.item.product_id` is ondelete='restrict', so this variant
        # cannot be deleted, which in turn pins the value it materializes.
        self.env["product.combo"].create(
            {
                "name": "Mixed delete combo",
                "combo_item_ids": [(0, 0, {"product_id": pinned_variant.id})],
            }
        )
        self.env.flush_all()

        ptavs.unlink()
        self.env.flush_all()

        survivors = ptavs.exists()
        self.assertTrue(survivors, "the pinned value should have survived")
        self.assertLess(
            len(survivors), len(ptavs), "the unblocked values should be deleted"
        )
        self.assertFalse(
            survivors.filtered("ptav_active"),
            "a value that could not be deleted must be archived, not left active",
        )

    def test_helper_reports_what_it_could_not_delete(self):
        """The helper deletes what it can and returns the remainder."""
        from odoo.addons.product.models.utils import unlink_where_possible

        _template, ptavs = self._template_with_values("Helper", 4)
        blocked = ptavs[0]

        def delete(records):
            if blocked in records:
                raise ValueError("blocked")
            records._unlink_without_fallback()

        remainder = unlink_where_possible(ptavs, delete)

        self.assertEqual(remainder, blocked)
        self.assertEqual(ptavs.exists(), blocked)
