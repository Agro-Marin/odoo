// @ts-check

import { expect, test } from "@odoo/hoot";
import { Deferred, press, waitFor, waitUntil } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { onWillStart } from "@odoo/owl";
import {
    contains,
    defineModels,
    fields,
    mockService,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { DynamicPlaceholderPopover } from "@web/fields/dynamic_placeholder_popover";

class Partner extends models.Model {
    char = fields.Char();
    placeholder = fields.Char({ default: "partner" });
    date_end = fields.Datetime({ string: "Deadline" });
    image = fields.Binary({ string: "Image" });
    note = fields.Html({ string: "Note" });
    product_id = fields.Many2one({ relation: "product" });
    properties = fields.Properties({
        string: "Properties",
        definition_record: "product_id",
        definition_record_field: "properties_definitions",
    });

    _records = [
        {
            id: 1,
            char: "yop",
            product_id: 37,
            properties: { f80b6fb58d0d4c72: 3, f424643eee1f3655: 41 },
        },
        { id: 2, char: "blip", product_id: false },
        { id: 4, char: "abc", product_id: 41 },
    ];

    _views = {
        form: `
            <form>
                <field name="placeholder" invisible="1"/>
                <sheet>
                    <group>
                        <field
                            name="char"
                            options="{
                                'dynamic_placeholder': true,
                                'dynamic_placeholder_model_reference_field': 'placeholder'
                            }"
                        />
                    </group>
                </sheet>
            </form>
        `,
    };
}

class Product extends models.Model {
    name = fields.Char({ string: "Product Name" });
    properties_definitions = fields.PropertiesDefinition();

    _records = [
        {
            id: 37,
            name: "xphone",
            properties_definitions: [
                { name: "f80b6fb58d0d4c72", type: "integer", string: "prop 1" },
                {
                    name: "f424643eee1f3655",
                    type: "many2one",
                    string: "prop 2",
                    comodel: "product",
                },
            ],
        },
        { id: 41, name: "xpad" },
    ];
}

defineModels([Partner, Product]);

onRpc("has_group", () => true);
onRpc("mail_allowed_qweb_expressions", () => []);

test("dynamic placeholder close with click out", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1 });

    await contains(".o_field_char input").edit("#", { confirm: false });
    expect(".o_model_field_selector_popover").toHaveCount(1);
    await contains(".o_content").click();
    expect(".o_model_field_selector_popover").toHaveCount(0);
    await contains(".o_field_char input").edit("#", { confirm: false });
    await contains(".o_model_field_selector_popover_item_relation").click();
    await contains(".o_content").click();
    expect(".o_model_field_selector_popover").toHaveCount(0);
});

test("dynamic placeholder close with escape", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1 });

    await contains(".o_field_char input").edit("#", { confirm: false });
    expect(".o_model_field_selector_popover").toHaveCount(1);
    press("Escape");
    await animationFrame();
    expect(".o_model_field_selector_popover").toHaveCount(0);
    await contains(".o_field_char input").edit("#", { confirm: false });
    await contains(".o_model_field_selector_popover_item_relation").click();
    press("Escape");
    await animationFrame();
    expect(".o_model_field_selector_popover").toHaveCount(0);
});

test("dynamic placeholder close when clicking on the cross", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1 });

    await contains(".o_field_char input").edit("#", { confirm: false });
    expect(".o_model_field_selector_popover").toHaveCount(1);
    await contains(".o_model_field_selector_popover_close").click();
    expect(".o_model_field_selector_popover").toHaveCount(0);
    await contains(".o_field_char input").edit("#", { confirm: false });
    await contains(".o_model_field_selector_popover_item_relation").click();
    await contains(".o_model_field_selector_popover_close").click();
    expect(".o_model_field_selector_popover").toHaveCount(0);
});

test("dynamic placeholder properties", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1 });

    await contains(".o_field_char input").edit("#", { confirm: false });
    expect(".o_model_field_selector_popover").toHaveCount(1);
    expect(
        ".o_model_field_selector_popover .o_model_field_selector_popover_item_name:contains('Properties')",
    ).toHaveCount(1);

    await contains(
        ".o_model_field_selector_popover .o_model_field_selector_popover_item_name:contains('Properties') + .o_model_field_selector_popover_item_relation",
    ).click();
    expect(
        ".o_model_field_selector_popover .o_model_field_selector_popover_item_name:contains('prop 1 (xphone)')",
    ).toHaveCount(1);
    expect(
        ".o_model_field_selector_popover .o_model_field_selector_popover_item_name:contains('prop 2 (xphone)')",
    ).toHaveCount(1);

    await contains(
        ".o_model_field_selector_popover .o_model_field_selector_popover_item_name:contains('prop 2 (xphone)') + .o_model_field_selector_popover_item_relation",
    ).click();
    expect(
        ".o_model_field_selector_popover .o_model_field_selector_popover_item_name:contains('Created on')",
    ).toHaveCount(1);

    await contains(
        ".o_model_field_selector_popover .o_model_field_selector_popover_item_name:contains('Product Name')",
    ).click();

    await contains(".o_model_field_selector_popover button:contains('Insert')").click();

    const value = /** @type {HTMLInputElement} */ (
        document.querySelector(".o_field_placeholder")
    ).value.trim();
    expect(value).toBe(
        `{{object.properties.get("f424643eee1f3655", env['product']).name}}`,
    );
    expect(".o_form_status_indicator_buttons").toBeVisible({
        message: "inserting a placeholder must mark the field dirty",
    });
});

