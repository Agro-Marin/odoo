import { expect, test } from "@odoo/hoot";
import { press, queryFirst } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    models,
    mountView,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";

// The empty-state of the Discounts & Loyalty list is the only way to start a
// program from a template, and it used to be a <div t-on-click>: unreachable
// without a mouse, and announced as nothing in particular.
class LoyaltyProgram extends models.Model {
    _name = "loyalty.program";

    name = fields.Char();

    _records = [];
}

defineModels([...Object.values(webModels), LoyaltyProgram]);

const TEMPLATES = {
    promo_code: {
        title: "Promo Code",
        description: "Get 10% off on some products, with a code",
        icon: "promo_code",
    },
};

async function mountEmptyProgramList() {
    onRpc("loyalty.program", "get_program_templates", () => TEMPLATES);
    await mountView({
        type: "list",
        resModel: "loyalty.program",
        arch: `<list js_class="loyalty_program_list_view"><field name="name"/></list>`,
        noContentHelp: "<p>No program found.</p>",
    });
}

test("each onboarding template is a button carrying its own name", async () => {
    await mountEmptyProgramList();

    expect(".loyalty-template").toHaveCount(1);
    expect("button.loyalty-template").toHaveCount(1);
    expect(".loyalty-template").toHaveAttribute(
        "aria-label",
        "Select Promo Code template",
    );
});

test("a template can be focused and started from the keyboard", async () => {
    await mountEmptyProgramList();
    onRpc("loyalty.program", "create_from_template", ({ args }) => {
        expect.step(`create_from_template:${args[0]}`);
        return false;
    });

    queryFirst(".loyalty-template").focus();
    expect(".loyalty-template").toBeFocused();

    await press("Enter");
    await animationFrame();

    expect.verifySteps(["create_from_template:promo_code"]);
});
