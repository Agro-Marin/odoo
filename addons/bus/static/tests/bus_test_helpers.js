import { busService } from "@bus/services/bus_service";
import { WEBSOCKET_CLOSE_CODES } from "@bus/workers/websocket_worker_constants";
import { after, expect, registerDebugInfo } from "@odoo/hoot";
import { on, runAllTimers, waitUntil } from "@odoo/hoot-dom";
import { Deferred } from "@odoo/hoot-mock";
import {
    asyncStep,
    defineModels,
    getMockEnv,
    getService,
    MockServer,
    mockService,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { deepEqual } from "@web/core/utils/collections/objects";
import { patch } from "@web/core/utils/patch";

import { BusBus } from "./mock_server/mock_models/bus_bus.js";
import { IrWebSocket } from "./mock_server/mock_models/ir_websocket.js";
import { getWebSocketWorker, onWebsocketEvent } from "./mock_websocket.js";

/**
 * @typedef {[
 *  env?: OdooEnv,
 *  type: string,
 *  payload: NotificationPayload,
 *  options?: ExpectedNotificationOptions,
 * ]} ExpectedNotification
 *
 * @typedef {{
 *  received?: boolean;
 * }} ExpectedNotificationOptions
 *
 * @typedef {Record<string, any>} NotificationPayload
 *
 * @typedef {import("@web/env").OdooEnv} OdooEnv
 * @typedef {import("@bus/workers/websocket_worker").WorkerAction} WorkerAction
 */

//-----------------------------------------------------------------------------
// Setup
//-----------------------------------------------------------------------------

patch(busService, {
    _onMessage(env, id, type, payload) {
        // Generic handlers (namely: debug info)
        if (type in busMessageHandlers) {
            busMessageHandlers[type](env, id, payload);
        } else {
            registerDebugInfo("bus message", { id, type, payload });
        }

        // Notifications
        if (!busNotifications.has(env)) {
            busNotifications.set(env, []);
            after(() => busNotifications.clear());
        }
        busNotifications.get(env).push({ id, type, payload });
    },
});

/**
 * Normalize the `[env?, type, payload, options]` tuple (the leading `env` is
 * optional and defaults to the current mock env).
 *
 * @param {ExpectedNotification} notification
 */
const normalizeExpected = ([env, type, payload, options]) => {
    if (typeof env === "string") {
        [env, type, payload, options] = [getMockEnv(), env, type, payload];
    }
    return {
        env,
        type,
        payload,
        shouldHaveReceived: Boolean(options?.received ?? true),
    };
};

/**
 * The first delivered notification matching `type` (and `payload`, when one is
 * expected). Does NOT consume it.
 *
 * @param {ReturnType<typeof normalizeExpected>} expected
 */
const findNotification = ({ env, type, payload }) => {
    const envNotifications = busNotifications.get(env) || [];
    const hasPayload = payload !== null && payload !== undefined;
    return envNotifications.find(
        (n) => n.type === type && (!hasPayload || matchPayload(n.payload, payload)),
    );
};

/**
 * Human-readable description of an expected notification.
 *
 * @param {ReturnType<typeof normalizeExpected>} expected
 */
const describeExpected = ({ type, payload }) =>
    `Notification of type ${type}${
        payload !== null && payload !== undefined
            ? ` with payload ${JSON.stringify(payload)}`
            : ""
    }`;

/**
 * Assert that a positive expectation was received; compares the ACTUAL payload
 * to the expected one (a real, non-vacuous check).
 *
 * @param {ReturnType<typeof normalizeExpected>} expected
 * @param {object} [found] the notification consumed while waiting, if any.
 */
const assertReceived = (expected, found) => {
    const message = `${describeExpected(expected)} not received.`;
    expect(Boolean(found)).toBe(true, { message });
    if (found) {
        const { payload } = expected;
        if (payload !== null && payload !== undefined) {
            if (typeof payload === "function") {
                // Boolean(): findNotification matched this payload with truthy
                // semantics; asserting strict `true` here would fail matchers
                // that return the matched value (e.g. a record id).
                expect(Boolean(payload(found.payload))).toBe(true, { message });
            } else {
                expect(found.payload).toEqual(payload, { message });
            }
        }
    }
};

/**
 * Assert that a negative expectation was NOT received. Called only after the
 * delivery window has settled (see `waitNotifications`).
 *
 * @param {ReturnType<typeof normalizeExpected>} expected
 */
const assertNotReceived = (expected) => {
    const found = findNotification(expected);
    expect(found).toBe(undefined, {
        message: `${describeExpected(expected)} was received but should NOT have been.`,
    });
};

/**
 * @param {NotificationPayload} payload
 * @param {NotificationPayload | ((payload: NotificationPayload) => boolean)} matcher
 */
const matchPayload = (payload, matcher) =>
    typeof matcher === "function" ? matcher(payload) : deepEqual(payload, matcher);

class LockedWebSocket extends WebSocket {
    constructor() {
        super(...arguments);

        this.addEventListener("open", (ev) => {
            ev.stopImmediatePropagation();

            this.dispatchEvent(new Event("error"));
            this.close(WEBSOCKET_CLOSE_CODES.ABNORMAL_CLOSURE);
        });
    }
}

/** @type {Record<string, (env: OdooEnv, id: string, payload: any) => any>} */
const busMessageHandlers = {};
/** @type {Map<OdooEnv, { id: number, type: string, payload: NotificationPayload }[]>} */
const busNotifications = new Map();

const viewsRegistry = registry.category("bus.view.archs");
viewsRegistry.category("activity").add(
    "default",
    /* xml */ `
        <activity><templates /></activity>
    `,
);
viewsRegistry.category("form").add("default", /* xml */ `<form />`);
viewsRegistry
    .category("kanban")
    .add("default", /* xml */ `<kanban><templates /></kanban>`);
viewsRegistry.category("list").add("default", /* xml */ `<list />`);
viewsRegistry.category("search").add("default", /* xml */ `<search />`);

viewsRegistry.category("form").add(
    "res.partner",
    /* xml */ `
    <form>
        <sheet>
            <field name="name" />
        </sheet>
        <chatter/>
    </form>`,
);

// should be enough to decide whether or not notifications/channel
// subscriptions... are received.
const TIMEOUT = 2000;

//-----------------------------------------------------------------------------
// Exports
//-----------------------------------------------------------------------------

/**
 * Useful to display debug information about bus events in tests.
 *
 * @param {string} type
 * @param {(env: OdooEnv, id: string, payload: any) => any} handler
 */
export function addBusMessageHandler(type, handler) {
    busMessageHandlers[type] = handler;
}

/**
 * Patches the bus service to add given event listeners immediatly when it starts.
 *
 * @param  {...[string, (event: CustomEvent) => any]} listeners
 */
export function addBusServiceListeners(...listeners) {
    mockService("bus_service", (env, dependencies) => {
        const busServiceInstance = busService.start(env, dependencies);
        for (const [type, handler] of listeners) {
            after(on(busServiceInstance, type, handler));
        }
        return busServiceInstance;
    });
}

export function defineBusModels() {
    return defineModels({ ...webModels, ...busModels });
}

/**
 * Returns a deferred that resolves when a websocket subscription is
 * done.
 *
 * @returns {Deferred<void>}
 */
export function waitUntilSubscribe() {
    const def = new Deferred();
    const timeout = setTimeout(() => handleResult(false), TIMEOUT);

    function handleResult(success) {
        clearTimeout(timeout);
        offWebsocketEvent();
        const message = success
            ? "Websocket subscription received."
            : "Websocket subscription not received.";
        expect(success).toBe(true, { message });
        if (success) {
            def.resolve();
        } else {
            def.reject(new Error(message));
        }
    }
    const offWebsocketEvent = onWebsocketEvent("subscribe", () => handleResult(true));
    return def;
}

/**
 * Returns a deferred that resolves when the given channel addition/deletion
 * occurs. Resolve immediately if the operation was already done.
 *
 * @param {string[]} channels
 * @param {object} [options={}]
 * @param {"add" | "delete"} [options.operation="add"]
 * @returns {Promise<void>}
 */
export async function waitForChannels(channels, { operation = "add" } = {}) {
    const { env } = MockServer;
    const def = new Deferred();
    let done = false;
    let failTimeout;

    /**
     * @param {boolean} crashOnFail
     */
    function check(crashOnFail) {
        if (done) {
            return;
        }
        const userChannels = new Set(env["bus.bus"].channelsByUser[env.uid]);
        const success = channels.every((c) =>
            operation === "add" ? userChannels.has(c) : !userChannels.has(c),
        );
        if (!success && !crashOnFail) {
            return;
        }
        clearTimeout(failTimeout);
        offWebsocketEvent();
        const message = (pass) =>
            pass
                ? `Channel(s) ${channels} ${operation === "add" ? `added` : `deleted`}`
                : `Waited ${TIMEOUT}ms for ${channels} to be ${
                      operation === "add" ? `added` : `deleted`
                  }`;
        expect(success).toBe(true, { message });
        if (success) {
            def.resolve();
        } else {
            def.reject(new Error(message(false)));
        }
        done = true;
    }

    after(() => check(true));
    const offWebsocketEvent = onWebsocketEvent("subscribe", () => check(false));

    await runAllTimers();

    failTimeout = setTimeout(() => check(true), TIMEOUT);
    check(false);

    return def;
}

/**
 * Wait for the expected notifications to be received/not received. Returns
 * a deferred that resolves when the assertion is done.
 *
 * @param {ExpectedNotification[]} expectedNotifications
 * @returns {Promise<void>}
 */
export async function waitNotifications(...expectedNotifications) {
    const normalized = expectedNotifications.map(normalizeExpected);
    const positives = normalized.filter((n) => n.shouldHaveReceived);
    const negatives = normalized.filter((n) => !n.shouldHaveReceived);

    // Wait for every POSITIVE to be delivered (postMessage delivery is async).
    // Consume matches as they arrive so a single notification cannot satisfy
    // two distinct expectations.
    const found = new Map();
    const remaining = new Set(positives);
    await waitUntil(
        () => {
            for (const expected of remaining) {
                const match = findNotification(expected);
                if (match) {
                    const envNotifications = busNotifications.get(expected.env);
                    envNotifications.splice(envNotifications.indexOf(match), 1);
                    found.set(expected, match);
                    remaining.delete(expected);
                }
            }
            return remaining.size === 0;
        },
        { timeout: TIMEOUT },
    ).catch(() => {});
    for (const expected of positives) {
        assertReceived(expected, found.get(expected));
    }
    // Negatives are asserted only AFTER a settling window: an erroneous
    // delivery to a stopped/left tab is an async postMessage (preceded by the
    // worker's debounced sends), so it would not yet be visible on the first
    // waitUntil tick. Flush the mocked clock and microtasks first, then assert
    // the notification genuinely never arrived — so a regression that keeps
    // delivering to a stopped tab now fails instead of passing vacuously.
    if (negatives.length) {
        await runAllTimers();
        for (const expected of negatives) {
            assertNotReceived(expected);
        }
    }
    busNotifications.clear();
}

/**
 * Registers an asynchronous step on actions received by the websocket worker that
 * match the given list of target actions.
 *
 * @param {WorkerAction[]} targetActions
 */
export function stepWorkerActions(targetActions) {
    patchWithCleanup(getWebSocketWorker(), {
        _onClientMessage(_, { action }) {
            if (targetActions.includes(action)) {
                asyncStep(action);
            }
            return super._onClientMessage(...arguments);
        },
    });
}

/**
 * Lock the websocket connection until the returned function is called. Useful
 * to simulate server being unavailable.
 */
export function lockWebsocketConnect() {
    return patchWithCleanup(window, { WebSocket: LockedWebSocket });
}

/**
 * @param {OdooEnv} [env]
 */
export async function startBusService(env) {
    const busService = env ? env.services.bus_service : getService("bus_service");
    busService.start();
    await runAllTimers();
}

export const busModels = { BusBus, IrWebSocket };
