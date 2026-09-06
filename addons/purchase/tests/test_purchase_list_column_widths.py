from lxml import etree

from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged("post_install", "-at_install")
class TestPurchaseOrderPriorityColumnWidth(AccountTestInvoicingCommon):
    """The one-star priority column must not reserve a full text column.

    `getWidthSpecs` reads `column.field.listViewWidth` and then
    `FIELD_WIDTHS[<widget name>]` (web/static/src/views/list/column_width_hook.js:191-201).
    `priorityField` declares no `listViewWidth`
    (web/static/src/fields/selection/priority/priority_field.js:106-118) and
    `FIELD_WIDTHS` has no `priority` key (web/static/src/fields/field_widths.js:31-58),
    so without a declared width the column falls back to DEFAULT_MIN_WIDTH = 80.

    This asserts the three lists declare the width. That the attribute is then
    honoured in pixels is covered by web's own suite
    (web/static/tests/views/list/column_widths.test.js:256).
    """

    LIST_VIEWS = (
        "purchase.view_purchase_order_list",
        "purchase.view_purchase_order_list_kpis",
        "purchase.view_purchase_order_list_2",
    )

    def test_priority_column_declares_a_star_sized_width(self):
        for xmlid in self.LIST_VIEWS:
            with self.subTest(view=xmlid):
                view = self.env.ref(xmlid)
                arch = etree.fromstring(
                    self.env["purchase.order"].get_view(
                        view_id=view.id, view_type="list"
                    )["arch"]
                )
                node = arch.find(".//field[@name='priority']")
                self.assertIsNotNone(node, "no priority column in this list")
                self.assertEqual(node.get("width"), "20px")
                self.assertEqual(
                    node.get("nolabel"),
                    "1",
                    "a 20px column cannot hold a header label",
                )

    def test_the_form_priority_field_keeps_no_width(self):
        view = self.env.ref("purchase.view_purchase_order_form")
        arch = etree.fromstring(
            self.env["purchase.order"].get_view(view_id=view.id, view_type="form")[
                "arch"
            ]
        )
        node = arch.find(".//field[@name='priority']")
        self.assertIsNotNone(node)
        self.assertIsNone(
            node.get("width"), "width is a list-column concern, not a form one"
        )
