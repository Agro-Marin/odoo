// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import {
    contains,
    defineActions,
    defineModels,
    getService,
    models,
    mountWithCleanup,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { installActionCacheInvalidation } from "@web/webclient/actions/action_cache_invalidation";
import { BreadcrumbCache } from "@web/webclient/actions/breadcrumb_cache";
import { WebClient } from "@web/webclient/webclient";

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _rec_name = "display_name";

    _records = [
        { id: 1, display_name: "First record" },
        { id: 2, display_name: "Second record" },
    ];
    _views = {
        list: `<list><field name="display_name"/></list>`,
        form: `<form><field name="display_name"/></form>`,
    };
}

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

defineActions([
    {
        id: 3,
        xml_id: "action_3",
        name: "Partners",
        res_model: "partner",
        views: [
            [false, "list"],
            [false, "form"],
        ],
    },
]);

/** Simulate a mutating RPC on ir.actions.act_window reaching the rpcBus. */
function fireActWindowWrite() {
    rpcBus.trigger(RpcEvent.RESPONSE, {
        data: { params: { model: "ir.actions.act_window", method: "write" } },
        settings: { silent: true },
    });
}

test.tags("desktop");
test("act_window write refreshes breadcrumbs in place (no stack rebuild)", async () => {
    onRpc("/web/action/load_breadcrumbs", () => {
        expect.step("/web/action/load_breadcrumbs");
    });

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    await contains(".o_data_cell").click();
    await animationFrame();
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
        "First record",
    ]);

    const am = getService("action");
    const stackBefore = [...am.controllerStack];
    const cacheBefore = am.breadcrumbCache;
    expect.verifySteps([]);

    fireActWindowWrite();
    await animationFrame();
    await animationFrame();

    expect(am.breadcrumbCache).not.toBe(cacheBefore);
    expect.verifySteps(["/web/action/load_breadcrumbs"]);

    expect(am.controllerStack.length).toBe(stackBefore.length);
    expect(am.controllerStack.every((c, i) => c === stackBefore[i])).toBe(true);
    expect(am.controllerStack.some((c) => c.virtual)).toBe(false);
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
        "First record",
    ]);

    await contains(".breadcrumb-item a").click();
    await animationFrame();
    expect(".o_list_view").toHaveCount(1);
    expect(am.controllerStack.at(-1)).toBe(stackBefore[0]);
});

test("act_window write with no active controller is a no-op", async () => {
    await mountWithCleanup(WebClient);
    const am = getService("action");
    expect(am.controllerStack.length).toBe(0);

    fireActWindowWrite();
    await animationFrame();

    expect(am.controllerStack.length).toBe(0);
});

test("any ir.actions.* write clears the /web/action/load cache", async () => {
    await mountWithCleanup(WebClient);

    const cleared = [];
    const onClear = (/** @type {any} */ ev) => cleared.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);

    for (const model of [
        "ir.actions.server",
        "ir.actions.report",
        "ir.actions.client",
        "ir.actions.act_url",
        "ir.actions.act_window",
    ]) {
        rpcBus.trigger(RpcEvent.RESPONSE, {
            data: { params: { model, method: "write" } },
            settings: { silent: true },
        });
    }
    await animationFrame();
    rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear);

    expect(cleared.filter((d) => d === "/web/action/load").length).toBe(5);

    const clearedAfter = [];
    const onClear2 = (/** @type {any} */ ev) => clearedAfter.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear2);
    rpcBus.trigger(RpcEvent.RESPONSE, {
        data: { params: { model: "res.partner", method: "write" } },
        settings: { silent: true },
    });
    await animationFrame();
    rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear2);
    expect(clearedAfter.includes("/web/action/load")).toBe(false);
});

