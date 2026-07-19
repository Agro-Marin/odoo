import { describe, expect, test } from "@odoo/hoot";
import { RPCError } from "@web/core/network/rpc";

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

    test("a client-side fault keeps the queued entry, bounded by MAX_SYNC_ATTEMPTS", async () => {
        const store = await setupPosEnv();
        const data = store.data;
        data.network.unsyncData = [];
        data.network.deadSyncData = [];

        // A client-side fault (e.g. the TypeError raised when the data layer is
        // not ready) is not evidence the server refused the write, so the entry
        // must survive for a later retry instead of being dead-lettered...
        let calls = 0;
        data.execute = async () => {
            calls++;
            throw new TypeError("client-side fault");
        };
        data.network.unsyncData.push({
            args: [{ type: "write", model: "pos.order", ids: [1], values: {} }],
            date: "2025-01-01 00:00:00",
            try: 1,
            uuid: "fault-1",
        });

        for (let i = 0; i < 10; i++) {
            await data.syncData().catch(() => {});
            if (!data.network.unsyncData.length) {
                break;
            }
        }

        // ...but not forever: without a cap one permanently failing entry would
        // block everything queued behind it for the rest of the session.
        expect(data.network.unsyncData).toHaveLength(0);
        expect(data.network.deadSyncData).toHaveLength(1);
        expect(calls).toBe(5);
    });

    test("a server rejection dead-letters immediately", async () => {
        const store = await setupPosEnv();
        const data = store.data;
        data.network.unsyncData = [];
        data.network.deadSyncData = [];

        let calls = 0;
        data.execute = async () => {
            calls++;
            throw new RPCError("server said no");
        };
        data.network.unsyncData.push({
            args: [{ type: "write", model: "pos.order", ids: [1], values: {} }],
            date: "2025-01-01 00:00:00",
            try: 1,
            uuid: "rejected-1",
        });

        await data.syncData().catch(() => {});

        expect(calls).toBe(1);
        expect(data.network.unsyncData).toHaveLength(0);
        expect(data.network.deadSyncData).toHaveLength(1);
    });
});
