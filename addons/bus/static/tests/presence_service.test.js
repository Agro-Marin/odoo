import { defineBusModels } from "@bus/../tests/bus_test_helpers";
import { describe, expect, test } from "@odoo/hoot";
import {
    getService,
    makeMockEnv,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

defineBusModels();
describe.current.tags("desktop");

test("J18: blur triggers window_focus(false)", async () => {
    const env = await makeMockEnv();
    getService("presence");
    const focusEvents = [];
    env.bus.addEventListener("window_focus", ({ detail }) => focusEvents.push(detail));
    // A genuine blur must propagate to same-tab listeners as loss of focus
    // (mail's out-of-focus counter relies on hearing the `false`). NB: the mock
    // localStorage echoes its own `storage` event same-tab, so the focus write
    // re-emits `window_focus`; assert the emitted values rather than a count.
    browser.dispatchEvent(new Event("blur"));
    expect(focusEvents).toInclude(false);
    expect(focusEvents).not.toInclude(true);
});

test("J18: a storage event with null newValue keeps inactivity sane", async () => {
    await makeMockEnv();
    const presence = getService("presence");
    // A "clear site data" in another tab removes the key (newValue === null).
    // Parsing it would poison lastPresenceTime and make getInactivityPeriod
    // return an epoch-scale number; the guard must ignore it.
    browser.dispatchEvent(
        new StorageEvent("storage", {
            key: "presence.lastPresence",
            newValue: null,
        }),
    );
    const inactivity = presence.getInactivityPeriod();
    expect(inactivity).toBeGreaterThanOrEqual(0);
    expect(inactivity).toBeLessThan(60_000);
});

test("J18: a bfcache pageshow restores the real focus state", async () => {
    const env = await makeMockEnv();
    getService("presence");
    // pagehide force-unfocuses the tab.
    browser.dispatchEvent(new Event("pagehide"));
    const focusEvents = [];
    env.bus.addEventListener("window_focus", ({ detail }) => focusEvents.push(detail));
    // The browser does not replay a `focus` event for an already-focused
    // restored page, so pageshow must restore focus from document.hasFocus().
    patchWithCleanup(document, { hasFocus: () => true });
    browser.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    expect(focusEvents).toInclude(true);
    expect(focusEvents).not.toInclude(false);
});
