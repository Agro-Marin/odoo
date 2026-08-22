// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import {
    forbidden,
    OVERRIDDEN_EXCEPTIONS,
    registerErrorNotifications,
    sessionExpired,
} from "@web/public/error_notifications_registry";

describe.current.tags("headless");

function fakeCategory() {
    /** @type {Map<string, any>} */
    const entries = new Map();
    /** @type {string[]} */
    const forced = [];
    const category = {
        entries,
        forced,
        /**
         * @param {string} name
         * @param {any} value
         * @param {{ force?: boolean }} [options]
         */
        add(name, value, { force = false } = {}) {
            if (entries.has(name) && !force) {
                throw new Error(`duplicate registration for "${name}"`);
            }
            if (force) {
                forced.push(name);
            }
            entries.set(name, value);
            return category;
        },
    };
    return category;
}

test("every exception in the map gets a sticky warning carrying its title", () => {
    const category = fakeCategory();
    registerErrorNotifications(
        category,
        new Map([
            ["some.Exception", "Some title"],
            ["other.Exception", "Other title"],
        ]),
    );
    expect(category.entries.get("some.Exception")).toEqual({
        title: "Some title",
        type: "warning",
        sticky: true,
    });
    expect(category.entries.get("other.Exception")).toEqual({
        title: "Other title",
        type: "warning",
        sticky: true,
    });
});

test("the two richer presentations are applied last, and win", () => {
    const category = fakeCategory();
    registerErrorNotifications(
        category,
        new Map([
            ["werkzeug.exceptions.Forbidden", "A bare title"],
            ["some.other.Exception", "Another"],
        ]),
    );
    expect(category.entries.get("werkzeug.exceptions.Forbidden")).toBe(forbidden);
    expect(category.entries.get("odoo.http.SessionExpiredException")).toBe(
        sessionExpired,
    );
    expect(category.forced).toEqual(Object.keys(OVERRIDDEN_EXCEPTIONS));
});

test("without force, the second claim on a name would throw", () => {
    const category = fakeCategory();
    category.add("werkzeug.exceptions.Forbidden", { title: "A bare title" });
    expect(() => category.add("werkzeug.exceptions.Forbidden", forbidden)).toThrow(
        /duplicate registration/,
    );
});

test("both presentations are sticky warnings, so neither self-dismisses", () => {
    for (const entry of [sessionExpired, forbidden]) {
        expect(entry.type).toBe("warning");
        expect(entry.sticky).toBe(true);
        expect(String(entry.title).length).toBeGreaterThan(0);
        expect(String(entry.message).length).toBeGreaterThan(0);
    }
});

test("the session-expired button reloads through browser, not window", () => {
    let reloads = 0;
    patchWithCleanup(browser.location, { reload: () => reloads++ });
    const buttons = sessionExpired.buttons ?? [];
    expect(buttons).toHaveLength(1);
    buttons[0].onClick();
    expect(reloads).toBe(1);
});
