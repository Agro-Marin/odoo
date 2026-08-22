// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { FormController } from "@web/views/form/form_controller";

/** @type {any} */
let controller;
function captureController() {
    controller = null;
    patchWithCleanup(FormController.prototype, {
        setup() {
            super.setup();
            controller = this;
        },
    });
}

class Order extends models.Model {
    _name = "order";
    kind = fields.Selection({
        selection: [
            ["goods", "Goods"],
            ["service", "Service"],
        ],
    });
    qty = fields.Integer();
    note = fields.Char();
    _records = [{ id: 1, kind: "goods", qty: 3, note: "n" }];
}

defineModels([Order]);

const ARCH = `
    <form>
        <field name="kind"/>
        <field name="note"/>
        <field name="qty" invisible="kind == 'service'"/>
    </form>`;

test("a widget-invalid field hidden by a modifier stops blocking the save", async () => {
    onRpc("order", "web_save", () => expect.step("web_save"));
    captureController();
    await mountView({ type: "form", resModel: "order", resId: 1, arch: ARCH });
    const record = controller.model.root;

    await contains("[name=qty] input").edit("not-a-number");
    await animationFrame();
    expect([...record._invalidFields]).toEqual(["qty"], {
        message: "the widget rejected the input, so the field is invalid",
    });
    expect([...record._unsetRequiredFields]).toEqual([]);

    await record.update({ kind: "service" });
    await animationFrame();

    expect("[name=qty] input").toHaveCount(0);
    expect([...record._invalidFields]).toEqual([], {
        message: "a field the user cannot see cannot be corrected by them",
    });

    await contains(".o_form_button_save").click();
    await animationFrame();
    expect.verifySteps(["web_save"]);
    expect(record.dirty).toBe(false);
});

test("the value saved is the last one that parsed, not the rejected text", async () => {
    /** @type {any} */
    let written;
    onRpc("order", "web_save", ({ args }) => {
        written = args[1];
    });
    captureController();
    await mountView({ type: "form", resModel: "order", resId: 1, arch: ARCH });
    const record = controller.model.root;

    await contains("[name=qty] input").edit("12");
    await animationFrame();
    await contains("[name=qty] input").edit("not-a-number");
    await animationFrame();
    await record.update({ kind: "service" });
    await animationFrame();
    await contains(".o_form_button_save").click();
    await animationFrame();

    expect(written).not.toBe(undefined, { message: "web_save must have run" });
    expect(written.qty).toBe(12);
    expect(written.kind).toBe("service");
});

test("a VISIBLE widget-invalid field still blocks the save", async () => {
    onRpc("order", "web_save", () => expect.step("web_save"));
    captureController();
    await mountView({ type: "form", resModel: "order", resId: 1, arch: ARCH });
    const record = controller.model.root;

    await contains("[name=qty] input").edit("not-a-number");
    await animationFrame();
    await contains(".o_form_button_save").click();
    await animationFrame();

    expect.verifySteps([]);
    expect([...record._invalidFields]).toEqual(["qty"]);
});

test("checkValidity({ silent: true }) still writes nothing", async () => {
    captureController();
    await mountView({ type: "form", resModel: "order", resId: 1, arch: ARCH });
    const record = controller.model.root;

    await contains("[name=qty] input").edit("not-a-number");
    await animationFrame();
    await record.update({ kind: "service" });
    record._setInvalidFieldFlag("qty");

    record._checkValidity({ silent: true });

    expect([...record._invalidFields]).toEqual(["qty"]);
});
