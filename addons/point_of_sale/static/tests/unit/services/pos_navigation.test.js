import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

describe("firstPage is a description, not an action", () => {
    let fromBackend;
    beforeEach(() => (fromBackend = odoo.from_backend));
    afterEach(() => (odoo.from_backend = fromBackend));

    test("reading it does not end the session", async () => {
        const store = await setupPosEnv();
        expect(store.cashier).toBe(store.user);
        void store.firstPage;
        void store.firstPage;
        expect(store.cashier).toBe(store.user);
    });

    test("it reports LoginScreen when, and only when, there is no cashier", async () => {
        const store = await setupPosEnv();
        expect(store.firstPage.page).not.toBe("LoginScreen");
        store.resetCashier();
        expect(store.firstPage.page).toBe("LoginScreen");
    });

    test("the idle timer returns to the floor without logging the cashier out", async () => {
        const store = await setupPosEnv();
        store.addNewOrder();
        const cashier = store.cashier;
        store.navigateToFirstPage();
        expect(store.cashier).toBe(cashier);
    });
});

describe("bootPage consumes the boot flags, and says so in its name", () => {
    let fromBackend;
    beforeEach(() => (fromBackend = odoo.from_backend));
    afterEach(() => (odoo.from_backend = fromBackend));

    test("without from_backend it starts logged out", async () => {
        const store = await setupPosEnv();
        odoo.from_backend = 0;
        expect(store.bootPage().page).toBe("LoginScreen");
        expect(store.cashier).toBe(false);
    });

    test("with from_backend it starts logged in as the user", async () => {
        const store = await setupPosEnv();
        store.resetCashier();
        odoo.from_backend = 1;
        const page = store.bootPage();
        expect(store.cashier).toBe(store.user);
        expect(page.page).not.toBe("LoginScreen");
    });

    test("with from_backend it strips the flag from the address bar", async () => {
        const store = await setupPosEnv();
        odoo.from_backend = 1;
        const url = new URL(browserLocation());
        url.searchParams.set("from_backend", "True");
        window.history.replaceState({}, "", url);
        store.bootPage();
        expect(new URL(browserLocation()).searchParams.get("from_backend")).toBe(null);
    });
});

function browserLocation() {
    return window.location.href;
}
