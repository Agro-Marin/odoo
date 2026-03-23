import { test, expect, describe } from "@odoo/hoot";
import { getFilledOrder, setupPosEnv } from "../utils.js";
import { definePosModels } from "../data/generate_model_definitions.js";

definePosModels();

describe("data_service", () => {
    test("localDeleteCascade", async () => {
        const store = await setupPosEnv();
        const data = store.data;
        const order = await getFilledOrder(store);

        expect(store.models["pos.order"].length).toBe(1);
        expect(store.models["pos.order.line"].length).toBe(2);
        data.localDeleteCascade(order);
        expect(store.models["pos.order"].length).toBe(0);
        expect(store.models["pos.order.line"].length).toBe(0);
    });
});
