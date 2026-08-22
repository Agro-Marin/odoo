// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import {
    makeMockEnv,
    makeMockServer,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { rpc } from "@web/core/network/rpc";
import { config as transitionConfig } from "@web/core/transition";
import { LoadingIndicator } from "@web/webclient/loading_indicator/loading_indicator";

describe.current.tags("desktop");

async function withIndicator(/** @type {() => any} */ run) {
    await makeMockServer();
    patchWithCleanup(transitionConfig, { disabled: true });
    await makeMockEnv();
    const indicator = await mountWithCleanup(LoadingIndicator, {
        noMainContainer: true,
    });
    await run();
    await runAllTimers();
    await animationFrame();
    return indicator;
}

test("a successful call leaves nothing in flight", async () => {
    onRpc("/probe", () => ({ ok: true }));
    const indicator = await withIndicator(async () => {
        await rpc("/probe", {});
    });
    expect(indicator.rpcIds.size).toBe(0);
    expect(".o_loading_indicator").toHaveCount(0);
});

test("a failing call leaves nothing in flight", async () => {
    onRpc("/probe", () => {
        throw new Error("server said no");
    });
    const indicator = await withIndicator(async () => {
        await rpc("/probe", {}).catch(() => {});
    });
    expect(indicator.rpcIds.size).toBe(0);
    expect(".o_loading_indicator").toHaveCount(0);
});

test("an aborted call leaves nothing in flight", async () => {
    onRpc("/probe", () => new Promise(() => {}));
    const indicator = await withIndicator(async () => {
        const prom = rpc("/probe", {});
        prom.catch(() => {});
        prom.abort();
    });
    expect(indicator.rpcIds.size).toBe(0);
    expect(".o_loading_indicator").toHaveCount(0);
});

test("deduplicated callers leave nothing in flight", async () => {
    onRpc("/probe", () => ({ ok: true }));
    const indicator = await withIndicator(async () => {
        await Promise.all([
            rpc("/probe", { a: 1 }, { dedup: true }),
            rpc("/probe", { a: 1 }, { dedup: true }),
            rpc("/probe", { a: 1 }, { dedup: true }),
        ]);
    });
    expect(indicator.rpcIds.size).toBe(0);
    expect(".o_loading_indicator").toHaveCount(0);
});

test("one caller aborting a deduplicated call leaves nothing in flight", async () => {
    onRpc("/probe", () => ({ ok: true }));
    const indicator = await withIndicator(async () => {
        const first = rpc("/probe", { a: 2 }, { dedup: true });
        const second = rpc("/probe", { a: 2 }, { dedup: true });
        first.catch(() => {});
        first.abort();
        await second;
    });
    expect(indicator.rpcIds.size).toBe(0);
    expect(".o_loading_indicator").toHaveCount(0);
});

test("a silent call is never counted at all", async () => {
    onRpc("/probe", () => ({ ok: true }));
    const indicator = await withIndicator(async () => {
        await rpc("/probe", {}, { silent: true });
    });
    expect(indicator.rpcIds.size).toBe(0);
    expect(".o_loading_indicator").toHaveCount(0);
});
