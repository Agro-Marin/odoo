import { animationFrame } from "@odoo/hoot-mock";
import { insertListInSpreadsheet } from "@spreadsheet/../tests/helpers/list";
import { createSpreadsheetWithPivot } from "@spreadsheet/../tests/helpers/pivot";

export async function createSpreadsheetWithPivotAndList() {
    const { model, env } = await createSpreadsheetWithPivot();
    insertListInSpreadsheet(model, {
        model: "partner",
        columns: ["foo", "bar", "date", "product_id"],
    });
    await animationFrame();
    return { env, model };
}
