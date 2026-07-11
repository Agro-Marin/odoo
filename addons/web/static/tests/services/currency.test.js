// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    fields,
    makeMockEnv,
    models,
    onRpc,
    serverState,
} from "@web/../tests/web_test_helpers";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { formatCurrency, getCurrencyRates } from "@web/services/currency";

class Currency extends models.Model {
    _name = "res.currency";

    name = fields.Char();
    inverse_rate = fields.Float();
    date = fields.Date();

    _records = [
        { id: 1, name: "USD", inverse_rate: 1, date: "2026-07-10" },
        { id: 2, name: "EUR", inverse_rate: 0.5, date: "2026-07-10" },
    ];
}

defineModels([Currency]);

describe.current.tags("headless");

beforeEach(async () => {
    await makeMockEnv(); // To start the localization service
});

test("formatCurrency", async () => {
    serverState.currencies = [
        { id: 1, position: "after", symbol: "€" },
        { id: 2, position: "before", symbol: "$" },
    ];

    expect(formatCurrency(200)).toBe("200.00");
    expect(formatCurrency(1234567.654, 1)).toBe("1,234,567.65\u00a0€");
    expect(formatCurrency(1234567.654, 2)).toBe("$\u00a01,234,567.65");
    expect(formatCurrency(1234567.654, 44)).toBe("1,234,567.65");
    expect(formatCurrency(1234567.654, 1, { noSymbol: true })).toBe("1,234,567.65");
    expect(formatCurrency(8.0, 1, { humanReadable: true })).toBe("8.00\u00a0€");
    expect(formatCurrency(1234567.654, 1, { humanReadable: true })).toBe(
        "1.23M\u00a0€",
    );
    expect(formatCurrency(1990000.001, 1, { humanReadable: true })).toBe(
        "1.99M\u00a0€",
    );
    expect(formatCurrency(1234567.654, 44, { digits: [69, 1] })).toBe("1,234,567.7");
    expect(formatCurrency(1234567.654, 2, { digits: [69, 1] })).toBe(
        "$\u00a01,234,567.7",
        {
            message:
                "options digits should take over currency digits when both are defined",
        },
    );
});

test("formatCurrency without currency", async () => {
    serverState.currencies = [];

    expect(formatCurrency(1234567.654, 10, { humanReadable: true })).toBe("1.23M");
    expect(formatCurrency(1234567.654, 10)).toBe("1,234,567.65");
});

test("getCurrencyRates hands every caller the same updated object", async () => {
    serverState.currencies = [
        { id: 1, position: "after", symbol: "€" },
        { id: 2, position: "before", symbol: "$" },
    ];
    let inverseRate = 0.5;
    onRpc("read", ({ model }) => {
        if (model !== "res.currency") {
            return;
        }
        expect.step("read rates");
        return [
            { id: 1, inverse_rate: 1, date: "2026-07-10" },
            { id: 2, inverse_rate: inverseRate, date: "2026-07-10" },
        ];
    });

    // Concurrent callers share one in-flight RPC and one reactive object.
    const [rates1, rates2] = await Promise.all([
        getCurrencyRates(),
        getCurrencyRates(),
    ]);
    expect(rates2).toBe(rates1);
    expect(rates1[2].rate).toBe(0.5);
    expect.verifySteps(["read rates"]);

    // After a cache invalidation, the refetch updates the SAME object, so
    // earlier consumers holding rates1 observe the refreshed rate.
    inverseRate = 0.75;
    rpcBus.dispatchEvent(
        new CustomEvent(RpcEvent.CLEAR_CACHES, {
            detail: { tables: ["read"], model: "res.currency" },
        }),
    );
    await animationFrame();
    const rates3 = await getCurrencyRates();
    expect(rates3).toBe(rates1);
    expect(rates1[2].rate).toBe(0.75);
    expect.verifySteps(["read rates"]);
});
