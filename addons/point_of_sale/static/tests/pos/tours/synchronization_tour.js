/* global posmodel */

import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as ReceiptScreen from "@point_of_sale/../tests/pos/tours/utils/receipt_screen_util";
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("test_sync_from_ui_one_by_one", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            {
                trigger: "body",
                content: "Create fake orders",
                run: async () => {
                    // Create 5 orders that will be synced one by one
                    for (let i = 0; i < 5; i++) {
                        const product = posmodel.models["product.template"].find(
                            (p) => p.name === "Desk Pad",
                        );
                        const order = posmodel.createNewOrder();
                        await posmodel.addLineToOrder(
                            { product_tmpl_id: product },
                            order,
                        );
                        posmodel.addPendingOrder([order.id]);
                    }
                },
            },
            // Create one more order to be able to trigger the sync from the UI
            ProductScreen.clickDisplayedProduct("Desk Pad"),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Bank"),
            PaymentScreen.clickValidate(),
            ReceiptScreen.isShown(),
            {
                trigger: "body",
                content: "Flush the five orders left pending",
                // Validating an order syncs exactly that order and no other
                // (order_payment_validation.js says why), so the queue built
                // above is still local at this point. Flush it explicitly: what
                // this test exists to pin is that each order costs its own
                // sync_from_ui call, not that validation drains the queue.
                run: async () => {
                    await posmodel.syncAllOrders();
                },
            },
        ].flat(),
});
