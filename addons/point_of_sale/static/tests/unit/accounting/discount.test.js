import { expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { expectFormattedPrice, setupPosEnv } from "../utils.js";
import { getFilledOrderForPriceCheck } from "./utils.js";

definePosModels();

test("Taxes object should contain no discount values", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrderForPriceCheck(store);
    order.lines[0].setDiscount(10);
    order.lines[1].setDiscount(20);

    const details = order.prices.taxDetails;
    const line1 = order.lines[0].prices;
    const line2 = order.lines[1].prices;

    expect(details.base_amount).toBe(980);
    expect(details.tax_amount).toBe(257);
    expect(details.total_amount).toBe(1237);

    expectFormattedPrice(order.currencyDisplayPrice, "$ 1,237.00");
    expectFormattedPrice(order.currencyAmountTaxes, "$ 257.00");
    expectFormattedPrice(order.lines[0].currencyDisplayPrice, "$ 1,125.00");
    expectFormattedPrice(order.lines[0].currencyDisplayPriceUnit, "$ 1,125.00");
    expectFormattedPrice(order.lines[0].currencyDisplayPriceUnitExcl, "$ 900.00");
    expectFormattedPrice(order.lines[1].currencyDisplayPrice, "$ 112.00");
    expectFormattedPrice(order.lines[1].currencyDisplayPriceUnit, "$ 112.00");
    expectFormattedPrice(order.lines[1].currencyDisplayPriceUnitExcl, "$ 80.00");

    expect(line1.no_discount_total_included).toBe(1250);
    expect(line1.no_discount_total_excluded).toBe(1000);
    expect(line1.no_discount_taxes_data[0].tax_amount).toBe(250);
    expect(line1.no_discount_taxes_data[0].tax.amount).toBe(25);

    expect(line2.no_discount_total_included).toBe(140);
    expect(line2.no_discount_total_excluded).toBe(100);
    expect(line2.no_discount_taxes_data[0].tax_amount).toBe(15);
    expect(line2.no_discount_taxes_data[0].tax.amount).toBe(15);
    expect(line2.no_discount_taxes_data[1].tax_amount).toBe(25);
    expect(line2.no_discount_taxes_data[1].tax.amount).toBe(25);
});

test("no_discount unit prices exclude the line discount", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrderForPriceCheck(store);
    const line = order.lines[0];
    line.setDiscount(10);

    expect(line.unitPrices.total_included).toBe(1125);
    expect(line.unitPrices.no_discount_total_included).toBe(1250);
    expect(line.unitPrices.no_discount_total_excluded).toBe(1000);
});
