// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    display_name = fields.Char();

    _records = [{ id: 1, display_name: "first record" }];
}

defineModels([Partner]);

test("web_ribbon renders when neither title nor text is set", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <widget name="web_ribbon"/>
            </form>`,
    });

    expect(".ribbon span").toHaveCount(1);
    expect(".ribbon span").toHaveText("");
});

test("web_ribbon uses the title attribute as its label", async () => {
    await mountView({
        type: "form",
        resModel: "partner",
        resId: 1,
        arch: `
            <form>
                <widget name="web_ribbon" title="Archived"/>
            </form>`,
    });

    expect(".ribbon span").toHaveText("ARCHIVED");
});
