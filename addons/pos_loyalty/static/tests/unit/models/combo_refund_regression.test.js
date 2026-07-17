import { describe, expect, test } from "@odoo/hoot";
import { setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { definePosLoyaltyModels } from "@pos_loyalty/../tests/unit/data/generate_model_definitions";

definePosLoyaltyModels();

/**
 * `comboTotalPrice` / `comboTotalPriceWithoutTax` (point_of_sale, on
 * pos.order.line) exist solely for pos_loyalty: `pointsForPrograms` sums them
 * as the "amount with tax" / "amount without tax" gating every rule's
 * `minimum_amount`, and `_getDiscountableOnCheapest` uses the pair as a
 * discount base. Nothing else reads them, and nothing covered them.
 *
 * Product templates used: 5 = "TEST" (combo parent), 6 = "TEST 2" and
 * 8 = "Wood chair" (leaf children), 9 = "Steel chair" (plain line). Template 7
 * is deliberately avoided: it is itself a combo product, so it acquires its own
 * `combo_line_ids` and would be filtered out of the leaf sum.
 */

/**
 * Builds a combo parent with two leaf children plus one plain (non-combo) line.
 *
 * A refund order is shaped exactly like this in production: ticket_screen
 * creates each line with `qty: -refundDetail.qty` (negative) and then relinks
 * `combo_line_ids` onto the refund's parent line. `isSaleDisallowed` rejects
 * positive-qty lines on a refund order, hence the sign of `qty` here.
 */
const setupComboOrder = async (store, { qty = 2, isRefund = false } = {}) => {
    const order = store.addNewOrder();
    order.is_refund = isRefund;
    const lineQty = isRefund ? -qty : qty;

    const mkLine = async (tmplId, q) =>
        await store.addLineToOrder(
            { product_tmpl_id: store.models["product.template"].get(tmplId), qty: q },
            order,
            { force: true },
            false, // configure: skip the combo configurator dialog
        );

    const parent = await mkLine(5, isRefund ? -1 : 1);
    const child1 = await mkLine(6, lineQty);
    const child2 = await mkLine(8, lineQty);
    child1.combo_parent_id = parent;
    child2.combo_parent_id = parent;
    const plain = await mkLine(9, lineQty);

    return { order, parent, children: [child1, child2], plain };
};

describe("combo totals — the pos_loyalty-facing pair", () => {
    test("comboTotalPriceWithoutTax counts quantity, not a unit price", async () => {
        const store = await setupPosEnv();
        const { parent, children } = await setupComboOrder(store, { qty: 3 });

        // Pre-fix this summed `displayPriceUnitExcl` (= unitPrices, computed as
        // if qty were 1), so every child with qty > 1 was undercounted -- it
        // under-gated rule minimum_amounts and under-sized discount bases.
        const lineTotals = children.reduce((s, l) => s + l.priceExcl, 0);
        const unitTotals = children.reduce(
            (s, l) => s + l.unitPrices.total_excluded,
            0,
        );

        expect(parent.comboTotalPriceWithoutTax).toBe(lineTotals);
        // Guard the guard: the two bases must actually differ at qty > 1, else
        // this would pass against the pre-fix code too.
        expect(unitTotals).not.toBe(lineTotals);
        expect(children.every((l) => l.priceExcl !== 0)).toBe(true);
    });

    test("the pair is independent of the iface_tax_included display setting", async () => {
        const store = await setupPosEnv();
        const { order, parent } = await setupComboOrder(store);
        const config = order.config;

        // Pre-fix this summed `displayPrice`, which branches on
        // iface_tax_included -- a *display* setting. On a POS configured to show
        // prices ex-tax, `comboTotalPrice` ("with tax") silently returned
        // tax-EXCLUDED amounts into pos_loyalty's rule math.
        config.iface_tax_included = "total";
        const withTax = parent.comboTotalPrice;
        const withoutTax = parent.comboTotalPriceWithoutTax;
        expect(withTax).not.toBe(withoutTax);

        config.iface_tax_included = "subtotal";
        expect(parent.comboTotalPrice).toBe(withTax);
        expect(parent.comboTotalPriceWithoutTax).toBe(withoutTax);
    });

    test("refund combo totals stay quantity-aware (and keep their sign)", async () => {
        const store = await setupPosEnv();
        const { parent, children } = await setupComboOrder(store, {
            qty: 2,
            isRefund: true,
        });

        // A refund line carries negative qty, and orderSign is -1, so the two
        // cancel: priceExcl is positive. The pre-fix basis (displayPriceUnitExcl
        // = unitPrices, qty-1) was positive too, so the money-math fix changed
        // the MAGNITUDE here, not the sign.
        expect(parent.comboTotalPriceWithoutTax).toBeGreaterThan(0);
        expect(parent.comboTotalPrice).toBeGreaterThan(0);
        expect(parent.comboTotalPriceWithoutTax).toBe(
            children.reduce((s, l) => s + l.priceExcl, 0),
        );
    });
});

describe("combo totals on refunds — sign convention", () => {
    /**
     * Refund + combo + loyalty is reachable: ticket_screen sets
     * `is_refund = true` and relinks `combo_line_ids` onto the refund parent;
     * neither `_updatePrograms` nor `_programIsApplicable` excludes refunds; and
     * `pointsForPrograms` keeps combo parents (it filters out combo *children*).
     *
     * In that reduce the two branches disagree on a refund:
     *
     *     line.combo_line_ids.length > 0
     *         ? line.comboTotalPriceWithoutTax   // priceExcl: qty(-) * sign(-) => POSITIVE
     *         : line.prices.total_excluded       // raw: qty(-)      => NEGATIVE
     *
     * So a refunded combo adds +N to the same total a refunded plain line
     * subtracts -N from. The result gates
     * `if (rule.minimum_amount > amountCheck) continue;`, so the two line kinds
     * push that gate in opposite directions on the same refund.
     *
     * This predates the money-math fix -- the old basis (displayPriceUnitExcl)
     * was positive on refunds too, so both before and after, combo is positive
     * while plain is negative. The fix changed magnitude only; it neither
     * introduced nor worsened this.
     *
     * The assertion is deliberately convention-NEUTRAL: it only requires the two
     * branches to agree. Either signing the non-combo branch or unsigning the
     * combo getters would satisfy it. The decision is genuinely open because the
     * pair's other consumer, `_getDiscountableOnCheapest`, feeds a value bounded
     * by the signed `priceIncl` (`Math.min(this.priceIncl, discountable)`), so
     * the two consumers currently want opposite conventions.
     *
     * Marked `todo`: HOOT suppresses the failure while the asymmetry stands and
     * fails with `remove "todo" test modifier` once it is resolved -- so whoever
     * fixes it is forced to read this note rather than silently flip behaviour.
     */
    test.todo(
        "a refund's combo branch agrees in sign with its plain-line branch",
        async () => {
            const store = await setupPosEnv();
            const { parent, plain } = await setupComboOrder(store, {
                qty: 2,
                isRefund: true,
            });

            // Both must be non-zero, or Math.sign comparison would be vacuous.
            expect(parent.comboTotalPriceWithoutTax).not.toBe(0);
            expect(plain.prices.total_excluded).not.toBe(0);

            // These two are summed together in pointsForPrograms; opposite signs
            // make that total meaningless.
            expect(Math.sign(parent.comboTotalPriceWithoutTax)).toBe(
                Math.sign(plain.prices.total_excluded),
            );
            expect(Math.sign(parent.comboTotalPrice)).toBe(
                Math.sign(plain.prices.total_included),
            );
        },
    );
});