test("installActionCacheInvalidation returns a disposer that removes the listener", async () => {
    /** @type {any} */
    const am = { breadcrumbCache: new BreadcrumbCache(), controllerStack: [] };
    const uninstall = installActionCacheInvalidation(am);

    const cleared = [];
    const onClear = (/** @type {any} */ ev) => cleared.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);

    fireActWindowWrite();
    await animationFrame();
    expect(cleared.filter((d) => d === "/web/action/load").length).toBe(1);

    uninstall();
    fireActWindowWrite();
    await animationFrame();
    expect(cleared.filter((d) => d === "/web/action/load").length).toBe(1);

    uninstall();

    rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear);
});

test("action service exposes the cache-invalidation disposer", async () => {
    await mountWithCleanup(WebClient);
    const am = getService("action");
    expect(typeof am.uninstallActionCacheInvalidation).toBe("function");

    const cleared = [];
    const onClear = (/** @type {any} */ ev) => cleared.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);

    am.uninstallActionCacheInvalidation();
    fireActWindowWrite();
    await animationFrame();
    rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear);

    expect(cleared.includes("/web/action/load")).toBe(false);
});

test.tags("desktop");
test("failed breadcrumb refresh keeps the current names", async () => {
    onRpc("/web/action/load_breadcrumbs", () => {
        expect.step("/web/action/load_breadcrumbs");
        return Promise.reject(new Error("breadcrumbs unavailable"));
    });

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    await contains(".o_data_cell").click();
    await animationFrame();

    fireActWindowWrite();
    await animationFrame();
    await animationFrame();

    expect.verifySteps(["/web/action/load_breadcrumbs"]);
    expect(".o_error_dialog").toHaveCount(0);
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
        "First record",
    ]);
});

/** Simulate a mutating RPC on an arbitrary model reaching the rpcBus. */
function fireWrite(/** @type {any} */ model) {
    rpcBus.trigger(RpcEvent.RESPONSE, {
        data: { params: { model, method: "write" } },
        settings: { silent: true },
    });
}

test("a non-act_window action write clears the cache but skips the refresh", async () => {
    let refreshed = 0;
    onRpc("/web/action/load_breadcrumbs", () => {
        refreshed++;
        return [];
    });
    const cacheBefore = new BreadcrumbCache();
    /** @type {any} */
    const am = {
        breadcrumbCache: cacheBefore,
        controllerStack: [
            { state: { action: 1 }, action: {}, config: { breadcrumbs: [] } },
        ],
        _getBreadcrumbs: () => [],
    };
    const uninstall = installActionCacheInvalidation(am);

    const cleared = [];
    const onClear = (/** @type {any} */ ev) => cleared.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);

    fireWrite("ir.actions.server");
    await animationFrame();

    expect(cleared.includes("/web/action/load")).toBe(true);
    expect(refreshed).toBe(0);
    expect(am.breadcrumbCache).toBe(cacheBefore);

    rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear);
    uninstall();
});

/** Simulate a mutating RPC on `model` with an explicit method reaching the bus. */
function fireMutation(/** @type {any} */ model, /** @type {any} */ method) {
    rpcBus.trigger(RpcEvent.RESPONSE, {
        data: { params: { model, method } },
        settings: { silent: true },
    });
}

test("an ir.embedded.actions create/unlink clears the cache but skips the refresh", async () => {
    // `/web/action/load` inlines the action's embedded actions, so mutating one
    // must bust the cache -- but the model is `ir.embedded.actions`, which a
    // prefix-only `ir.actions.` match misses (the bug this guards). It is not an
    // act_window, so the breadcrumb refresh must NOT run.
    let refreshed = 0;
    onRpc("/web/action/load_breadcrumbs", () => {
        refreshed++;
        return [];
    });
    const cacheBefore = new BreadcrumbCache();
    /** @type {any} */
    const am = {
        breadcrumbCache: cacheBefore,
        controllerStack: [
            { state: { action: 1 }, action: {}, config: { breadcrumbs: [] } },
        ],
        _getBreadcrumbs: () => [],
    };
    const uninstall = installActionCacheInvalidation(am);

    const cleared = [];
    const onClear = (/** @type {any} */ ev) => cleared.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);

    fireMutation("ir.embedded.actions", "create");
    fireMutation("ir.embedded.actions", "unlink");
    await animationFrame();

    expect(cleared.filter((d) => d === "/web/action/load").length).toBe(2);
    expect(refreshed).toBe(0);
    expect(am.breadcrumbCache).toBe(cacheBefore);

    rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear);
    uninstall();
});

