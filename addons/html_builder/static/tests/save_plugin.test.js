import { addBuilderOption, setupHTMLBuilder } from "@html_builder/../tests/helpers";
import { BaseOptionComponent } from "@html_builder/core/utils";
import { expect, test, describe } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { xml } from "@odoo/owl";
import { contains, makeServerError, onRpc } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

function addDirtyingOption() {
    addBuilderOption(
        class extends BaseOptionComponent {
            static selector = ".test-options-target";
            static template = xml`<BuilderButton classAction="'x'">X</BuilderButton>`;
        }
    );
}

test("a validation error on save is reported, not thrown", async () => {
    onRpc("ir.ui.view", "save", () => {
        expect.step("save");
        throw makeServerError({ message: "A Validation Error", type: "ValidationError" });
    });
    addDirtyingOption();
    const { getEditor } = await setupHTMLBuilder(`<p class="test-options-target">b</p>`);
    await contains(":iframe .test-options-target").click();
    await contains("[data-class-action='x']").click();

    expect(":iframe .o_dirty").toHaveCount(1);
    await getEditor().shared.savePlugin.save();
    await animationFrame();

    expect.verifySteps(["save"]);
    expect(".o_notification").toHaveCount(1);
    expect(".o_notification_content").toHaveText(
        "One or more fields were not valid. Your changes were not saved. Correct them and save again."
    );
});

test("an error which is not a validation error still propagates", async () => {
    onRpc("ir.ui.view", "save", () => {
        expect.step("save");
        throw makeServerError({ message: "Not A Validation Error" });
    });
    addDirtyingOption();
    const { getEditor } = await setupHTMLBuilder(`<p class="test-options-target">b</p>`);
    await contains(":iframe .test-options-target").click();
    await contains("[data-class-action='x']").click();

    await expect(getEditor().shared.savePlugin.save()).rejects.toThrow();
    expect.verifySteps(["save"]);
    expect(".o_notification").toHaveCount(0);
});
