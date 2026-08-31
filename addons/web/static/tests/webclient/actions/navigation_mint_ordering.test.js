// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { ActionManager } from "@web/webclient/actions/action_service";

describe.current.tags("desktop");

/**
 * `switchView` and `restore` bump the navigation epoch, which supersedes every
 * in-flight `doAction` load. A call that ends up doing nothing — or that throws
 * because its target does not exist — must not pay that price: the user's
 * pending navigation would be dropped and nothing would replace it.
 */
function makeManager() {
    const am = new ActionManager(
        /** @type {any} */ ({
            bus: new EventBus(),
            services: { title: { setParts() {} }, dialog: { closeAll() {} } },
        }),
        /** @type {any} */ ({
            current: {},
            pushState() {},
            stateToUrl: () => "",
            hideKeyFromUrl() {},
        }),
    );
    am._confirmLeave = async () => true;
    return am;
}

test("a switchView refused because a dialog is open does not supersede", async () => {
    const am = makeManager();
    am.dialog = /** @type {any} */ ({});
    const inFlight = am.navigation.mint();

    await am.switchView("form");

    expect(inFlight.isCurrent()).toBe(true);
});

test("a switchView refused because a dispatch is pending does not supersede", async () => {
    const am = makeManager();
    am._pendingDispatch = /** @type {any} */ ({ baseStack: [] });
    const inFlight = am.navigation.mint();

    await am.switchView("form");

    expect(inFlight.isCurrent()).toBe(true);
});

test("a switchView for a view the action does not have does not supersede", async () => {
    const am = makeManager();
    am.controllerStack = [
        /** @type {any} */ ({
            jsId: "c1",
            action: { jsId: "a1", type: "ir.actions.act_window", controllers: {} },
            views: [{ type: "list", multiRecord: true }],
            props: { type: "list" },
            config: {},
        }),
    ];
    const inFlight = am.navigation.mint();

    await expect(am.switchView("graph")).rejects.toThrow();

    expect(inFlight.isCurrent()).toBe(true);
});

test("a restore of an unknown controller does not supersede", async () => {
    const am = makeManager();
    am.controllerStack = [];
    const inFlight = am.navigation.mint();

    await expect(am.restore("nope")).rejects.toThrow();

    expect(inFlight.isCurrent()).toBe(true);
});

test("a switchView that proceeds still supersedes the load it replaces", async () => {
    const am = makeManager();
    am._getViewInfo = /** @type {any} */ (
        (/** @type {any} */ view) => ({
            props: { type: view.type },
            config: {},
            currentState: {},
            displayName: view.type,
        })
    );
    am._dispatchInline = /** @type {any} */ (async () => {});
    am.controllerStack = [
        /** @type {any} */ ({
            jsId: "c1",
            action: { jsId: "a1", type: "ir.actions.act_window", controllers: {} },
            view: { type: "list", multiRecord: true },
            views: [
                { type: "list", multiRecord: true },
                { type: "form", multiRecord: false },
            ],
            props: { type: "list" },
            config: {},
            state: {},
            currentState: {},
            isMounted: true,
        }),
    ];
    const inFlight = am.navigation.mint();

    await am.switchView("form");

    expect(inFlight.isCurrent()).toBe(false);
});
