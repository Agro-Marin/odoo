import { expect, test } from "@odoo/hoot";
import { press, runAllTimers } from "@odoo/hoot-dom";
import { Deferred } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import { SaleOrderLineProductField } from "@sale/js/sale_product_field";
import {
    clickSave,
    Command,
    contains,
    defineModels,
    fields,
    makeMockServer,
    models,
    mountView,
    onRpc,
    serverState,
} from "@web/../tests/web_test_helpers";
import { Mutex } from "@web/core/utils/concurrency";
import { RelationalModel } from "@web/model/relational_model";

import { saleModels } from "./sale_test_helpers.js";

class SaleOrderLine extends saleModels.SaleOrderLine {
    product_template_attribute_value_ids = fields.Many2many({
        string: "Product template attributes values",
        relation: "product.template.attribute.value",
    });
}

class ProductTemplateAttributeValue extends models.Model {
    _name = "product.template.attribute.value";

    name = fields.Char();
}

defineModels({ ...saleModels, SaleOrderLine, ProductTemplateAttributeValue });

saleModels.SaleOrder._views.form = /* xml */ `
    <form>
        <field name="line_ids" widget="sol_o2m" mode="list">
            <list editable="bottom">
                <field name="product_id" widget="sol_product_many2one"/>
                <field name="product_template_id" widget="sol_product_many2one"/>
                <field name="name" widget="sol_text"/>
            </list>
        </field>
    </form>
`;

test.tags("desktop");
test("pressing tab with incomplete text will create a product", async () => {
    onRpc(({ method }) => {
        expect.step(method);
    });
    await mountView({
        type: "form",
        resModel: "sale.order",
        arch: `
                <form>
                    <sheet>
                        <field name="line_ids">
                            <list editable="bottom">
                                <field name="product_template_id" widget="sol_product_many2one"/>
                                <field name="product_id" optional="hide"/>
                                <field name="name" optional="show"/>
                            </list>
                        </field>
                    </sheet>
                </form>`,
    });

    // add a line and enter new product name
    await contains(".o_field_x2many_list .o_field_x2many_list_row_add a").click();
    await contains("[name='product_template_id'] input").edit("new product");
    await press("tab");
    await runAllTimers();
    expect.verifySteps([
        "get_views",
        "onchange",
        "onchange",
        "web_name_search",
        "name_create",
        "get_single_product_variant",
    ]);
});

test("Hide product name if its not translated", async () => {
    const { env } = await makeMockServer();
    const product = env["product.product"][0];
    const soId = env["sale.order"].create({
        partner_id: serverState.partnerId,
        line_ids: [
            Command.create({
                product_id: product.id,
                name: [product.name, "A description"].join("\n"),
                product_name_translated: "Produit de test",
            }),
        ],
    });
    await mountView({
        type: "form",
        resModel: "sale.order",
        resId: soId,
    });

    expect(".o_field_product_label_section_and_note_cell .o_input").toHaveText(
        "A description",
    );
});

test("If translated product name already in the SOL name, should not hide the translated product name", async () => {
    const { env } = await makeMockServer();
    const translatedProductName = "Produit de test";
    const product = env["product.product"][0];
    const soId = env["sale.order"].create({
        partner_id: serverState.partnerId,
        line_ids: [
            Command.create({
                product_id: product.id,
                name: [product.name, translatedProductName, "A description"].join("\n"),
                product_name_translated: translatedProductName,
            }),
        ],
    });
    await mountView({
        type: "form",
        resModel: "sale.order",
        resId: soId,
    });

    expect(".o_field_product_label_section_and_note_cell .o_input").toHaveText(
        [translatedProductName, "A description"].join("\n"),
    );
});

