import { DYNAMIC_PLACEHOLDER_PLUGINS } from "@html_editor/backend/plugin_sets";
import { DynamicPlaceholderPlugin } from "@html_editor/others/dynamic_placeholder_plugin";
import { MAIN_PLUGINS } from "@html_editor/plugin_sets";
import { expect, test } from "@odoo/hoot";
import { click, manuallyDispatchProgrammaticEvent, press } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    contains,
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";

import { setupEditor } from "./_helpers/editor.js";
import { insertText } from "./_helpers/user_actions.js";

class ResUsers extends models.Model {
    _name = "res.users";
    _records = [
        {
            id: serverState.userId,
        },
    ];
}

class Template extends models.Model {
    _name = "template";
    body = fields.Html();
    model = fields.Char();
    _records = [{ id: 1, body: "<p>[]</p>", model: false }];
}

onRpc("has_group", () => true);
onRpc("mail_allowed_qweb_expressions", () => []);
defineModels([ResUsers, Template]);

test("inserted value from dynamic placeholder should contain the data-oe-t-inline attribute", async () => {
    const { editor } = await setupEditor("<p>test[]</p>", {
        config: {
            Plugins: [...MAIN_PLUGINS, ...DYNAMIC_PLACEHOLDER_PLUGINS],
            dynamicPlaceholderResModel: "res.users",
        },
    });
    onRpc("res.users", "mail_get_partner_fields", () => ["partner_id"]);

    await insertText(editor, "/dynamicplaceholder");
    await press("Enter");
    await animationFrame();

    const popover_search_input = document.querySelector(
        ".o_model_field_selector_popover_search .o_input",
    );
    popover_search_input.value = "displayname";
    await manuallyDispatchProgrammaticEvent(popover_search_input, "input", {
        inputType: "insertText",
    });
    await press("Enter");
    await animationFrame();

    const default_value_input = document.querySelector(
        ".o_model_field_selector_default_value_input .o_input",
    );
    await click(default_value_input);
    await manuallyDispatchProgrammaticEvent(default_value_input, "input", {
        inputType: "insertText",
    });
    default_value_input.value = "Test";
    await manuallyDispatchProgrammaticEvent(default_value_input, "input", {
        inputType: "insertText",
    });
    await press("Enter");
    await animationFrame();

    expect("t[data-oe-t-inline]").toHaveCount(1);
});

test("a model chosen after the editor mounted still reaches the picker", async () => {
    const pushed = [];
    patchWithCleanup(DynamicPlaceholderPlugin.prototype, {
        updateDphDefaultModel(resModel) {
            super.updateDphDefaultModel(resModel);
            pushed.push(resModel);
        },
    });
    await mountView({
        type: "form",
        resModel: "template",
        resId: 1,
        arch: `
            <form>
                <field name="model"/>
                <field name="body" widget="html" options="{
                    'dynamic_placeholder': true,
                    'dynamic_placeholder_model_reference_field': 'model'
                }"/>
            </form>`,
    });

    await contains("[name='model'] input").edit("res.users");
    await animationFrame();

    expect(pushed.at(-1)).toBe("res.users");
});
