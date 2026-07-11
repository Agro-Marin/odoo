// @ts-check

/**
 * Integration tests for the Many2XAutocomplete component.
 *
 * Covers the dropdown suggestion-building logic: search RPC calls, quick-create,
 * create-and-edit, search-more, and access-restriction props (no_create,
 * no_quick_create). The component is exercised through a many2one field in a
 * form view — it cannot be mounted in isolation because it uses OWL service hooks.
 *
 * Module under test: fields/relational/many2x_autocomplete.js
 */

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import {
    clickFieldDropdown,
    clickFieldDropdownItem,
    contains,
    defineModels,
    fields,
    makeServerError,
    models,
    mountView,
    onRpc,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

// Shared model definitions

class Partner extends models.Model {
    name = fields.Char();
    product_id = fields.Many2one({ relation: "product", string: "Product" });

    _records = [{ id: 1, name: "first record", product_id: 37 }];
}

class Product extends models.Model {
    name = fields.Char({ string: "Product Name" });

    _records = [
        { id: 37, name: "xphone" },
        { id: 41, name: "xpad" },
    ];

    // Required for SelectCreateDialog (search more)
    _views = {
        form: `<form><field name="name"/></form>`,
        list: `<list><field name="name"/></list>`,
        search: `<search/>`,
    };
}

// SelectCreateDialog internally queries res.users (for filters/favorites)
class ResUsers extends models.Model {
    _name = "res.users";
    name = fields.Char();

    _records = [{ id: 1, name: "Admin" }];
}

defineModels([Partner, Product, ResUsers]);

// web_name_search — search RPC

describe("search RPC", () => {
    test("typing triggers web_name_search with the typed text", async () => {
        onRpc("product", "web_name_search", ({ kwargs }) => {
            expect(kwargs.name).toBe("xp");
            expect.step("web_name_search");
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await contains(".o_field_widget[name=product_id] input").edit("xp", {
            confirm: false,
        });
        await runAllTimers();

        expect.verifySteps(["web_name_search"]);
    });

    test("dropdown shows matching records returned by web_name_search", async () => {
        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await clickFieldDropdown("product_id");
        await runAllTimers();

        // Both server records should appear in the dropdown (verified below)
        expect(
            ".o_field_widget[name=product_id] .o-autocomplete--dropdown-item:contains(xphone)",
        ).toHaveCount(1);
        expect(
            ".o_field_widget[name=product_id] .o-autocomplete--dropdown-item:contains(xpad)",
        ).toHaveCount(1);
    });
});

// Create restrictions — no_create, no_quick_create

describe("create restrictions", () => {
    test("no_create hides both quick-create and create-and-edit options", async () => {
        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id" options="{'no_create': True}"/></form>`,
        });

        await contains(".o_field_widget[name=product_id] input").edit("newprod", {
            confirm: false,
        });
        await runAllTimers();

        // Neither create option should be rendered
        expect(".o_m2o_dropdown_option_create").toHaveCount(0);
        expect(".o_m2o_dropdown_option_create_edit").toHaveCount(0);
    });

    test("no_quick_create hides quick-create but keeps create-and-edit", async () => {
        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id" options="{'no_quick_create': True}"/></form>`,
        });

        await contains(".o_field_widget[name=product_id] input").edit("brand", {
            confirm: false,
        });
        await runAllTimers();

        expect(".o_m2o_dropdown_option_create").toHaveCount(0, {
            message: 'Quick-create "Create ..." should be absent',
        });
        expect(".o_m2o_dropdown_option_create_edit").toHaveCount(1, {
            message: '"Create and edit..." should still be present',
        });
    });
});

// Quick create — calls name_create and updates the field

