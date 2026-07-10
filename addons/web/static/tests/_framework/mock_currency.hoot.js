// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

import { onServerStateChange, serverState } from "./mock_server_state.hoot.js";

/**
 * Build the `{ id → currency }` map shape that `@web/services/currency`'s
 * module-level `currencies` export holds at runtime. Default `digits` is
 * `[69, 2]` to match the historical mock fixture — the leading 69 isn't
 * load-bearing, only `digits[1]` (fraction count) is read.
 *
 * @param {import("./mock_server_state.hoot").ServerState} state
 */
function makeCurrencies({ currencies }) {
    return Object.fromEntries(
        currencies.map((currency) => [currency.id, { digits: [69, 2], ...currency }]),
    );
}

/**
 * Seed `@web/services/currency`'s module-level `currencies` map from
 * `serverState.currencies` so monetary widgets format with the expected
 * symbol. Without this, `formatCurrency` finds no entry for `id` and
 * falls back to `"1,200.00"` instead of `"$ 1,200.00"`.
 *
 * Why prototype-style mutation via `onServerStateChange`? The Odoo
 * loader stores modules as native ES module namespaces (frozen by spec),
 * so we can't `Object.assign(currencyModule, { currencies: newMap })`.
 * What we *can* do is mutate the SAME object the module exports — which
 * is what `notifySubscribers` does via `Object.defineProperties(target,
 * descriptors)`. The `currencies` const is a binding to that object;
 * mutating its properties is visible to every importer.
 *
 * @param {{ modules: Map<string, any> }} loader
 */
export function setupMockCurrencies(loader) {
    const currencyModule = loader.modules.get("@web/services/currency");
    if (!currencyModule?.currencies) {
        return;
    }
    onServerStateChange(currencyModule.currencies, makeCurrencies);
    // Apply once at setup so eagerly-imported format helpers see populated
    // currencies before the first beforeEach fires.
    Object.assign(currencyModule.currencies, makeCurrencies(serverState));
}
