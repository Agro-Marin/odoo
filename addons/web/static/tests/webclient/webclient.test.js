// @ts-check

import { expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import {
    contains,
    makeMockEnv,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { watchServiceWorkerUpdates, WebClient } from "@web/webclient/webclient";

test("can be rendered", async () => {
    await mountWithCleanup(WebClient);

    expect(`header > nav.o_main_navbar`).toHaveCount(1);
});

test("can render a main component", async () => {
    class MyComponent extends Component {
        static props = {};
        static template = xml`<span class="chocolate">MyComponent</span>`;
    }

    const env = await makeMockEnv();
    registry.category("main_components").add("mycomponent", { Component: MyComponent });

    await mountWithCleanup(WebClient, { env });

    expect(`.chocolate`).toHaveCount(1);
});

test.tags("desktop");
test("control-click <a href/> in a standalone component", async () => {
    class MyComponent extends Component {
        static props = {};
        static template = xml`<a href="#" class="MyComponent" t-on-click="onclick">Some link</a>`;

        /** @param {MouseEvent} ev */
        onclick(ev) {
            expect.step(ev.ctrlKey ? "ctrl-click" : "click");
            // Necessary in order to prevent the test browser to open in new tab on ctrl-click
            ev.preventDefault();
        }
    }

    await mountWithCleanup(MyComponent);

    expect.verifySteps([]);

    await contains(".MyComponent").click();
    await contains(".MyComponent").click({ ctrlKey: true });

    expect.verifySteps(["click", "ctrl-click"]);
});

test.tags("desktop");
test("control-click propagation stopped on <a href/>", async () => {
    expect.assertions(3);

    patchWithCleanup(WebClient.prototype, {
        /** @param {MouseEvent} ev */
        onGlobalClick(ev) {
            super.onGlobalClick(ev);
            if (ev.ctrlKey) {
                expect(ev.defaultPrevented).toBe(false, {
                    message:
                        "the global click should not prevent the default behavior on ctrl-click an <a href/>",
                });
                // Necessary in order to prevent the test browser to open in new tab on ctrl-click
                ev.preventDefault();
            }
        },
    });

    class MyComponent extends Component {
        static props = {};
        static template = xml`<a href="#" class="MyComponent" t-on-click="onclick">Some link</a>`;

        /** @param {MouseEvent} ev */
        onclick(ev) {
            expect.step(ev.ctrlKey ? "ctrl-click" : "click");
            // Necessary in order to prevent the test browser to open in new tab on ctrl-click
            ev.preventDefault();
        }
    }

    await mountWithCleanup(WebClient);

    registry.category("main_components").add("mycomponent", { Component: MyComponent });
    await animationFrame();

    expect.verifySteps([]);

    await contains(".MyComponent").click();
    await contains(".MyComponent").click({ ctrlKey: true });

    expect.verifySteps(["click"]);
});

// -----------------------------------------------------------------------------
// Service worker update lifecycle (watchServiceWorkerUpdates)
// -----------------------------------------------------------------------------

class MockServiceWorker extends EventTarget {
    /** @param {string} state */
    constructor(state) {
        super();
        this.state = state;
    }

    /** @param {{ type: string }} message */
    postMessage(message) {
        expect.step(`postMessage:${message.type}`);
    }

    /** @param {string} state */
    setState(state) {
        this.state = state;
        this.dispatchEvent(new Event("statechange"));
    }
}

class MockRegistration extends EventTarget {
    /** @type {MockServiceWorker | null} */
    active = null;
    /** @type {MockServiceWorker | null} */
    installing = null;
    /** @type {MockServiceWorker | null} */
    waiting = null;

    update() {
        expect.step("update");
        return Promise.resolve();
    }
}

/**
 * Captures the `visibilitychange` listener instead of attaching it to the
 * real window (it would leak across tests and fire on real tab switches).
 *
 * @returns {Array<() => void>} the captured visibility handlers
 */
function captureVisibilityHandlers() {
    /** @type {Array<() => void>} */
    const handlers = [];
    patchWithCleanup(browser, {
        /**
         * @param {string} type
         * @param {() => void} handler
         */
        addEventListener(type, handler) {
            expect(type).toBe("visibilitychange");
            handlers.push(handler);
        },
    });
    return handlers;
}

test("SW update: posts SKIP_WAITING when an updated worker finishes installing", async () => {
    captureVisibilityHandlers();
    const registration = new MockRegistration();
    registration.active = new MockServiceWorker("activated");
    watchServiceWorkerUpdates(/** @type {any} */ (registration));
    expect.verifySteps([]);

    // A new version is discovered and starts installing.
    registration.installing = new MockServiceWorker("installing");
    registration.dispatchEvent(new Event("updatefound"));
    expect.verifySteps([]);

    // Once installed (while an old version is still active), it must be told
    // to skip the waiting state instead of parking until every tab closes.
    registration.installing.setState("installed");
    expect.verifySteps(["postMessage:SKIP_WAITING"]);

    // Further state changes do not re-post.
    registration.installing.setState("activating");
    registration.installing.setState("activated");
    expect.verifySteps([]);
});

test("SW update: first install keeps the natural lifecycle (no SKIP_WAITING)", async () => {
    captureVisibilityHandlers();
    const registration = new MockRegistration();
    // No active worker: this is the very first install, not an update.
    watchServiceWorkerUpdates(/** @type {any} */ (registration));

    registration.installing = new MockServiceWorker("installing");
    registration.dispatchEvent(new Event("updatefound"));
    registration.installing.setState("installed");
    expect.verifySteps([]);
});

test("SW update: a worker already waiting at boot is promoted immediately", async () => {
    captureVisibilityHandlers();
    const registration = new MockRegistration();
    registration.active = new MockServiceWorker("activated");
    // A previous session left an updated worker parked in `waiting`.
    registration.waiting = new MockServiceWorker("installed");
    watchServiceWorkerUpdates(/** @type {any} */ (registration));
    expect.verifySteps(["postMessage:SKIP_WAITING"]);
});

test("SW update: periodic and visibility-triggered registration.update()", async () => {
    const visibilityHandlers = captureVisibilityHandlers();
    const registration = new MockRegistration();
    registration.active = new MockServiceWorker("activated");
    watchServiceWorkerUpdates(/** @type {any} */ (registration));
    expect(visibilityHandlers).toHaveLength(1);
    expect.verifySteps([]);

    const SIX_HOURS = 6 * 60 * 60 * 1000;
    await advanceTime(SIX_HOURS);
    expect.verifySteps(["update"]);
    await advanceTime(SIX_HOURS);
    expect.verifySteps(["update"]);

    // Returning to a visible tab triggers one cheap update check.
    // (document.visibilityState is "visible" in the test runner.)
    visibilityHandlers[0]();
    expect.verifySteps(["update"]);
});
