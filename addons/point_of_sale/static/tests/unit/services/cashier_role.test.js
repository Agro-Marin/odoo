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

        // The navbar renders before LoginScreen has run, when the field has
        // never been assigned at all -- a shape `false` does not cover.
        store.cashier = undefined;
        expect(store.cashierIsMinimal).toBe(false);
    });
});
