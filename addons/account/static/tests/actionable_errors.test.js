import { describe, expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class Move extends models.Model {
    _name = "move";

    errors = fields.Json();

    _records = [
        {
            id: 1,
            errors: {
                unknown_level: { message: "unknown", level: "not_a_level" },
                no_level: { message: "defaulted" },
                blocking: { message: "blocking", level: "danger" },
                informative: { message: "informative", level: "info" },
            },
        },
    ];
}

defineModels([Move]);

describe("ActionableErrors ordering", () => {
    test("sorts by severity and puts an unknown level last", async () => {
        await mountView({
            type: "form",
            resModel: "move",
            resId: 1,
            arch: `<form><field name="errors" widget="actionable_errors"/></form>`,
        });

        expect(queryAllTexts(".alert")).toEqual([
            "blocking",
            "defaulted",
            "informative",
            "unknown",
        ]);
    });
});
