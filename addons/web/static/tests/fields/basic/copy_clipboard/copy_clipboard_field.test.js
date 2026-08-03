// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    contains,
    defineModels,
    fieldInput,
    fields,
    mockService,
    models,
    mountView,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    _name = "res.partner";

    char_field = fields.Char({
        string: "Char",
        default: "My little Char Value",
        trim: true,
    });

    url_field = fields.Char({ string: "Url" });

    _records = [
        {
            id: 1,
            char_field: "char value",
            url_field: "odoo.com",
        },
    ];

    _views = {
        form: `
            <form>
                <sheet>
                    <group>
                        <field name="char_field" widget="CopyClipboardChar"/>
                    </group>
                </sheet>
            </form>`,
    };
}

defineModels([Partner]);

test("Char Field: Copy to clipboard button", async () => {
    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
    });

    expect(".o_clipboard_button.o_btn_char_copy").toHaveCount(1);
});

test("Show copy button even on empty field", async () => {
    Partner._records.push({
        char_field: false,
    });

    await mountView({ type: "form", resModel: "res.partner", resId: 2 });

    expect(
        ".o_field_CopyClipboardChar[name='char_field'] .o_clipboard_button",
    ).toHaveCount(1);
});

test("Show copy button even on readonly empty field", async () => {
    Partner._fields.char_field.readonly = true;
    await mountView({
        type: "form",
        resModel: "res.partner",
        arch: `
        <form>
            <sheet>
                <group>
                    <field name="char_field" widget="CopyClipboardChar" />
                </group>
            </sheet>
        </form>`,
    });

    expect(
        ".o_field_CopyClipboardChar[name='char_field'] .o_clipboard_button",
    ).toHaveCount(1);
});

test("Display a tooltip on click", async () => {
    mockService("popover", {
        add(el, comp, params) {
            expect(params).toEqual({ tooltip: "Copied" });
            expect.step("copied tooltip");
            return async () => {};
        },
    });

    patchWithCleanup(navigator.clipboard, {
        async writeText(text) {
            expect.step(text);
        },
    });

    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
    });

    await expect(".o_clipboard_button.o_btn_char_copy").toHaveCount(1);
    await contains(".o_clipboard_button", { visible: false }).click();
    expect.verifySteps(["char value", "copied tooltip"]);
});

test("CopyClipboardButtonField in form view", async () => {
    patchWithCleanup(navigator.clipboard, {
        async writeText(text) {
            expect.step(text);
        },
    });

    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
        arch: `
            <form>
                <group>
                    <field name="char_field" widget="CopyClipboardButton"/>
                </group>
            </form>`,
    });

    expect(".o_field_widget[name=char_field] input").toHaveCount(0);
    expect(".o_clipboard_button.o_btn_char_copy").toHaveCount(1);
    expect(".o_clipboard_button.o_btn_char_copy").toHaveClass("btn-primary");
    expect(".o_clipboard_button.o_btn_char_copy").not.toHaveClass("btn-secondary");

    await contains(".o_clipboard_button.o_btn_char_copy").click();

    expect.verifySteps(["char value"]);
});

test("CopyClipboardButtonField with a secondary style", async () => {
    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
        arch: `
            <form>
                <group>
                    <field name="char_field" widget="CopyClipboardButton" options="{'btn_class': 'secondary'}"/>
                </group>
            </form>`,
    });

    expect(".o_field_widget[name=char_field] input").toHaveCount(0);
    expect(".o_clipboard_button.o_btn_char_copy").toHaveCount(1);
    expect(".o_clipboard_button.o_btn_char_copy").not.toHaveClass("btn-primary");
    expect(".o_clipboard_button.o_btn_char_copy").toHaveClass("btn-secondary");
});

test("CopyClipboardButtonField can be disabled", async () => {
    patchWithCleanup(navigator.clipboard, {
        async writeText(text) {
            expect.step(text);
        },
    });

    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
        arch: `
            <form>
                <sheet>
                    <group>
                        <field name="char_field" disabled="char_field == 'char value'" widget="CopyClipboardButton"/>
                        <field name="char_field" widget="char"/>
                    </group>
                </sheet>
            </form>`,
    });
    expect(".o_clipboard_button.o_btn_char_copy[disabled]").toHaveCount(1);
    await fieldInput("char_field").edit("another char value");
    expect(".o_clipboard_button.o_btn_char_copy[disabled]").toHaveCount(0);
});

const URL_ARCH = (attrs = "") => `
    <form>
        <group>
            <field name="url_field" widget="CopyClipboardURL" ${attrs}/>
        </group>
    </form>`;

test("CopyClipboardURLField wraps the url widget and uses the link icon", async () => {
    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
        arch: URL_ARCH(),
    });

    expect(".o_field_CopyClipboardURL[name=url_field] input").toHaveValue("odoo.com");
    expect(".o_clipboard_button.o_btn_char_copy").toHaveCount(1);
    expect(".o_clipboard_button.o_btn_char_copy .mx-1").toHaveClass("fa-link");
    expect(".o_clipboard_button.o_btn_char_copy .mx-1").not.toHaveClass("fa-clipboard");
});

test("CopyClipboardURLField copies the raw field value", async () => {
    patchWithCleanup(navigator.clipboard, {
        async writeText(text) {
            expect.step(text);
        },
    });

    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
        arch: URL_ARCH(),
    });

    await contains(".o_clipboard_button.o_btn_char_copy", { visible: false }).click();

    expect.verifySteps(["odoo.com"]);
});

test("CopyClipboardURLField readonly renders a link with a prefixed href", async () => {
    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
        arch: URL_ARCH(`readonly="1"`),
    });

    expect(".o_field_CopyClipboardURL a.o_form_uri").toHaveAttribute(
        "href",
        "http://odoo.com",
    );
    expect(".o_field_CopyClipboardURL a.o_form_uri").toHaveText("odoo.com");
    expect(".o_clipboard_button.o_btn_char_copy").toHaveCount(1);
});

test("CopyClipboardURLField website_path option leaves the href unprefixed", async () => {
    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 1,
        arch: URL_ARCH(`readonly="1" options="{'website_path': True}"`),
    });

    expect(".o_field_CopyClipboardURL a.o_form_uri").toHaveAttribute(
        "href",
        "odoo.com",
    );
});

test("CopyClipboardURLField shows the copy button on an empty url", async () => {
    Partner._records.push({ id: 3, url_field: false });

    await mountView({
        type: "form",
        resModel: "res.partner",
        resId: 3,
        arch: URL_ARCH(),
    });

    expect(".o_field_CopyClipboardURL[name=url_field] input").toHaveValue("");
    expect(".o_clipboard_button.o_btn_char_copy").toHaveCount(1);
});
