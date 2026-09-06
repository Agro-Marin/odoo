import { afterEach, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";
import { PosConfig } from "@point_of_sale/../tests/unit/data/pos_config.data";
import { getFilledOrder, setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";
import OrderPaymentValidation from "@point_of_sale/app/utils/order_payment_validation";
import { getService, mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";

definePosModels();

const pristineConfigs = PosConfig._records;
afterEach(() => {
    PosConfig._records = pristineConfigs;
});

const configureStock = (values) => {
    PosConfig._records = PosConfig._records.map((record) => ({ ...record, ...values }));
};

async function mountCard(product) {
    return mountWithCleanup(ProductCard, {
        props: {
            product,
            name: product.display_name,
            productId: product.id,
            imageUrl: false,
        },
    });
}

test("requests issued in one tick travel as one batched call", async () => {
    const calls = [];
    onRpc("product.product", "get_pos_stock_quantities", ({ args }) => {
        calls.push(args);
        return { 5: 4, 6: 30 };
    });
    await setupPosEnv();
    const service = getService("pos_stock");
    service.request([5]);
    service.request([6, 5]);
    await animationFrame();

    expect(calls).toEqual([[[5, 6], 1]]);
    expect(service.quantities).toEqual({ 5: 4, 6: 30 });
});

test("a template card shows its variants' stock, coloured by the threshold", async () => {
    onRpc("product.product", "get_pos_stock_quantities", () => ({ 5: 4, 6: 30 }));
    const store = await setupPosEnv();
    await mountCard(store.models["product.template"].get(5));
    await mountCard(store.models["product.template"].get(6));
    await animationFrame();

    expect(".o_pos_stock_badge").toHaveCount(2);
    expect(".o_pos_stock_low").toHaveText("4");
    expect(".o_pos_stock_available").toHaveText("30");
    expect(".o_pos_stock_badge.top-0.start-0").toHaveCount(2);
});

test("zero stock is red and the position follows the configuration", async () => {
    configureStock({ stock_display_location: "bottom_right" });
    onRpc("product.product", "get_pos_stock_quantities", () => ({ 5: 0 }));
    const store = await setupPosEnv();
    await mountCard(store.models["product.template"].get(5));
    await animationFrame();

    expect(".o_pos_stock_empty.bottom-0.end-0").toHaveText("0");
});

test("a failed fetch marks the card unknown rather than empty", async () => {
    onRpc("product.product", "get_pos_stock_quantities", () => {
        throw new Error("stock is down");
    });
    const store = await setupPosEnv();
    await mountCard(store.models["product.template"].get(5));
    await animationFrame();

    expect(".o_pos_stock_unknown").toHaveText("?");
    expect(".o_pos_stock_empty").toHaveCount(0);
});

test("no badge when the configuration disables the display", async () => {
    configureStock({ show_stock_in_pos: false });
    onRpc("product.product", "get_pos_stock_quantities", () => {
        expect.step("rpc");
        return {};
    });
    const store = await setupPosEnv();
    await mountCard(store.models["product.template"].get(5));
    await animationFrame();

    expect(".o_pos_stock_badge").toHaveCount(0);
    expect.verifySteps([]);
});

test("refresh refetches every known product and the badge follows", async () => {
    let qty = 2;
    onRpc("product.product", "get_pos_stock_quantities", () => ({ 5: qty }));
    const store = await setupPosEnv();
    await mountCard(store.models["product.template"].get(5));
    await animationFrame();
    expect(".o_pos_stock_badge").toHaveText("2");

    qty = 0;
    getService("pos_stock").refresh();
    expect(".o_pos_stock_badge").toHaveText("2");
    await animationFrame();
    expect(".o_pos_stock_empty").toHaveText("0");
});

test("a validated order refetches the quantities the session already knows", async () => {
    let qty = 9;
    onRpc("product.product", "get_pos_stock_quantities", ({ args }) => {
        expect.step(`rpc ${args[0].join(",")}`);
        return { 5: qty };
    });
    const store = await setupPosEnv();
    await mountCard(store.models["product.template"].get(5));
    await animationFrame();
    expect.verifySteps(["rpc 5"]);

    const order = await getFilledOrder(store);
    store.checkPreparationStateAndSentOrderInPreparation = async () => {};
    const validation = new OrderPaymentValidation({
        pos: store,
        orderUuid: order.uuid,
    });
    qty = 8;
    await validation.afterOrderValidation();
    await animationFrame();
    expect.verifySteps(["rpc 5"]);
    expect(".o_pos_stock_badge").toHaveText("8");
});
