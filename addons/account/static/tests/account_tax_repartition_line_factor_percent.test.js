import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    models,
    mountView,
} from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");

class TaxRepartitionLine extends models.Model {
    _name = "tax.repartition.line";

    factor_percent = fields.Float();

    _records = [
        { id: 1, factor_percent: 100 },
        { id: 2, factor_percent: 0.5 },
        { id: 3, factor_percent: 1 / 3 },
    ];
}

defineModels([TaxRepartitionLine]);

/** @param {number} resId */
function arch(options) {
    return `
        <form>
            <field name="factor_percent"
                widget="account_tax_repartition_line_factor_percent"
                readonly="1"${options ? ` options="${options}"` : ""}/>
        </form>`;
}

describe("factor percent formatting", () => {
    test("trims the trailing zeros of the default 12 decimals", async () => {
        await mountView({
            type: "form",
            resModel: "tax.repartition.line",
            resId: 2,
            arch: arch(),
        });

        expect("[name='factor_percent']").toHaveText("0.50");
    });

    test("keeps every significant decimal", async () => {
        await mountView({
            type: "form",
            resModel: "tax.repartition.line",
            resId: 3,
            arch: arch(),
        });

        expect("[name='factor_percent']").toHaveText("0.333333333333");
    });

    test("leaves an integer alone when the arch asks for no decimals", async () => {
        await mountView({
            type: "form",
            resModel: "tax.repartition.line",
            resId: 1,
            arch: arch("{'digits': [16, 0]}"),
        });

        expect("[name='factor_percent']").toHaveText("100");
    });
});
