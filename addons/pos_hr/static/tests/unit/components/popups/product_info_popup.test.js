import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { ProductInfoPopup } from "@point_of_sale/app/components/popups/product_info_popup/product_info_popup";
import { definePosHrModels } from "@pos_hr/../tests/unit/data/generate_model_definitions";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

definePosHrModels();

test("allowProductEdition", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const admin = store.models["hr.employee"].get(2);
    store.setCashier(admin);
    const product = store.models["product.template"].get(5);
    const info = await store.getProductInfo(product, 1);
    const comp = await mountWithCleanup(ProductInfoPopup, {
        props: {
            productTemplate: product,
            info,
            close: () => {},
        },
    });
    expect(comp.allowProductEdition).toBe(true);
    const emp = store.models["hr.employee"].get(3);
    store.setCashier(emp);
    expect(comp.allowProductEdition).toBe(false);
});

test("a minimal employee is not shown the order financials", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const product = store.models["product.template"].get(5);
    const info = await store.getProductInfo(product, 1);
    await mountWithCleanup(ProductInfoPopup, {
        props: {
            productTemplate: product,
            info,
            close: () => {},
        },
    });

    const admin = store.models["hr.employee"].get(2);
    const minimal = store.models["hr.employee"].get(4);
    expect(minimal._role).toBe("minimal");

    store.setCashier(admin);
    await animationFrame();
    expect(".financials-order").toHaveCount(1);
    expect(".section-financials .section-title").toHaveCount(1);

    // Cost, margin and the order totals are not a minimal employee's to read:
    // the same popup already refuses them the favourite toggle.
    store.setCashier(minimal);
    await animationFrame();
    expect(".financials-order").toHaveCount(0);
});