test("Editing the description shouldn't show the translated product name", async () => {
    const { env } = await makeMockServer();
    const translatedProductName = "Produit de test";
    const product = env["product.product"][0];
    const soId = env["sale.order"].create({
        partner_id: serverState.partnerId,
        line_ids: [
            Command.create({
                product_id: product.id,
                name: [product.name, "something wrong"].join("\n"),
                product_name_translated: translatedProductName,
            }),
        ],
    });
    const [so] = env["sale.order"].browse(soId);
    const [sol] = env["sale.order.line"].browse(so.line_ids);
    await mountView({
        type: "form",
        resModel: "sale.order",
        resId: soId,
    });
    await contains(".o_field_product_label_section_and_note_cell").click();
    await contains(".o_field_product_label_section_and_note_cell textarea").edit(
        "A description",
    );
    await clickSave();

    expect(".o_field_product_label_section_and_note_cell .o_input").toHaveText(
        "A description",
    );
    expect(sol.name).toBe([translatedProductName, "A description"].join("\n"));
});

test("No description should be shown if there does not exist one apart from the product name", async () => {
    const { env } = await makeMockServer();
    const translatedProductName = "Produit de test";
    const product = env["product.product"][0];
    const soId = env["sale.order"].create({
        partner_id: serverState.partnerId,
        line_ids: [
            Command.create({
                product_id: product.id,
                name: product.name,
                product_name_translated: translatedProductName,
            }),
        ],
    });
    await mountView({
        type: "form",
        resModel: "sale.order",
        resId: soId,
    });

    expect(".o_field_product_label_section_and_note_cell .o_input").not.toBeVisible();
});

test("No description should be shown if there does not exist one apart from the translated product name", async () => {
    const { env } = await makeMockServer();
    const translatedProductName = "Produit de test";
    const product = env["product.product"][0];
    const soId = env["sale.order"].create({
        partner_id: serverState.partnerId,
        line_ids: [
            Command.create({
                product_id: product.id,
                name: translatedProductName,
                product_name_translated: translatedProductName,
            }),
        ],
    });
    await mountView({
        type: "form",
        resModel: "sale.order",
        resId: soId,
    });

    expect(".o_field_product_label_section_and_note_cell .o_input").not.toBeVisible();
});

test("the product cascade holds the model until the combo configurator is done", async () => {
    // `_selectProduct` runs the cascade inside `trackCompoundUpdate` so that a save,
    // reload or `leaveEditMode` cannot settle on a half-applied line. That only holds if
    // `_onProductTemplateUpdate` awaits the configurator it opens: on the
    // all-preselected combo path the configurator skips its dialog and writes
    // `product_qty` / `selected_combo_items` itself. Started but not awaited, the model
    // reported the line settled while it held nothing but `product_id`.
    const model = Object.create(RelationalModel.prototype);
    model._compoundUpdates = new Set();
    model.mutex = new Mutex();
    model.bus = new EventBus();
    model.config = { resModel: "sale.order" };

    const comboWork = new Deferred();
    const writes = [];
    const field = Object.create(SaleOrderLineProductField.prototype);
    field.context = {};
    field.orm = {
        call: async () => ({
            product_id: 7,
            product_name: "Combo",
            is_combo: true,
            has_optional_products: false,
        }),
    };
    field.props = {
        record: {
            model,
            data: { product_template_id: { id: 3 }, product_id: { id: false } },
            update: async (vals) => writes.push(Object.keys(vals).join("+")),
        },
    };
    field._openComboConfigurator = async () => {
        await comboWork;
        writes.push("product_qty+selected_combo_items");
    };

    const cascade = model.trackCompoundUpdate(async () => {
        await field._onProductTemplateUpdate();
    });

    // Race the settle against the combo work. Whichever wins names the behaviour:
    // "askChanges-first" is the bug (the model declared the line settled while the
    // configurator was still writing to it), "combo-first" is the invariant.
    const winner = await Promise.race([
        model._askChanges().then(() => "askChanges-first"),
        comboWork.then(() => "combo-first"),
        // Nothing else may resolve the race: give the settle every chance to win.
        new Promise((resolve) => setTimeout(() => resolve("nothing-settled"), 0)),
    ]);
    expect(winner).not.toBe("askChanges-first");
    expect(writes).toEqual(["product_id"]);

    comboWork.resolve();
    await cascade;
    expect(writes).toEqual(["product_id", "product_qty+selected_combo_items"]);
});
