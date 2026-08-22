// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getService, makeMockEnv, onRpc } from "@web/../tests/web_test_helpers";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";

describe.current.tags("desktop");

const actionRegistry = registry.category("actions");

async function countSettled(/** @type {any} */ run) {
    const env = await makeMockEnv();
    let settled = 0;
    env.bus.addEventListener(AppEvent.ACTION_MANAGER_SETTLED, () => settled++);
    await run(getService("action"));
    return settled;
}

test("a plain client action settles once", async () => {
    actionRegistry.add("settle_plain", () => {});
    const settled = await countSettled((/** @type {any} */ action) =>
        action.doAction({ type: "ir.actions.client", tag: "settle_plain" }),
    );
    expect(settled).toBe(1);
});

test("a server action that returns another action settles once", async () => {
    actionRegistry.add("settle_target", () => {});
    onRpc("/web/action/run", () => ({
        type: "ir.actions.client",
        tag: "settle_target",
    }));
    const settled = await countSettled((/** @type {any} */ action) =>
        action.doAction({ type: "ir.actions.server", id: 1 }),
    );
    expect(settled).toBe(1);
});

test("a client action chaining into another settles once", async () => {
    actionRegistry.add("settle_chain_end", () => {});
    actionRegistry.add("settle_chain_start", () => ({
        type: "ir.actions.client",
        tag: "settle_chain_end",
    }));
    const settled = await countSettled((/** @type {any} */ action) =>
        action.doAction({ type: "ir.actions.client", tag: "settle_chain_start" }),
    );
    expect(settled).toBe(1);
});

test("an act_url that closes settles once", async () => {
    const settled = await countSettled((/** @type {any} */ action) =>
        action.doAction({
            type: "ir.actions.act_url",
            target: "download",
            url: "/x",
            close: true,
        }),
    );
    expect(settled).toBe(1);
});

test("a failing dispatch still settles, exactly once", async () => {
    actionRegistry.add("settle_boom", () => {
        throw new Error("boom");
    });
    const settled = await countSettled(async (/** @type {any} */ action) => {
        await expect(
            action.doAction({ type: "ir.actions.client", tag: "settle_boom" }),
        ).rejects.toThrow(/boom/);
    });
    expect(settled).toBe(1);
});

test("two separate gestures settle twice", async () => {
    actionRegistry.add("settle_twice", () => {});
    const settled = await countSettled(async (/** @type {any} */ action) => {
        await action.doAction({ type: "ir.actions.client", tag: "settle_twice" });
        await action.doAction({ type: "ir.actions.client", tag: "settle_twice" });
    });
    expect(settled).toBe(2);
});

test("overlapping gestures settle once, when the last of them is done", async () => {
    actionRegistry.add("settle_overlap", () => {});
    const settled = await countSettled(async (/** @type {any} */ action) => {
        await Promise.allSettled([
            action.doAction({ type: "ir.actions.client", tag: "settle_overlap" }),
            action.doAction({ type: "ir.actions.client", tag: "settle_overlap" }),
        ]);
    });
    expect(settled).toBe(1);
});
