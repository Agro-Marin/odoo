import { expect, test } from "@odoo/hoot";
import { setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { definePosHrModels } from "@pos_hr/../tests/unit/data/generate_model_definitions";

definePosHrModels();

test("getCashierName", async () => {
    const store = await setupPosEnv();
    store.addNewOrder();
    const emp = store.models["hr.employee"].get(3);
    store.setCashier(emp);
    const posOrder = store.getOrder();
    expect(posOrder.getCashierName()).toBe("Employee1");
});
