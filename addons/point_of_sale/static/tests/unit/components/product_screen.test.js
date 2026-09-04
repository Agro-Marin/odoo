import { expect, test } from "@odoo/hoot";
import { queryAll } from "@odoo/hoot-dom";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { mountWithCleanup, onRpc } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

test("_getProductByBarcode", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const order = store.getOrder();
    const comp = await mountWithCleanup(ProductScreen, {
        props: { orderUuid: order.uuid },
    });
    await comp.addProductToOrder(store.models["product.template"].get(5));

    expect(order.displayPrice).toBe(3.45);
    expect(comp.total).toBe("$\u00a03.45");
    expect(comp.items).toBe("1");

    const productByBarcode = await comp._getProductByBarcode({
        base_code: "test_test",
    });
    expect(productByBarcode.id).toEqual(5);
});

test("fastValidate", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const order = store.getOrder();
    const fastPaymentMethod = order.config.fast_payment_method_ids[0];
    const productScreen = await mountWithCleanup(ProductScreen, {
        props: { orderUuid: order.uuid },
    });
    await productScreen.addProductToOrder(store.models["product.template"].get(5));

    expect(order.displayPrice).toBe(3.45);
    expect(productScreen.total).toBe("$\u00a03.45");
    expect(productScreen.items).toBe("1");

    await productScreen.fastValidate(fastPaymentMethod);

    expect(order.payment_ids[0].payment_method_id).toEqual(fastPaymentMethod);
    expect(order.state).toBe("paid");
    expect(order.amount_paid).toBe(3.45);
});

test("product cards are wired for reordering", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const order = store.getOrder();
    await mountWithCleanup(ProductScreen, { props: { orderUuid: order.uuid } });

    const cards = queryAll(".product-sortable");
    expect(cards.length).toBeGreaterThan(1);
    for (const card of cards) {
        const product = store.models["product.template"].get(Number(card.dataset.productId));
        expect(card.dataset.posSequence).toBe(String(product.pos_sequence));
    }
});

test("dropping a product card renumbers only what it displaces", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const order = store.getOrder();
    const comp = await mountWithCleanup(ProductScreen, { props: { orderUuid: order.uuid } });

    const cards = queryAll(".product-sortable");
    const [first, second, third] = cards;
    const idOf = (card) => Number(card.dataset.productId);
    for (const [index, card] of [first, second, third].entries()) {
        store.models["product.template"].get(idOf(card)).update({ pos_sequence: index + 1 });
        card.dataset.posSequence = String(index + 1);
    }

    let written = null;
    onRpc("product.template", "set_pos_sequence", ({ args }) => {
        written = args[0];
        return true;
    });

    // Drop the third card between the first and the second.
    await comp._sortDrop({ element: third, previous: first, next: second });

    expect(written).toEqual({
        [idOf(third)]: 2,
        [idOf(second)]: 3,
    });
    expect(store.models["product.template"].get(idOf(third)).pos_sequence).toBe(2);
    expect(store.models["product.template"].get(idOf(second)).pos_sequence).toBe(3);
    expect(store.models["product.template"].get(idOf(first)).pos_sequence).toBe(1);
});
