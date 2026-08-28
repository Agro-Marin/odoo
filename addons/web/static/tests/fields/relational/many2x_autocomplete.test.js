// @ts-check

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
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { Many2XAutocomplete } from "@web/fields/relational/many2x_autocomplete";
import { FormViewDialog } from "@web/views/view_dialogs";

describe.current.tags("desktop");

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

    _views = {
        form: `<form><field name="name"/></form>`,
        list: `<list><field name="name"/></list>`,
        search: `<search/>`,
    };
}

class ResUsers extends models.Model {
    _name = "res.users";
    name = fields.Char();

    _records = [{ id: 1, name: "Admin" }];
}

defineModels([Partner, Product, ResUsers]);

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

        expect(
            ".o_field_widget[name=product_id] .o-autocomplete--dropdown-item:contains(xphone)",
        ).toHaveCount(1);
        expect(
            ".o_field_widget[name=product_id] .o-autocomplete--dropdown-item:contains(xpad)",
        ).toHaveCount(1);
    });
});

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

describe("empty-search memoization", () => {
    const INPUT_SELECTOR = ".o_field_widget[name=product_id] input";
    const RECORD_ITEM_SELECTOR =
        ".o_field_widget[name=product_id] " +
        ".o-autocomplete--dropdown-item:not(.o_m2o_dropdown_option)";

    test("narrowing an empty search re-triggers web_name_search", async () => {
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

        expect.verifySteps(["web_name_search: zz", "web_name_search: zzz"]);
    });

    test("an exact barcode match after a shorter empty prefix is not suppressed", async () => {
        onRpc("product", "web_name_search", ({ kwargs }) => {
            expect.step(`web_name_search: ${kwargs.name}`);
            if (kwargs.name === "0370006152") {
                return [{ id: 42, display_name: "Scanned Product" }];
            }
            return [];
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await contains(INPUT_SELECTOR).edit("037000", { confirm: false });
        await runAllTimers();
        expect(RECORD_ITEM_SELECTOR).toHaveCount(0, {
            message: "no product matches the partial barcode",
        });

        await contains(INPUT_SELECTOR).edit("0370006152", { confirm: false });
        await runAllTimers();

        expect.verifySteps(["web_name_search: 037000", "web_name_search: 0370006152"]);
        expect(`${RECORD_ITEM_SELECTOR}:contains(Scanned Product)`).toHaveCount(1, {
            message: "the exact barcode match is surfaced, not suppressed",
        });
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

        await contains(INPUT_SELECTOR).edit("Foo", { confirm: false });
        await runAllTimers();
        expect.verifySteps(["web_name_search: Foo"]);
        expect(`${RECORD_ITEM_SELECTOR}:contains(Foo)`).toHaveCount(1);
    });

    test("a term already known to be empty is not searched again", async () => {
        onRpc("product", "web_name_search", ({ kwargs }) => {
            expect.step(`web_name_search: ${kwargs.name}`);
            return [];
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        for (const term of ["zz", "zzz", "zz", "zzz"]) {
            await contains(INPUT_SELECTOR).edit(term, { confirm: false });
            await runAllTimers();
        }

        expect.verifySteps(["web_name_search: zz", "web_name_search: zzz"]);
    });

    test("a changed domain re-enables a term already known to be empty", async () => {
        Partner._fields.name = fields.Char();
        onRpc("product", "web_name_search", ({ kwargs }) => {
            expect.step(`web_name_search: ${kwargs.name}`);
            return [];
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form>
                <field name="name"/>
                <field name="product_id" domain="[('name', '=', name)]"/>
            </form>`,
        });

        await contains(INPUT_SELECTOR).edit("zz", { confirm: false });
        await runAllTimers();
        await contains(INPUT_SELECTOR).edit("zz", { confirm: false });
        await runAllTimers();
        expect.verifySteps(["web_name_search: zz"]);

        await contains(".o_field_widget[name=name] input").edit("other", {
            confirm: "blur",
        });
        await contains(INPUT_SELECTOR).edit("zz", { confirm: false });
        await runAllTimers();
        expect.verifySteps(["web_name_search: zz"]);
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

        await clickFieldDropdownItem("product_id", "Create and edit...");
        expect(".modal").toHaveCount(1);
        await contains(".modal .o_form_button_save").click();
        expect(".modal").toHaveCount(0);

        await contains(INPUT_SELECTOR).edit("Bar", { confirm: false });
        await runAllTimers();
        expect.verifySteps(["web_name_search: Bar"]);
        expect(`${RECORD_ITEM_SELECTOR}:contains(Bar)`).toHaveCount(1);
    });
});

describe("search more", () => {
    test("Search more... opens SelectCreateDialog with the field's label in the title", async () => {
        onRpc("res.users", "has_group", () => false);
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

        expect(".modal .modal-title").toHaveCount(1);
        expect(".modal .modal-title").toHaveText("Search: Product");
    });

    test("dropdown renders at most searchLimit records plus Search more on overflow", async () => {
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

describe("creation dialog size", () => {
    const INPUT_SELECTOR = ".o_field_widget[name=product_id] input";

    test("the default dialog opens at its own size", async () => {
        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await contains(INPUT_SELECTOR).edit("Bar", { confirm: false });
        await runAllTimers();
        await clickFieldDropdownItem("product_id", "Create and edit...");
        await animationFrame();
        expect(".modal-dialog.modal-lg").toHaveCount(1);
    });

    test("a dialog that declares a size opens at it, with nothing passed", async () => {
        class NarrowFormViewDialog extends FormViewDialog {
            static defaultProps = { ...FormViewDialog.defaultProps, size: "md" };
        }
        patchWithCleanup(Many2XAutocomplete.prototype, {
            get createDialog() {
                return NarrowFormViewDialog;
            },
        });

        await mountView({
            type: "form",
            resModel: "partner",
            resId: 1,
            arch: `<form><field name="product_id"/></form>`,
        });

        await contains(INPUT_SELECTOR).edit("Bar", { confirm: false });
        await runAllTimers();
        await clickFieldDropdownItem("product_id", "Create and edit...");
        await animationFrame();
        expect(".modal-dialog.modal-md").toHaveCount(1);
        expect(".modal-dialog.modal-lg").toHaveCount(0);
    });
});

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
