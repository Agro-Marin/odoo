import { expect, test } from "@odoo/hoot";
import { PosOrderAccounting } from "@point_of_sale/app/models/accounting/pos_order_accounting";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

definePosModels();

// Instruments the tax engine entry point to count how many full passes an order
// action costs. `_computeAllPrices` is the real cost centre: it maps every line
// to a base line and runs the account tax helpers. Prices are computed lazily on
// read, so a realistic count spans "mutate, then read the displayed prices".
function countComputes() {
    const counter = { n: 0 };
    patchWithCleanup(PosOrderAccounting.prototype, {
        _computeAllPrices() {
            counter.n++;
            return super._computeAllPrices(...arguments);
        },
    });
    return counter;
}

test("no-discount order: one recompute, no redundant no-discount pass", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const before = order.prices.taxDetails.total_amount;
    const counter = countComputes();

    counter.n = 0;
    order.lines[0].qty = 10;
    // Reading the memoized prices is what triggers the (single) recompute.
    const details = order.prices.taxDetails;
    void order.unitPrices;
    void order.lines[0].prices;

    // original + unit datasets, one tax pass each (no-discount skips the second)
    // => 2 total. Extra reads do not recompute.
    expect(counter.n).toBe(2);

    // Fresh: the new quantity is reflected, not a stale cached total.
    expect(order.lines[0].qty).toBe(10);
    expect(details.total_amount).toBeGreaterThan(before);

    const line = order.lines[0].prices;
    expect(line.discount_amount).toBe(0);
    expect(line.no_discount_total_included).toBe(line.total_included);
    expect(line.no_discount_total_excluded).toBe(line.total_excluded);
});

test("discounted order still runs the no-discount pass and reports the discount", async () => {
    const store = await setupPosEnv();
    const order = await getFilledOrder(store);
    const counter = countComputes();

    counter.n = 0;
    order.lines[0].discount = 20;
    void order.prices;
    void order.unitPrices;

    // With a discount present, both datasets need the extra no-discount pass => 4.
    expect(counter.n).toBe(4);

    const line = order.lines[0].prices;
    expect(line.discount_amount).toBeGreaterThan(0);
    expect(line.no_discount_total_included).toBeGreaterThan(line.total_included);
});

test("combo parent setQuantity coalesces child updates into one recompute", async () => {
    const store = await setupPosEnv();
    store.models["product.combo"].get(1).qty_free = 2;
    const comboProduct1 = store.models["product.combo.item"].get(1);
    const comboProduct2 = store.models["product.combo.item"].get(3);
    const template = store.models["product.template"].get(7);
    const order = store.addNewOrder();
    await store.addLineToOrder(
        {
            product_tmpl_id: template,
            payload: [
                [{ combo_item_id: comboProduct1, qty: 2 }],
                [{ combo_item_id: comboProduct2, qty: 2 }],
            ],
            qty: 1,
        },
        order,
    );
    const parent = order.lines.find((l) => l.combo_line_ids.length);
    const counter = countComputes();

    counter.n = 0;
    parent.setQuantity(3);
    // Cascaded child qty/price writes all mark dirty; the read recomputes once.
    const total = order.prices.taxDetails.total_amount;

    // Was 10 full passes (one per cascaded write) before coalescing; now the
    // whole action collapses to a single recompute (original + unit).
    expect(counter.n).toBe(2);
    expect(parent.qty).toBe(3);
    expect(total).toBeGreaterThan(0);
});
