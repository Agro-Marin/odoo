import { OutdatedPageWatcherService } from "@bus/outdated_page_watcher_service";
import { lastNotificationIdKey } from "@bus/services/bus_service";
import {
    CONNECTION_STATE,
    WEBSOCKET_CLOSE_CODES,
} from "@bus/workers/websocket_worker_constants";
import { after, describe, expect, test } from "@odoo/hoot";
import { on, runAllTimers, waitFor } from "@odoo/hoot-dom";
import { EventBus } from "@odoo/owl";
import {
    asyncStep,
    contains,
    getService,
    MockServer,
    mountWithCleanup,
    onRpc,
    waitForSteps,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { WebClient } from "@web/webclient/webclient";

import {
    addBusServiceListeners,
    defineBusModels,
    startBusService,
} from "./bus_test_helpers.js";

defineBusModels();
describe.current.tags("desktop");

test("disconnect during vacuum should ask for reload", async () => {
    // Auto-removed (`after`) so this listener on the shared `browser.location`
    // mock does not leak a stray "reload" step into later suites.
    after(on(browser.location, "reload", () => asyncStep("reload")));
    addBusServiceListeners(
        ["BUS:CONNECT", () => asyncStep("BUS:CONNECT")],
        ["BUS:DISCONNECT", () => asyncStep("BUS:DISCONNECT")],
        ["BUS:RECONNECTING", () => asyncStep("BUS:RECONNECTING")],
        ["BUS:RECONNECT", () => asyncStep("BUS:RECONNECT")],
    );
    onRpc("/bus/has_missed_notifications", () => true);
    await mountWithCleanup(WebClient);
    getService("legacy_multi_tab").setSharedValue(lastNotificationIdKey(), 1);
    startBusService();
    expect(await getService("multi_tab").isOnMainTab()).toBe(true);
    await runAllTimers();
    await waitForSteps(["BUS:CONNECT"]);
    MockServer.env["bus.bus"]._simulateDisconnection(
        WEBSOCKET_CLOSE_CODES.ABNORMAL_CLOSURE,
    );
    await waitForSteps(["BUS:DISCONNECT", "BUS:RECONNECTING"]);
    await runAllTimers();
    await waitForSteps(["BUS:RECONNECT"]);
    await waitFor(".o_notification");
    expect(".o_notification_content:first").toHaveText(
        "The page is out of date. Save your work and refresh to get the latest updates and avoid potential issues.",
    );
    await contains(".o_notification button:contains(Refresh)").click();
    await waitForSteps(["reload"]);
});

test("reconnect after going offline after bus gc should ask for reload", async () => {
    addBusServiceListeners(
        ["BUS:CONNECT", () => asyncStep("BUS:CONNECT")],
        ["BUS:DISCONNECT", () => asyncStep("BUS:DISCONNECT")],
    );
    onRpc("/bus/has_missed_notifications", () => true);
    await mountWithCleanup(WebClient);
    getService("legacy_multi_tab").setSharedValue(lastNotificationIdKey(), 1);
    startBusService();
    expect(await getService("multi_tab").isOnMainTab()).toBe(true);
    await runAllTimers();
    await waitForSteps(["BUS:CONNECT"]);
    browser.dispatchEvent(new Event("offline"));
    await waitForSteps(["BUS:DISCONNECT"]);
    browser.dispatchEvent(new Event("online"));
    await runAllTimers();
    await waitForSteps(["BUS:CONNECT"]);
    await waitFor(".o_notification");
    expect(".o_notification_content:first").toHaveText(
        "The page is out of date. Save your work and refresh to get the latest updates and avoid potential issues.",
    );
});

test("J10: a DISCONNECTED first worker state is not treated as a prior connection", async () => {
    // A tab restored while the server is down/restarting joins a worker whose
    // REPLAYED state is DISCONNECTED (a failed attempt or `_stop()`), not
    // CONNECTING. That must not count as "already connected": probing on the
    // subsequent first BUS:CONNECT would compare a stale (GC'd) watermark
    // against the server and raise a sticky false "out of date" spread to every
    // tab. Driven at the unit level: the multi-tab replay path (a late-joining
    // client seeing DISCONNECTED first) is not reproducible in the
    // single-environment browser harness, which always shows a tab the worker's
    // own IDLE→CONNECTING→CONNECTED lifecycle.
    const busService = new EventBus();
    const services = {
        bus_service: busService,
        // Spy: `checkHasMissedNotifications` consults `isOnMainTab` — a call
        // here means a probe was (wrongly) attempted.
        multi_tab: {
            isOnMainTab: () => {
                asyncStep("probe-attempted");
                return Promise.resolve(true);
            },
        },
        legacy_multi_tab: {
            bus: new EventBus(),
            getSharedValue: () => 1, // non-empty watermark: probe not short-circuited
            setSharedValue: () => {},
        },
        notification: { add: () => () => {} },
    };
    new OutdatedPageWatcherService({}, services);
    // First observed worker state is the replayed DISCONNECTED, then a genuine
    // first connect follows.
    busService.trigger("BUS:WORKER_STATE_UPDATED", CONNECTION_STATE.DISCONNECTED);
    busService.trigger("BUS:CONNECT");
    await runAllTimers();
    // The first connect after joining a disconnected worker must NOT probe.
    await waitForSteps([]);
});

test("J9: joining while connecting does not probe missed notifications on the first connect", async () => {
    // On a browser session restore every tab joins a worker connecting for the
    // first time; treating that as "already connected" would compare a stale
    // watermark against a GC'd server bus and show a sticky false "out of date".
    onRpc("/bus/has_missed_notifications", () => {
        asyncStep("probe");
        return false;
    });
    addBusServiceListeners(["BUS:CONNECT", () => asyncStep("BUS:CONNECT")]);
    await mountWithCleanup(WebClient);
    getService("legacy_multi_tab").setSharedValue(lastNotificationIdKey(), 1);
    startBusService();
    expect(await getService("multi_tab").isOnMainTab()).toBe(true);
    await runAllTimers();
    // The first connect must NOT trigger the missed-notification probe.
    await waitForSteps(["BUS:CONNECT"]);
});
