import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, runAllTimers, test } from "@odoo/hoot";
import { click, edit } from "@odoo/hoot-dom";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { SUGGEST_TOGGLE_STORAGE_KEY } from "@purchase_stock/product_catalog/utils";
import {
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

class ProductProduct extends models.Model {
    _name = "product.product";

    name = fields.Char({ string: "Product Name" });
    type = fields.Selection({
        selection: [
            ["consu", "Goods"],
            ["service", "Service"],
        ],
    });
    default_code = fields.Char({ string: "Default Code" });
    monthly_demand = fields.Float();
    suggested_qty = fields.Integer();

    _records = [
        { id: 1, name: "name1", default_code: "AAAA" },
        { id: 2, name: "name2", default_code: "AAAB", suggested_qty: 10 },
        { id: 3, name: "name1", default_code: "AAAC" },
        { id: 4, name: "name2", default_code: "AAAD" },
    ];

    _views = {
        search: `
            <search>
                <filter name="products_in_purchase_order" string="In the Order" domain="[('id', '=', 0)]"/>
                <filter name="suggested" string="Suggested" domain="[('suggested_qty', '!=', 0)]"/>
                <searchpanel>
                    <field name="type" string="Type" icon="fa-th-list" expand="1"/>
                </searchpanel>
            </search>
        `,
        kanban: `
            <kanban records_draggable="0" js_class="purchase_product_kanban_catalog">
                <templates>
                    <t t-name="card">
                        <field name="name"/>
                        <field name="default_code"/>
                        <div name="o_kanban_price"
                        t-attf-id="product-{{record.id.raw_value}}-price"
                        class="d-flex flex-column"/>
                        <div name="kanban_purchase_suggest">
                            <!-- encapsulate in div with name="kanban_purchase_suggest" to make sure JS hides it -->
                            <field name="suggested_qty"/>
                        </div>
                    </t>
                </templates>
            </kanban>
        `,
    };
}

class PurchaseOrder extends models.Model {
    _name = "purchase.order";
    _records = [
        {
            id: 1,
        },
    ];
}

defineModels([ProductProduct, PurchaseOrder]);
defineMailModels();

const purchaseOrderLineInfo = {
    1: {
        quantity: 0,
        price: 35.0,
        uomDisplayName: "Units",
        min_qty: 1.0,
        suggested_qty: 0,
        productType: "consu",
    },
    2: {
        quantity: 0,
        price: 35.0,
        uomDisplayName: "Units",
        min_qty: 1.0,
        suggested_qty: 10,
        productType: "consu",
    },
    3: {
        quantity: 0,
        productType: "consu",
        uomDisplayName: "Units",
        price: 1299.0,
        min_qty: 5.0,
        suggested_qty: 1,
    },
    4: {
        quantity: 0,
        productType: "consu",
        uomDisplayName: "Units",
        price: 1299.0,
        min_qty: 0.0,
        suggested_qty: 1,
    },
};

onRpc("/product/catalog/order_lines_info", () => purchaseOrderLineInfo);

test("Adding products from purchase catalog with suggestion feature ON.", async () => {
    onRpc("/product/catalog/update_order_line_info", async (request) => {
        const { params } = await request.json();
        const { product_id, quantity } = params;
        expect.step(`product_id=${product_id} quantity=${quantity}`);
        return {};
    });

    await mountView({
        resModel: "product.product",
        type: "kanban",
        context: {
            product_catalog_order_model: "purchase.order",
            order_id: 1,
        },
    });

    await click(".o_kanban_record:nth-of-type(1) button:has(i.fa-shopping-cart)");
    await runAllTimers();
    expect(
        ".o_kanban_record:nth-of-type(1) .o_product_catalog_quantity .o_input",
    ).toHaveValue(1);

    expect(
        ".o_kanban_record:nth-of-type(2) div[name='kanban_purchase_suggest'] span:visible:contains('10')",
    ).toHaveCount(1, { message: "Suggested qty div should be visible on card #2" });
    await click(".o_kanban_record:nth-of-type(2) button:has(i.fa-shopping-cart)");
    await runAllTimers();
    expect(
        ".o_kanban_record:nth-of-type(2) .o_product_catalog_quantity .o_input",
    ).toHaveValue(10);
    expect(
        ".o_kanban_record:nth-of-type(2) div[name='kanban_purchase_suggest'] span:visible:contains('10')",
    ).toHaveCount(0, {
        message: "Div should be invisible now that suggested_qty == qty",
    });

    await click(".o_kanban_record:nth-of-type(2)");
    await runAllTimers();
    expect(
        ".o_kanban_record:nth-of-type(2) .o_product_catalog_quantity .o_input",
    ).toHaveValue(11);
    expect(
        ".o_kanban_record:nth-of-type(2) div[name='kanban_purchase_suggest'] span:visible:contains('10')",
    ).toHaveCount(1, { message: "Suggested qty div should be visible again" });

    await click(".o_kanban_record:nth-of-type(3)");
    await runAllTimers();
    expect(
        ".o_kanban_record:nth-of-type(3) .o_product_catalog_quantity .o_input",
    ).toHaveValue(5);

    await click(".o_kanban_record:nth-of-type(4)");
    await runAllTimers();
    expect(
        ".o_kanban_record:nth-of-type(4) .o_product_catalog_quantity .o_input",
    ).toHaveValue(1);

    expect.verifySteps([
        "product_id=1 quantity=1",
        "product_id=2 quantity=10",
        "product_id=2 quantity=11",
        "product_id=3 quantity=5",
        "product_id=4 quantity=1",
    ]);
});

test("The suggested total follows the parameters even when nothing is suggested", async () => {
    browser.localStorage.setItem(
        SUGGEST_TOGGLE_STORAGE_KEY,
        JSON.stringify({ isOn: true }),
    );
    const lateTotal = new Deferred();
    onRpc("product.product", "search_read", ({ kwargs }) =>
        kwargs.context.suggest_days === 7
            ? lateTotal
            : [{ id: 2, suggest_estimated_price: 480 }],
    );

    await mountView({
        resModel: "product.product",
        type: "kanban",
        context: {
            product_catalog_order_model: "purchase.order",
            product_catalog_order_state: "draft",
            order_id: 1,
            vendor_suggest_days: 30,
            vendor_suggest_based_on: "30_days",
            vendor_suggest_percent: 100,
        },
    });
    await runAllTimers();
    expect("span[name='suggest_total']").toHaveText("480.00");

    await click("input.o_PurchaseSuggestInput:eq(0)");
    await edit("7");
    await runAllTimers();
    lateTotal.resolve([]);
    await animationFrame();

    expect("span[name='suggest_total']").toHaveText("0.00");
});
