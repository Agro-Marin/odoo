// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    defineModels,
    getService,
    makeMockEnv,
    models,
    onRpc,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { RpcEvent } from "@web/core/events";
import { ConnectionLostError, rpcBus, RPCError } from "@web/core/network/rpc";
import { installActionCacheInvalidation } from "@web/webclient/actions/action_cache_invalidation";
import { BreadcrumbCache } from "@web/webclient/actions/breadcrumb_cache";

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _rec_name = "display_name";
    _records = [{ id: 1, display_name: "First record" }];
    _views = { list: `<list><field name="display_name"/></list>` };
}

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

function makeError(mode) {
    if (mode === "ok") {
        return undefined;
    }
    if (mode === "rpc") {
        const error = new RPCError("Access denied");
        error.exceptionName = "odoo.exceptions.AccessError";
        return error;
    }
    return new ConnectionLostError("/web/dataset/call_kw");
}

function fireWrite(model, mode) {
    rpcBus.trigger(RpcEvent.RESPONSE, {
        data: { params: { model, method: "write" } },
        url: "/web/dataset/call_kw",
        settings: { silent: true },
        error: makeError(mode),
    });
}

async function recordClearCaches(fn) {
    const seen = [];
    const onClear = (ev) => seen.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);
    try {
        await fn();
        await animationFrame();
    } finally {
        rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear);
    }
    return seen;
}

function makeFakeActionManager() {
    return {
        breadcrumbCache: new BreadcrumbCache(),
        controllerStack: [],
        _getBreadcrumbs: () => [],
    };
}

describe("action_cache_invalidation", () => {
    test("flushes on a successful act_window write", async () => {
        const uninstall = installActionCacheInvalidation(makeFakeActionManager());
        const seen = await recordClearCaches(() =>
            fireWrite("ir.actions.act_window", "ok"),
        );
        uninstall();
        expect(seen).toEqual(["/web/action/load"]);
    });

    test("SKIPS a write refused by the server (nothing changed)", async () => {
        const uninstall = installActionCacheInvalidation(makeFakeActionManager());
        const seen = await recordClearCaches(() =>
            fireWrite("ir.actions.act_window", "rpc"),
        );
        uninstall();
        expect(seen).toEqual([]);
    });

    test("still flushes on a lost response (the write may have committed)", async () => {
        const uninstall = installActionCacheInvalidation(makeFakeActionManager());
        const seen = await recordClearCaches(() =>
            fireWrite("ir.actions.act_window", "lost"),
        );
        uninstall();
        expect(seen).toEqual(["/web/action/load"]);
    });

    test("the returned disposer really detaches the rpcBus listener", async () => {
        const uninstall = installActionCacheInvalidation(makeFakeActionManager());
        uninstall();
        const seen = await recordClearCaches(() =>
            fireWrite("ir.actions.act_window", "ok"),
        );
        expect(seen).toEqual([]);
    });
});

describe("currency_service", () => {
    function trackReload() {
        onRpc("res.currency", "get_all_currencies", () => {
            expect.step("get_all_currencies");
            return {};
        });
    }

    test("reloads currencies on a successful res.currency write", async () => {
        trackReload();
        await makeMockEnv();
        getService("currency");
        fireWrite("res.currency", "ok");
        await animationFrame();
        expect.verifySteps(["get_all_currencies"]);
    });

    test("skips a write refused by the server", async () => {
        trackReload();
        await makeMockEnv();
        getService("currency");
        fireWrite("res.currency", "rpc");
        await animationFrame();
        expect.verifySteps([]);
    });

    test("NOW reloads on a lost response (rate change may have committed)", async () => {
        trackReload();
        await makeMockEnv();
        getService("currency");
        fireWrite("res.currency", "lost");
        await animationFrame();
        expect.verifySteps(["get_all_currencies"]);
    });
});

describe("view_service", () => {
    test("flushes get_views on a successful ir.ui.view write", async () => {
        await makeMockEnv();
        getService("view");
        const seen = await recordClearCaches(() => fireWrite("ir.ui.view", "ok"));
        expect(seen).toEqual(["get_views"]);
    });

    test("NOW skips a write refused by the server", async () => {
        await makeMockEnv();
        getService("view");
        const seen = await recordClearCaches(() => fireWrite("ir.ui.view", "rpc"));
        expect(seen).toEqual([]);
    });

    test("still flushes on a lost response", async () => {
        await makeMockEnv();
        getService("view");
        const seen = await recordClearCaches(() => fireWrite("ir.ui.view", "lost"));
        expect(seen).toEqual(["get_views"]);
    });
});

describe("reload_company_service (successOnly)", () => {
    async function setupReloadTracking() {
        await makeMockEnv();
        const action = getService("action");
        patchWithCleanup(action, {
            doAction(request, ...rest) {
                if (request === "reload_context") {
                    expect.step("reload_context");
                    return Promise.resolve();
                }
                return super.doAction(request, ...rest);
            },
        });
        getService("reloadCompany");
    }

    test("reloads the context on a successful res.company write", async () => {
        await setupReloadTracking();
        fireWrite("res.company", "ok");
        await animationFrame();
        expect.verifySteps(["reload_context"]);
    });

    test("skips a lost response: a page reload would discard user input", async () => {
        await setupReloadTracking();
        fireWrite("res.company", "lost");
        await animationFrame();
        expect.verifySteps([]);
    });

    test("skips a write refused by the server", async () => {
        await setupReloadTracking();
        fireWrite("res.company", "rpc");
        await animationFrame();
        expect.verifySteps([]);
    });
});
