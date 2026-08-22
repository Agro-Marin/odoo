import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

describe("data_service.write", () => {
    test("a rejected ORM write reverts the optimistic local update", async () => {
        const store = await setupPosEnv();
        const data = store.data;
        const category = store.models["pos.category"].get(1);
        const originalName = category.name;

        patchWithCleanup(data, {
            async ormWrite() {
                throw new Error("Access denied");
            },
        });

        let raised = false;
        try {
            await data.write("pos.category", [1], { name: "Renamed" });
        } catch {
            raised = true;
        }

        expect(raised).toBe(true);
        expect(category.name).toBe(originalName);
    });

    test("a successful ORM write keeps the optimistic update", async () => {
        const store = await setupPosEnv();
        const data = store.data;
        const category = store.models["pos.category"].get(1);

        patchWithCleanup(data, { async ormWrite() {} });

        const records = await data.write("pos.category", [1], { name: "Renamed" });
        expect(records).toHaveLength(1);
        expect(category.name).toBe("Renamed");
    });

    test("an unknown id is skipped instead of throwing", async () => {
        const store = await setupPosEnv();
        const data = store.data;

        const records = await data.write("pos.category", [999999], { name: "x" });
        expect(records).toHaveLength(0);
    });
});