test("opening a second popover is not blocked by the first", async () => {
    // Asserted as a non-editor: the allow-list only constrains those, and the
    // popover no longer spends the RPC on a user it cannot constrain.
    onRpc("has_group", () => false);
    const def = new Deferred();
    let willStarts = 0;
    patchWithCleanup(DynamicPlaceholderPopover.prototype, {
        setup() {
            super.setup();
            onWillStart(async () => {
                willStarts++;
                await def;
            });
        },
    });

    onRpc("partner", "mail_allowed_qweb_expressions", async () => {
        expect.step("mail_allowed_qweb_expressions");
        return [];
    });

    await mountView({ type: "form", resModel: "partner", resId: 1 });
    await contains(".o_field_char input").edit("#", { confirm: false });
    await waitUntil(() => willStarts === 1);
    await contains(".o_field_char input").edit("#", { confirm: false });
    await waitUntil(() => willStarts === 2);

    def.resolve();
    await waitFor(".o_model_field_selector_popover");
    expect(willStarts).toBe(2);
    expect.verifySteps([]);
});

test("a template editor does not pay for an allow-list that cannot constrain them", async () => {
    onRpc("partner", "mail_allowed_qweb_expressions", () => {
        expect.step("mail_allowed_qweb_expressions");
        return [];
    });
    await mountView({ type: "form", resModel: "partner", resId: 1 });
    await contains(".o_field_char input").edit("#", { confirm: false });
    expect(".o_model_field_selector_popover").toHaveCount(1);
    expect.verifySteps([]);
});

test("the model reference field is loaded without the view naming it", async () => {
    onRpc("web_read", ({ kwargs }) => {
        expect(Object.keys(kwargs.specification)).toInclude("placeholder");
    });
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <field name="char" options="{
                    'dynamic_placeholder': true,
                    'dynamic_placeholder_model_reference_field': 'placeholder'
                }"/>
            </form>`,
    });

    await contains(".o_field_char input").edit("#", { confirm: false });
    expect(".o_model_field_selector_popover").toHaveCount(1);
});

test("a datetime is localised in a subject, as it already was in a body", async () => {
    // The popover has always sent the field type as a third argument; the
    // char/text path declared two parameters and dropped it, so the same field
    // rendered as `08/17/2026 09:43 PM` in a body and as
    // `2026-08-18 03:43:39.788945` in a subject.
    onRpc("mail_get_partner_fields", () => ["product_id"]);
    await mountView({ type: "form", resModel: "partner", resId: 1 });
    await contains(".o_field_char input").edit("#", { confirm: false });
    await contains(
        ".o_model_field_selector_popover_item_name:contains('Deadline')",
    ).click();
    await contains(".o_model_field_selector_popover button:contains('Insert')").click();
    await animationFrame();
    expect(".o_field_char input").toHaveValue(
        " {{format_datetime(object.date_end, tz=object.product_id.tz)}}",
    );
});

test("a default value carrying the placeholder terminator survives", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1 });
    await contains(".o_field_char input").edit("#", { confirm: false });
    await contains(
        ".o_model_field_selector_popover_item_name:contains('Char')",
    ).click();
    await contains(".o_model_field_selector_default_value_input input").edit(
        "see }} here",
        { confirm: false },
    );
    await contains(".o_model_field_selector_popover button:contains('Insert')").click();
    expect(".o_field_char input").toHaveValue(" {{object.char ||| see \\}\\} here}}");
});

test("fields no placeholder can render are not offered", async () => {
    await mountView({ type: "form", resModel: "partner", resId: 1 });
    await contains(".o_field_char input").edit("#", { confirm: false });
    const names = [
        ...document.querySelectorAll(".o_model_field_selector_popover_item_name"),
    ].map((el) => el.textContent.trim());
    expect(names).not.toInclude("Image", {
        message: "a binary renders as the repr of its bytes",
    });
    expect(names).not.toInclude("Note", {
        message: "an html field reaches a subject as literal tags",
    });
    expect(names).toInclude("Deadline");
});

test("a non-editor is offered only what the server will accept", async () => {
    // The allow-list holds paths; the picker used to test the path and the
    // server the expression, so a datetime could be offered and then refused
    // on save. Both sides now judge the expression.
    onRpc("has_group", () => false);
    mockService("allowed_qweb_expressions", () => async () => [
        "object.char",
        "object.date_end",
    ]);
    await mountView({ type: "form", resModel: "partner", resId: 1 });
    await contains(".o_field_char input").edit("#", { confirm: false });
    const names = [
        ...document.querySelectorAll(".o_model_field_selector_popover_item_name"),
    ].map((el) => el.textContent.trim());
    expect(names).toEqual(["Char"], {
        message:
            "`object.date_end` is allow-listed but the placeholder would be " +
            "`format_datetime(...)`, which is not",
    });
});
