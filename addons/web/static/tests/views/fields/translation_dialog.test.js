// @ts-check

/**
 * Integration tests for the TranslationDialog component.
 *
 * Covers: translate button presence, dialog open/close lifecycle, per-language
 * row rendering, save payload (update_field_translations), and the user's
 * current-language pre-fill behaviour. All tests exercise the dialog via a
 * translatable char field in a form view.
 *
 * Module under test: fields/translation_dialog.js
 */

import { describe, expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import {
    contains,
    defineModels,
    fieldInput,
    fields,
    models,
    mountView,
    onRpc,
    serverState,
} from "@web/../tests/web_test_helpers";

// ---------------------------------------------------------------------------
// Shared model definitions
// ---------------------------------------------------------------------------

class Partner extends models.Model {
    _name = "res.partner";
    _inherit = [];

    name = fields.Char({ string: "Name" });
    description = fields.Text({ string: "Description" });

    _records = [{ id: 1, name: "yop", description: "a description" }];
}

defineModels([Partner]);

// ---------------------------------------------------------------------------
// Helper: standard two-language mock setup
// ---------------------------------------------------------------------------

function setupTranslationMocks({ translations = null, type = "char" } = {}) {
    onRpc("res.lang", "get_installed", () => [
        ["en_US", "English"],
        ["fr_BE", "French (Belgium)"],
    ]);

    onRpc("res.partner", "get_field_translations", () => [
        translations ?? [
            { lang: "en_US", source: "yop", value: "yop" },
            { lang: "fr_BE", source: "yop", value: "yop français" },
        ],
        { translation_type: type, translation_show_source: false },
    ]);
}

// ---------------------------------------------------------------------------
// Translate button presence
// ---------------------------------------------------------------------------

describe("translate button", () => {
    test("translate button appears on a translatable char field when multiLang is on", async () => {
        Partner._fields.name.translate = true;
        serverState.lang = "en_US";
        serverState.multiLang = true;

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });

        await contains("[name=name] input").click();
        expect(".o_field_char .btn.o_field_translate").toHaveCount(1, {
            message: "translate button should appear when the field is translatable",
        });
    });

    test("no translate button on a non-translatable char field", async () => {
        // translate is false by default
        serverState.lang = "en_US";
        serverState.multiLang = true;

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });

        expect(".o_field_char .btn.o_field_translate").toHaveCount(0);
    });
});

// ---------------------------------------------------------------------------
// Dialog open / close
// ---------------------------------------------------------------------------

describe("dialog open / close", () => {
    test("clicking the translate button opens TranslationDialog with correct title", async () => {
        Partner._fields.name.translate = true;
        serverState.lang = "en_US";
        serverState.multiLang = true;

        setupTranslationMocks();

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });

        // Focus the input first so the translate button becomes visible (CSS: focus-within)
        await contains("[name=name] input").click();
        await contains(".o_field_char .btn.o_field_translate").click();

        expect(".modal").toHaveCount(1, { message: "dialog should be open" });
        // Title format: "Translate: <field_string>"
        expect(".modal .modal-title").toHaveText("Translate: name");
    });

    test("clicking Close dismisses the dialog without calling update_field_translations", async () => {
        Partner._fields.name.translate = true;
        serverState.lang = "en_US";
        serverState.multiLang = true;

        setupTranslationMocks();
        onRpc("res.partner", "update_field_translations", () => {
            expect.step("update_field_translations");
        });

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });

        await contains("[name=name] input").click();
        await contains(".o_field_char .btn.o_field_translate").click();
        expect(".modal").toHaveCount(1);

        // Close without saving (use Discard footer button — works on desktop and mobile/fullscreen)
        await contains(".modal-footer .btn:not(.btn-primary)").click();

        expect(".modal").toHaveCount(0, { message: "dialog should be closed" });
        // update_field_translations must NOT have been called
        expect.verifySteps([]);
    });
});

// ---------------------------------------------------------------------------
// Language rows
// ---------------------------------------------------------------------------

describe("language rows", () => {
    test("dialog renders one input row per installed language", async () => {
        Partner._fields.name.translate = true;
        serverState.lang = "en_US";
        serverState.multiLang = true;

        setupTranslationMocks();

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });

        await contains("[name=name] input").click();
        await contains(".o_field_char .btn.o_field_translate").click();

        // Two languages → two translation rows
        expect(".modal .o_translation_dialog .translation").toHaveCount(2);

        const inputs = queryAll(".modal .o_translation_dialog .translation input");
        // Values should match the mock translations (sorted by language name)
        const values = inputs.map((el) => el.value);
        expect(values).toInclude("yop");
        expect(values).toInclude("yop français");
    });

    test("user's current language row is pre-filled with the record's current field value", async () => {
        Partner._fields.name.translate = true;
        serverState.lang = "en_US";
        serverState.multiLang = true;

        setupTranslationMocks();

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });

        // Change the field value in the form before opening translation dialog
        await fieldInput("name").edit("modified english");

        // Re-focus the input so the translate button becomes visible (CSS: focus-within)
        await contains("[name=name] input").click();
        await contains(".o_field_char .btn.o_field_translate").click();

        const inputs = queryAll(".modal .o_translation_dialog .translation input");
        // English (user's lang) row should show the current edited value
        const enInput = inputs.find((el) => el.value === "modified english");
        expect(enInput).not.toBe(undefined, {
            message:
                "the user's language row should reflect the current (unsaved) field value",
        });
    });
});

// ---------------------------------------------------------------------------
// Save payload
// ---------------------------------------------------------------------------

describe("save payload", () => {
    test("saving changed translations calls update_field_translations with correct args", async () => {
        Partner._fields.name.translate = true;
        serverState.lang = "en_US";
        serverState.multiLang = true;

        setupTranslationMocks();

        onRpc("res.partner", "update_field_translations", ({ args }) => {
            // args: [resIds, fieldName, translations]
            expect(args[0]).toEqual([1]);
            expect(args[1]).toBe("name");
            // French value was edited to "nouveau"
            expect(args[2].fr_BE).toBe("nouveau");
            expect.step("update_field_translations");
            return true;
        });

        await mountView({
            type: "form",
            resModel: "res.partner",
            resId: 1,
            arch: `<form><field name="name"/></form>`,
        });

        await contains("[name=name] input").click();
        await contains(".o_field_char .btn.o_field_translate").click();

        const inputs = queryAll(".modal .o_translation_dialog .translation input");
        // Find and edit the French row (value "yop français")
        const frInput = inputs.find((el) => el.value === "yop français");
        await contains(frInput).edit("nouveau");

        // Click the Save (primary) button in the dialog footer
        await contains(".modal footer .btn-primary").click();

        expect.verifySteps(["update_field_translations"]);
    });
});
