import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

import { definePosModels } from "../data/generate_model_definitions.js";
import { setupPosEnv } from "../utils.js";

definePosModels();

describe("data_service.write", () => {
    for (const firstSucceeds of [false, true]) {
        for (const secondSucceeds of [false, true]) {
            for (const reversed of [false, true]) {
                test(`overlapping writes settle correctly: first=${firstSucceeds}, second=${secondSucceeds}, reversed=${reversed}`, async () => {
                    const store = await setupPosEnv();
                    const record = store.models["pos.category"].get(1);
                    const original = record.name;
                    const requests = [];
                    patchWithCleanup(store.data.orm, {
                        write: () =>
                            new Promise((resolve, reject) =>
                                requests.push({ resolve, reject }),
                            ),
                    });
                    const first = store.data
                        .write("pos.category", [1], { name: "First" })
                        .catch(() => false);
                    const second = store.data
                        .write("pos.category", [1], { name: "Second" })
                        .catch(() => false);
                    expect(record.name).toBe("Second");
                    const outcomes = [firstSucceeds, secondSucceeds];
                    const pending = [first, second];
                    for (const index of reversed ? [1, 0] : [0, 1]) {
                        if (outcomes[index]) {
                            requests[index].resolve(true);
                        } else {
                            requests[index].reject(new Error("Rejected"));
                        }
                        await pending[index];
                        if (index === 0 && !reversed) {
                            expect(record.name).toBe("Second");
                        }
                    }
                    expect(record.name).toBe(
                        secondSucceeds ? "Second" : firstSucceeds ? "First" : original,
                    );
                });
            }
        }
    }

    test("rollback preserves newer edits even when a field returns to the submitted value", async () => {
        const store = await setupPosEnv();
        const record = store.models["pos.category"].get(1);
        const originalColor = record.color;
        let rejectRequest;
        patchWithCleanup(store.data.orm, {
            write: () =>
                new Promise((_resolve, reject) => {
                    rejectRequest = reject;
                }),
        });
        const writing = store.data
            .write("pos.category", [1], { name: "Sent", color: 5 })
            .catch(() => false);
        record.name = "Another edit";
        record.name = "Sent";
        rejectRequest(new Error("Rejected"));
        await writing;
        expect(record.name).toBe("Sent");
        expect(record.color).toBe(originalColor);
    });

    test("overlapping relation rollbacks restore the original parent and inverse links", async () => {
        const store = await setupPosEnv();
        const record = store.models["pos.category"].get(1);
        const parents = [
            store.models["pos.category"].get(2),
            store.models["pos.category"].get(3),
        ];
        const original = record.parent_id;
        const requests = [];
        patchWithCleanup(store.data.orm, {
            write: () => new Promise((_resolve, reject) => requests.push(reject)),
        });
        const first = store.data
            .write("pos.category", [1], { parent_id: parents[0].id })
            .catch(() => false);
        const second = store.data
            .write("pos.category", [1], { parent_id: parents[1].id })
            .catch(() => false);
        requests[0](new Error("Rejected first"));
        await first;
        expect(record.parent_id).toBe(parents[1]);
        requests[1](new Error("Rejected second"));
        await second;
        expect(record.parent_id).toBe(original);
        expect(parents[0].child_ids.includes(record)).toBe(false);
        expect(parents[1].child_ids.includes(record)).toBe(false);
    });

    test("rollback does not retain a failed baseline across later writes", async () => {
        const store = await setupPosEnv();
        const record = store.models["pos.category"].get(1);
        patchWithCleanup(store.data.orm, {
            write: async () => {
                throw new Error("Rejected");
            },
        });
        await store.data
            .write("pos.category", [1], { name: "Rejected first" })
            .catch(() => false);
        record.name = "New baseline";
        await store.data
            .write("pos.category", [1], { name: "Rejected second" })
            .catch(() => false);
        expect(record.name).toBe("New baseline");
    });

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
