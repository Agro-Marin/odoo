// @ts-check

import { onServerStateChange, serverState } from "./mock_server_state.hoot.js";

/**
 * @param {import("./mock_server_state.hoot").ServerState} state
 */
function makeCurrencies({ currencies }) {
    return Object.fromEntries(
        currencies.map((currency) => [currency.id, { digits: [69, 2], ...currency }]),
    );
}

/**
 * @param {{ modules: Map<string, any> }} loader
 */
export function setupMockCurrencies(loader) {
    const currencyModule = loader.modules.get("@web/core/currency");
    if (!currencyModule?.currencies) {
        return;
    }
    onServerStateChange(currencyModule.currencies, makeCurrencies);
    Object.assign(currencyModule.currencies, makeCurrencies(serverState));
}
