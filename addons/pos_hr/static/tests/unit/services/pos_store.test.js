import { expect, test } from "@odoo/hoot";
import { setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { definePosHrModels } from "@pos_hr/../tests/unit/data/generate_model_definitions";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

definePosHrModels();

test("createNewOrder", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const order = store.getOrder();
    expect(order.employee_id.id).toBe(2);
});
test("employeeIsAdmin", async () => {
    const store = await setupPosEnv();
    const emp = store.models["hr.employee"].get(2);
    store.setCashier(emp);
    expect(store.employeeIsAdmin).toBe(true);
});
// The three below state `module_pos_hr` and assign `cashier` explicitly instead
// of relying on the fixture and on `setCashier()`. Both leak across suites: run
// after the navbar suite, `config.module_pos_hr` arrives false and the override
// under test is never reached. `handleUrlParams` below sets the flag for the
// same reason.
test("getCashierUserId returns the user id, not the res.users record", async () => {
    const store = await setupPosEnv();
    store.config.module_pos_hr = true;
    store.cashier = store.models["hr.employee"].get(3);
    expect(store.getCashierUserId()).toBe(3);
});
test("getCashierUserId returns null when no cashier is logged in", async () => {
    const store = await setupPosEnv();
    store.config.module_pos_hr = true;
    // The Navbar evaluates this on mount, before LoginScreen has picked a
    // cashier, so `cashier` is still undefined -- the state the guard on
    // `employeeIsAdmin` was added for. `resetCashier()` leaves false instead.
    store.cashier = undefined;
    expect(store.getCashierUserId()).toBe(null);
    store.cashier = false;
    expect(store.getCashierUserId()).toBe(null);
});
test("the employee who opened the session can close the register", async () => {
    const store = await setupPosEnv();
    store.config.module_pos_hr = true;
    store.cashier = store.models["hr.employee"].get(3);
    store.session.user_id = store.models["res.users"].get(3);
    expect(store.employeeIsAdmin).toBe(false);
    // Third clause of the "Close Register" t-if in pos_hr's Navbar template.
    expect(store.getCashierUserId()).toBe(store.session.user_id?.id);
});
test("_getConnectedCashier", async () => {
    const store = await setupPosEnv();
    expect(store._getConnectedCashier().id).toBe(2);
});
test("shouldShowOpeningControl", async () => {
    const store = await setupPosEnv();
    const emp = store.models["hr.employee"].get(2);
    store.setCashier(emp);
    store.hasLoggedIn = true;
    expect(store.shouldShowOpeningControl()).toBe(true);
});
test("allowProductCreation", async () => {
    const store = await setupPosEnv();
    const admin = store.models["hr.employee"].get(2);
    store.setCashier(admin);
    expect(await store.allowProductCreation()).toBe(true);
    const emp = store.models["hr.employee"].get(3);
    store.setCashier(emp);
    expect(await store.allowProductCreation()).toBe(false);
});
test("addLineToCurrentOrder", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const admin = store.models["hr.employee"].get(2);
    store.setCashier(admin);
    const product_id = store.models["product.product"].get(5);
    const result = await store.addLineToCurrentOrder({
        product_id: product_id,
        product_tmpl_id: product_id.product_tmpl_id,
    });
    expect(result.order_id.employee_id.id).toBe(2);
});
test("canEditPayment", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const order = store.getOrder();
    const admin = store.models["hr.employee"].get(2);
    store.setCashier(admin);
    expect(store.canEditPayment(order)).toBe(true);
    const emp = store.models["hr.employee"].get(3);
    store.setCashier(emp);
    expect(store.canEditPayment(order)).toBe(false);
});
test("handleUrlParams prevents unauthorized access when POS is locked with pos_hr", async () => {
    const store = await setupPosEnv();
    store.config.module_pos_hr = true;
    odoo.from_backend = false;

    store.resetCashier();
    expect(store.cashier).toBe(false);
    expect(store.config.module_pos_hr).toBe(true);
    store.router.state.current = "ProductScreen";
    store.router.state.params = {};

    let navigateCalledWithLoginScreen = false;
    patchWithCleanup(store.router, {
        navigate(routeName, routeParams) {
            if (routeName === "LoginScreen") {
                navigateCalledWithLoginScreen = true;
            }
            return super.navigate(routeName, routeParams);
        },
    });

    await store.handleUrlParams();
    expect(navigateCalledWithLoginScreen).toBe(true);
});
