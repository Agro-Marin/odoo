import { expect, test } from "@odoo/hoot";
import { setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { definePosHrModels } from "@pos_hr/../tests/unit/data/generate_model_definitions";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";

definePosHrModels();

test("validateOrder", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const orderUuid = store.getOrder().uuid;
    const comp = await mountWithCleanup(PaymentScreen, {
        props: { orderUuid },
    });
    await comp.validateOrder();
    const order = store.getOrder();
    expect(order.employee_id.id).toBe(2);
});
