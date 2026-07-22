// @ts-check

import { expect, test } from "@odoo/hoot";
import { queryAllTexts } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
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
        // Real RPC:RESPONSE events always carry settings; other listeners
        // (e.g. the loading indicator) read them.
        settings: { silent: true },
    });
}

// Desktop-only: asserts on (and clicks) the `.breadcrumb-item` control-panel
// DOM, which the mobile navbar does not render (mobile collapses breadcrumbs
// into a back button). The cache-flush/stack-preservation logic under test is
// desktop breadcrumb-stack behaviour.
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

    // The display-name cache was flushed and fresh names were fetched.
    expect(am.breadcrumbCache).not.toBe(cacheBefore);
    expect.verifySteps(["/web/action/load_breadcrumbs"]);

    // The stack still holds the same live controllers — not URL-derived
    // virtual replacements that would lose exported view state.
    expect(am.controllerStack.length).toBe(stackBefore.length);
    expect(am.controllerStack.every((c, i) => c === stackBefore[i])).toBe(true);
    expect(am.controllerStack.some((c) => c.virtual)).toBe(false);
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
        "First record",
    ]);

    // Restoring through the breadcrumb reuses the kept controller instead of
    // re-executing the action from scratch.
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
    const onClear = (ev) => cleared.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);

    // Non-act_window action types (server/report/client/act_url) also
    // staleness the action-load disk cache; each must clear it.
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

    // One CLEAR_CACHES("/web/action/load") per action-type write.
    expect(cleared.filter((d) => d === "/web/action/load").length).toBe(5);

    // A non-action model must NOT clear the action cache.
    const clearedAfter = [];
    const onClear2 = (ev) => clearedAfter.push(ev.detail);
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
    // Pins the disposer contract relied on by short-lived managers (web_studio
    // editor): after the returned disposer runs, the rpcBus listener is gone and
    // an ir.actions write no longer clears the /web/action/load cache. Before the
    // fix, the install happened in the ActionManager ctor and nothing disposed
    // it, leaking one listener per Studio entry.
    const am = { breadcrumbCache: {}, controllerStack: [] };
    const uninstall = installActionCacheInvalidation(am);

    const cleared = [];
    const onClear = (ev) => cleared.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);

    fireActWindowWrite();
    await animationFrame();
    expect(cleared.filter((d) => d === "/web/action/load").length).toBe(1);

    // Dispose: the same write is now a no-op — the listener is gone.
    uninstall();
    fireActWindowWrite();
    await animationFrame();
    expect(cleared.filter((d) => d === "/web/action/load").length).toBe(1);

    // Idempotent: a second dispose must not throw.
    uninstall();

    rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear);
});

test("action service exposes the cache-invalidation disposer", async () => {
    // The session-lived webclient manager installs the listener in
    // ``actionService.start`` (not the ctor) and exposes the disposer, so
    // short-lived consumers can tear it down. Disposing here stops further
    // cache clears.
    await mountWithCleanup(WebClient);
    const am = getService("action");
    expect(typeof am.uninstallActionCacheInvalidation).toBe("function");

    const cleared = [];
    const onClear = (ev) => cleared.push(ev.detail);
    rpcBus.addEventListener(RpcEvent.CLEAR_CACHES, onClear);

    am.uninstallActionCacheInvalidation();
    fireActWindowWrite();
    await animationFrame();
    rpcBus.removeEventListener(RpcEvent.CLEAR_CACHES, onClear);

    expect(cleared.includes("/web/action/load")).toBe(false);
});

// Desktop-only: asserts on the `.breadcrumb-item` breadcrumb texts, absent from
// the mobile navbar (see the companion test above).
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

    // The refresh degraded silently: same controllers, same names, no dialog.
    expect.verifySteps(["/web/action/load_breadcrumbs"]);
    expect(".o_error_dialog").toHaveCount(0);
    expect(queryAllTexts(".breadcrumb-item, .o_breadcrumb .active")).toEqual([
        "Partners",
        "First record",
    ]);
});
