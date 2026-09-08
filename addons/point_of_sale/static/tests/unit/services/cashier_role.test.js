import { describe, expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

describe("cashierIsMinimal", () => {
    test("a minimal cashier is minimal and any other role is not", async () => {
        const store = await setupPosEnv();
        expect(Boolean(store.cashier)).toBe(true);

        store.cashier._role = "minimal";
        expect(store.cashierIsMinimal).toBe(true);

        store.cashier._role = "manager";
        expect(store.cashierIsMinimal).toBe(false);

        store.cashier._role = "cashier";
        expect(store.cashierIsMinimal).toBe(false);
    });

    test("a logged-out cashier reads as not minimal instead of throwing", async () => {
        const store = await setupPosEnv();

        store.resetCashier();
        expect(store.cashier).toBe(false);
        expect(store.cashierIsMinimal).toBe(false);
    });

    test("an unset cashier reads as not minimal instead of throwing", async () => {
        const store = await setupPosEnv();

        store.cashier = undefined;
        expect(store.cashierIsMinimal).toBe(false);
    });
});

describe("getCashier() does not read pos.cashier", () => {
    test("logging out clears one cashier and leaves the other in place", async () => {
        const store = await setupPosEnv();
        store.config.restrict_price_control = true;
        store.user._role = "manager";

        store.resetCashier();

        expect(store.cashier).toBe(false);
        expect(store.cashierIsMinimal).toBe(false);

        expect(store.getCashier()).toBe(store.user);
        expect(store.cashierHasPriceControlRights()).toBe(true);
    });
});