test("a write on an unrelated model is ignored entirely", async () => {
    const cacheBefore = new BreadcrumbCache();
    /** @type {any} */
    const am = { breadcrumbCache: cacheBefore, controllerStack: [] };
    const uninstall = installActionCacheInvalidation(am);

    const cleared = [];
    const onClear = (/** @type {any} */ ev) => cleared.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);

    fireWrite("res.partner");
    await animationFrame();

    expect(cleared.includes("/web/action/load")).toBe(false);
    expect(am.breadcrumbCache).toBe(cacheBefore);

    rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear);
    uninstall();
});

test("navigation during the refresh abandons the stale breadcrumb write", async () => {
    const released = new Deferred();
    onRpc("/web/action/load_breadcrumbs", async () => {
        await released;
        return [{ display_name: "Refreshed" }];
    });

    /** @type {any} */
    const staleTip = {
        state: { action: 1 },
        action: {},
        displayName: "Old",
        config: { breadcrumbs: ["ORIGINAL"] },
    };
    /** @type {any} */
    const am = {
        breadcrumbCache: new BreadcrumbCache(),
        controllerStack: [staleTip],
        _getBreadcrumbs: () => ["REBUILT"],
    };
    const uninstall = installActionCacheInvalidation(am);

    fireWrite("ir.actions.act_window");
    await animationFrame();

    am.controllerStack = [{ state: { action: 2 }, action: {}, config: {} }];
    released.resolve();
    await animationFrame();
    await animationFrame();

    expect(staleTip.config.breadcrumbs).toEqual(["ORIGINAL"]);

    uninstall();
});

test.tags("desktop");
test("act_window write during a URL restore refreshes the MOUNTED stack", async () => {
    // A restore in flight proposes a stack; it does not install one. The
    // invalidator therefore still finds the controllers that are actually on
    // screen, refreshes those, and cannot trip over a virtual placeholder.
    const blockLeaf = new Deferred();
    let reads = 0;
    onRpc("/web/action/load_breadcrumbs", () => {
        expect.step("/web/action/load_breadcrumbs");
        return [{ display_name: "First record" }];
    });
    onRpc("web_read", async () => {
        if (reads++) {
            await blockLeaf;
        }
    });

    await mountWithCleanup(WebClient);
    const am = getService("action");
    await am.doAction(3);
    await contains(".o_data_cell").click();
    await animationFrame();
    const mountedStack = am.controllerStack;
    expect(mountedStack.at(-1).isMounted).toBe(true);
    expect.verifySteps([]);

    const restoring = am.loadState({
        action: 3,
        resId: 2,
        actionStack: [
            { action: 3, displayName: "Partners", view_type: "list" },
            { action: 3, displayName: "Second record", resId: 2, view_type: "form" },
        ],
    });
    await animationFrame();

    // The proposal is NOT installed: the live stack is still the mounted one.
    expect(am.controllerStack).toBe(mountedStack);
    expect(am.controllerStack.some((c) => c.virtual)).toBe(false);

    fireActWindowWrite();
    await animationFrame();
    await animationFrame();

    expect.verifySteps(["/web/action/load_breadcrumbs"]);
    expect(".o_error_dialog").toHaveCount(0);

    blockLeaf.resolve();
    await restoring;
    await animationFrame();
    expect(".o_form_view").toHaveCount(1);
});
