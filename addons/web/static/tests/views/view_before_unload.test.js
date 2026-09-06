// @ts-check
import { expect, test } from "@odoo/hoot";
import { click, queryOne } from "@odoo/hoot-dom";
import { animationFrame, tick } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountView,
    webModels,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    name = fields.Char();
    _records = [{ id: 1, name: "first" }];
}
defineModels([...Object.values(webModels), Partner]);

// Two dispatches in one task would join the still-active urgent save of the
// first and skip the flush, which a real browser never does.
async function beforeUnloadPrompts() {
    const ev = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(ev);
    await tick();
    return ev.defaultPrevented;
}

test("form: an unblurred input on a new record prompts before unload", async () => {
    await mountView({
        resModel: "partner",
        type: "form",
        arch: `<form><field name="name"/></form>`,
    });
    expect(await beforeUnloadPrompts()).toBe(false);
    /** @type {HTMLInputElement} */ (
        queryOne(".o_field_widget[name=name] input")
    ).value = "typed but never blurred";
    expect(await beforeUnloadPrompts()).toBe(true);
});

test("editable list: an unblurred new row prompts before unload", async () => {
    await mountView({
        resModel: "partner",
        type: "list",
        arch: `<list editable="bottom"><field name="name"/></list>`,
    });
    expect(await beforeUnloadPrompts()).toBe(false);
    await click(".o_list_button_add");
    await animationFrame();
    expect(await beforeUnloadPrompts()).toBe(false);
    /** @type {HTMLInputElement} */ (
        queryOne(".o_selected_row [name=name] input")
    ).value = "new";
    expect(await beforeUnloadPrompts()).toBe(true);
});
