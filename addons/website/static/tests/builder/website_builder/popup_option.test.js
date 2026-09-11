import { setSelection } from "@html_editor/../tests/_helpers/selection";
import { insertText, redo, undo } from "@html_editor/../tests/_helpers/user_actions";
import { Plugin } from "@html_editor/plugin";
import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame, queryOne, waitFor } from "@odoo/hoot-dom";
import { contains } from "@web/../tests/web_test_helpers";
import {
    addPlugin,
    defineWebsiteModels,
    insertCategorySnippet,
    setupWebsiteBuilder,
} from "@website/../tests/builder/website_helpers";

defineWebsiteModels();

/**
 * @param {import("@odoo/hoot-dom").Target} target
 * @param {String} type
 * @param {Function} callback
 */
async function expectToTriggerEvent(target, type, callback) {
    const el = await waitFor(target);
    const step = `event '${type}' triggered on '${target}'`;
    el.addEventListener(type, () => expect.step(step), { once: true });
    const res = await callback();
    await expect.waitForSteps([step]);
    return res;
}

describe("Popup options: empty page before edit", () => {
    beforeEach(async () => {
        await setupWebsiteBuilder("", {
            loadIframeBundles: true,
            loadAssetsFrontendJS: true,
        });
    });
    test("dropping the popup snippet automatically displays it", async () => {
        await insertCategorySnippet({ group: "content", snippet: "s_popup" });
        expect(".o_add_snippet_dialog").toHaveCount(0);
        expect(":iframe .s_popup .modal").toHaveClass("show");
        expect(":iframe .s_popup .modal").toHaveStyle({ display: "block" });
    });
});
describe("Popup options: popup in page before edit", () => {
    let builder;
    beforeEach(async () => {
        addPlugin(
            class extends Plugin {
                static id = "ignore_d-none_on_s_popup";
                resources = {
                    savable_mutation_record_predicates: (record) =>
                        !(
                            record.target.matches?.(".s_popup") &&
                            record.className === "d-none"
                        ),
                };
            },
        );
        builder = await setupWebsiteBuilder(
            `<div class="s_popup o_snippet_invisible o_draggable" data-snippet="s_popup" data-name="Popup" id="sPopup" data-invisible="1">
                <div class="modal fade s_popup_middle modal_shown" style="background-color: var(--black-50)  !important; display: none;" data-show-after="5000" data-display="afterDelay" data-consents-duration="7" data-bs-focus="false" data-bs-backdrop="false" tabindex="-1" aria-label="Popup" aria-hidden="true">
                    <div class="modal-dialog d-flex">
                        <div class="modal-content oe_structure">
                            <div class="s_popup_close js_close_popup o_we_no_overlay o_not_editable" aria-label="Close" contenteditable="false">×</div>
                            <section><p>Popup content</p></section>
                        </div>
                    </div>
                </div>
            </div>`,
            {
                loadIframeBundles: true,
                loadAssetsFrontendJS: true,
            },
        );
    });

    test("editing a page with a popup snippet doesn't automatically display it", async () => {
        await advanceTime(5000);
        expect(":iframe .s_popup .modal").not.toBeVisible();
        expect(":iframe .s_popup").toHaveAttribute("data-invisible", "1");
    });

    test("closing s_popup with the X button updates the invisible elements panel", async () => {
        await expectToTriggerEvent(":iframe .s_popup .modal", "shown.bs.modal", () =>
            contains(".o_we_invisible_entry .fa-eye-slash").click(),
        );
        await waitFor(":iframe .s_popup .modal", { visible: true });
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye");
        expect(":iframe .s_popup .modal").toBeVisible();
        await expectToTriggerEvent(":iframe .s_popup .modal", "hidden.bs.modal", () =>
            contains(":iframe .s_popup div.js_close_popup").click(),
        );
        expect(":iframe .s_popup .modal").not.toBeVisible();
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye-slash");
        expect(builder.getEditor().shared.history.addStep()).toBe(false);
    });

    test("editing s_popup, then closing it, then undo show it again", async () => {
        const editor = builder.getEditor();
        await expectToTriggerEvent(":iframe .s_popup .modal", "shown.bs.modal", () =>
            contains(".o_we_invisible_entry .fa-eye-slash").click(),
        );
        await waitFor(":iframe .s_popup .modal", { visible: true });
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye");
        expect(":iframe .s_popup .modal").toBeVisible();
        setSelection({
            anchorNode: queryOne(":iframe .s_popup section p"),
            anchorOffset: 0,
        });
        await insertText(editor, "Other content");
        await expectToTriggerEvent(":iframe .s_popup .modal", "hidden.bs.modal", () =>
            contains(":iframe .s_popup div.js_close_popup").click(),
        );
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye-slash");
        expect(":iframe .s_popup .modal").not.toBeVisible();
        expect(editor.shared.history.canUndo()).toBe(true);
        await expectToTriggerEvent(":iframe .s_popup .modal", "shown.bs.modal", () =>
            undo(editor),
        );
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye");
        expect(":iframe .s_popup .modal").toBeVisible();
    });

    test("undoing something on a target outside s_popup closes it", async () => {
        await insertCategorySnippet({ group: "intro", snippet: "s_cover" });
        expect(".o_add_snippet_dialog").toHaveCount(0);
        await contains(":iframe .s_cover").click();
        await contains("button:contains(Grid)").click();
        await expectToTriggerEvent(":iframe .s_popup .modal", "shown.bs.modal", () =>
            contains(".o_we_invisible_entry .fa-eye-slash").click(),
        );
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye");
        await expectToTriggerEvent(":iframe .s_popup .modal", "hidden.bs.modal", () =>
            undo(builder.getEditor()),
        );
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye-slash");
    });

    test("emptied s_popup are removed and the options are updated correctly", async () => {
        const editor = builder.getEditor();
        await expectToTriggerEvent(":iframe .s_popup .modal", "shown.bs.modal", () =>
            contains(".o_we_invisible_entry .fa-eye-slash").click(),
        );
        await waitFor(":iframe .s_popup .modal", { visible: true });
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye");
        expect(":iframe .s_popup .modal").toBeVisible();

        await contains(":iframe section p:contains('Popup content')").click();
        await contains("div[data-container-title='Block'] button.fa-trash").click();
        expect(":iframe .s_popup").toHaveCount(0);
        expect("div[data-container-title='Block']").toHaveCount(0);

        expect(editor.shared.history.canUndo()).toBe(true);
        undo(editor);
        await animationFrame();
        expect(":iframe .s_popup").toHaveCount(1);
        expect("div[data-container-title='Block']").toHaveCount(1);

        expect(editor.shared.history.canRedo()).toBe(true);
        redo(editor);
        await animationFrame();
        expect(":iframe .s_popup").toHaveCount(0);
        expect("div[data-container-title='Block']").toHaveCount(0);

        expect(editor.shared.history.canUndo()).toBe(true);
        undo(editor);
        await animationFrame();
        expect(":iframe .s_popup").toHaveCount(1);
        expect("div[data-container-title='Block']").toHaveCount(1);

        contains(".o_we_invisible_entry .fa-eye").click();
        await animationFrame();
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye-slash");

        expect(editor.shared.history.canRedo()).toBe(true);
        redo(editor);
        await animationFrame();
        expect(":iframe .s_popup").toHaveCount(0);
        expect("div[data-container-title='Block']").toHaveCount(0);

        expect(editor.shared.history.canUndo()).toBe(true);
        undo(editor);
        await animationFrame();
        expect(":iframe .s_popup").toHaveCount(1);
        expect("div[data-container-title='Block']").toHaveCount(1);
        expect(".o_we_invisible_entry .fa").toHaveClass("fa-eye");
    });
});