describe("quick create", () => {
    test("selecting Create option calls name_create and sets the field value", async () => {
        onRpc("product", "name_create", ({ args }) => {
            expect(args[0]).toBe("brand new");
            expect.step("name_create");
            return [99, args[0]];
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await contains(".o_field_widget[name=product_id] input").edit("brand new", {
            confirm: false,
        });
        await runAllTimers();
        await clickFieldDropdownItem("product_id", 'Create "brand new"');

        expect.verifySteps(["name_create"]);
        expect(".o_field_widget[name=product_id] input").toHaveValue("brand new");
    });
});

// Empty-search memoization — skips redundant RPCs but must be invalidated
// whenever a record can come into existence (quick create, dialog create)

describe("empty-search memoization", () => {
    const INPUT_SELECTOR = ".o_field_widget[name=product_id] input";
    // Record suggestions, excluding create/search-more action options
    const RECORD_ITEM_SELECTOR =
        ".o_field_widget[name=product_id] " +
        ".o-autocomplete--dropdown-item:not(.o_m2o_dropdown_option)";

    test("narrowing an empty search does not re-trigger web_name_search", async () => {
        onRpc("product", "web_name_search", ({ kwargs }) => {
            expect.step(`web_name_search: ${kwargs.name}`);
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await contains(INPUT_SELECTOR).edit("zz", { confirm: false });
        await runAllTimers();
        await contains(INPUT_SELECTOR).edit("zzz", { confirm: false });
        await runAllTimers();

        // "zzz" starts with the memoized empty search "zz": no second RPC
        expect.verifySteps(["web_name_search: zz"]);
    });

    test("quick-creating a record invalidates the memoized empty search", async () => {
        onRpc("product", "web_name_search", ({ kwargs }) => {
            expect.step(`web_name_search: ${kwargs.name}`);
        });
        onRpc("product", "name_create", () => {
            expect.step("name_create");
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await contains(INPUT_SELECTOR).edit("Foo", { confirm: false });
        await runAllTimers();
        expect(RECORD_ITEM_SELECTOR).toHaveCount(0, {
            message: "no product matches 'Foo' yet",
        });
        expect.verifySteps(["web_name_search: Foo"]);

        await clickFieldDropdownItem("product_id", 'Create "Foo"');
        expect.verifySteps(["name_create"]);

        // Retyping the same text must hit the server again and list the
        // newly created record (a stale memo would claim no records exist
        // while offering to create a duplicate)
        await contains(INPUT_SELECTOR).edit("Foo", { confirm: false });
        await runAllTimers();
        expect.verifySteps(["web_name_search: Foo"]);
        expect(`${RECORD_ITEM_SELECTOR}:contains(Foo)`).toHaveCount(1);
    });

    test("creating a record via the dialog invalidates the memoized empty search", async () => {
        onRpc("product", "web_name_search", ({ kwargs }) => {
            expect.step(`web_name_search: ${kwargs.name}`);
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await contains(INPUT_SELECTOR).edit("Bar", { confirm: false });
        await runAllTimers();
        expect.verifySteps(["web_name_search: Bar"]);

        // The creation dialog's name field is prefilled through default_name
        await clickFieldDropdownItem("product_id", "Create and edit...");
        expect(".modal").toHaveCount(1);
        await contains(".modal .o_form_button_save").click();
        expect(".modal").toHaveCount(0);

        // Retyping the same text must hit the server again and list the
        // record created through the dialog
        await contains(INPUT_SELECTOR).edit("Bar", { confirm: false });
        await runAllTimers();
        expect.verifySteps(["web_name_search: Bar"]);
        expect(`${RECORD_ITEM_SELECTOR}:contains(Bar)`).toHaveCount(1);
    });
});

// Search more — opens SelectCreateDialog

describe("search more", () => {
    test("Search more... opens SelectCreateDialog with the field's label in the title", async () => {
        // SelectCreateDialog calls res.users.has_group to determine filter/favorites visibility
        onRpc("res.users", "has_group", () => false);
        // more records than the search limit, so "Search more..." shows up
        for (let i = 0; i < 8; i++) {
            Product._records.push({ id: 100 + i, name: `product ${i}` });
        }

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await clickFieldDropdown("product_id");
        await runAllTimers();
        await clickFieldDropdownItem("product_id", "Search more...");

        // SelectCreateDialog should be visible with the field string in the title
        expect(".modal .modal-title").toHaveCount(1);
        expect(".modal .modal-title").toHaveText("Search: Product");
    });

    test("dropdown renders at most searchLimit records plus Search more on overflow", async () => {
        // 10 records for a searchLimit of 7: the +1 overflow probe must be
        // sliced away and "Search more..." must appear
        for (let i = 0; i < 8; i++) {
            Product._records.push({ id: 100 + i, name: `product ${i}` });
        }

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await clickFieldDropdown("product_id");
        await runAllTimers();

        expect(
            ".o_field_widget[name=product_id] " +
                ".o-autocomplete--dropdown-item:not(.o_m2o_dropdown_option)",
        ).toHaveCount(7);
        expect(".o_m2o_dropdown_option_search_more").toHaveCount(1);
    });

    test("no Search more... when all matching records fit in the dropdown", async () => {
        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await clickFieldDropdown("product_id");
        await runAllTimers();

        expect(
            ".o_field_widget[name=product_id] " +
                ".o-autocomplete--dropdown-item:not(.o_m2o_dropdown_option)",
        ).toHaveCount(2);
        expect(".o_m2o_dropdown_option_search_more").toHaveCount(0);
    });
});

// Quick create error fallback — a ValidationError falls back to the
// create-and-edit dialog instead of escaping as an unhandled rejection

describe("quick create error fallback", () => {
    test("ValidationError on name_create falls back to the creation dialog", async () => {
        onRpc("product", "name_create", () => {
            throw makeServerError({ type: "ValidationError" });
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await contains(".o_field_widget[name=product_id] input").edit("failing", {
            confirm: false,
        });
        await runAllTimers();
        await clickFieldDropdownItem("product_id", 'Create "failing"');
        await animationFrame();

        expect(".o_error_dialog").toHaveCount(0);
        expect(".modal .o_form_view").toHaveCount(1);
        expect(".modal .o_field_widget[name=name] input").toHaveValue("failing");
    });
});
