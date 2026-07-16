import { describe, expect, test } from "@odoo/hoot";

import { definePosModels } from "../data/generate_model_definitions.js";
import { getFilledOrder, setupPosEnv } from "../utils.js";

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

    test("missingRecursive keeps its input when offline", async () => {
        // Regression: the offline early-return used to discard the whole input
        // map, so an offline boot restored zero orders from IndexedDB.
        const store = await setupPosEnv();
        const data = store.data;
        data.network.offline = true;

        const rows = {
            "pos.order": [{ id: "aaa-uuid", uuid: "aaa-uuid", lines: [] }],
            "pos.order.line": [{ id: "bbb-uuid", uuid: "bbb-uuid" }],
        };
        const result = await data.missingRecursive(rows);
        expect(result["pos.order"]).toHaveLength(1);
        expect(result["pos.order.line"]).toHaveLength(1);
        expect(result["pos.order"][0].uuid).toBe("aaa-uuid");
    });

    test("loadConnectedData tolerates an undefined model payload", async () => {
        // Regression: `rawData[model]` without the upstream `|| []` fallback
        // crashed the IndexedDB restore path when a model key was assigned
        // undefined (e.g. no pos.order.line rows on an offline boot).
        const store = await setupPosEnv();
        const results = store.models.loadConnectedData(
            { "pos.order.line": undefined },
            [],
        );
        expect(results["pos.order.line"] ?? []).toHaveLength(0);
    });
});
