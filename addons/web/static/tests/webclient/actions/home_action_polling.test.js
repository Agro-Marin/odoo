// @ts-check

/**
 * Characterization of the ``home`` client action's server-wait loop
 * (``webclient/actions/client_actions.js``).
 *
 * It polls ``/web/webclient/version_info`` until the server answers, so the
 * user lands on a booted instance after an install/upgrade. Dispatched for
 * real by ``base_install_request`` and ``spreadsheet_edition``.
 *
 * It used to retry on a FIXED 250 ms period with no attempt cap and no
 * deadline: a server that never came back was hammered at 4 req/s forever
 * while the action's promise never settled. These tests pin the bounded
 * replacement -- exponential backoff up to ``HOME_POLL_MAX_DELAY``, then a
 * ``HOME_POLL_DEADLINE`` after which it navigates anyway.
 *
 * Setup mirrors "test home client action" in ``client_action.test.js``.
 */

import { describe, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame } from "@odoo/hoot-mock";
import {
    getService,
    mountWithCleanup,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { redirect } from "@web/core/utils/urls";
import { WebClient } from "@web/webclient/webclient";

/** Dispatch `home` exactly as client_action.test.js does. */
function doHome() {
    // Deliberately NOT awaited: it only settles once the server answers or
    // the deadline expires, and the tests drive the clock in between.
    getService("action").doAction({ type: "ir.actions.client", tag: "home" });
}

describe("home action: bounded server-wait loop", () => {
    test("backs off exponentially up to a ceiling instead of a flat 250ms", async () => {
        redirect("/odoo");
        browser.location.search = "";
        patchWithCleanup(browser.location, { assign: () => {} });

        // Record the delay of every timer the polling loop schedules. This
        // measures the retry SCHEDULE directly; counting attempts via
        // advanceTime() cannot, because advanceTime does not cascade into
        // timers created while it is flushing (one retry per call).
        const delays = [];
        const realSetTimeout = browser.setTimeout;
        patchWithCleanup(browser, {
            setTimeout(fn, delay) {
                if ([1000, 2000, 4000, 8000].includes(delay)) {
                    delays.push(delay);
                }
                return realSetTimeout.call(this, fn, delay);
            },
        });

        let attempts = 0;
        onRpc("/web/webclient/version_info", () => {
            attempts++;
            throw new Error("server is restarting");
        });

        await mountWithCleanup(WebClient);
        doHome();
        await animationFrame();

        // Drive several retry rounds; each advanceTime yields one more probe.
        for (let i = 0; i < 6; i++) {
            await advanceTime(8000);
            await animationFrame();
        }

        expect(attempts).toBe(6);
        // Was [1000, 250, 250, ...]: flat, unbounded. Now the delay doubles
        // until it saturates at HOME_POLL_MAX_DELAY.
        expect(delays.slice(0, 5)).toEqual([1000, 2000, 4000, 8000, 8000]);
        // Never exceeds the ceiling, and never regresses to the old flat value.
        expect(delays.every((d) => d <= 8000)).toBe(true);
    });

    test("gives up at the deadline and navigates anyway", async () => {
        redirect("/odoo");
        browser.location.search = "";
        const assigned = [];
        patchWithCleanup(browser.location, { assign: (url) => assigned.push(url) });

        onRpc("/web/webclient/version_info", () => {
            throw new Error("server never came back");
        });

        await mountWithCleanup(WebClient);
        doHome();
        await animationFrame();

        // Past HOME_POLL_DEADLINE (2 min). Previously the promise never
        // settled and the loop probed forever.
        for (let i = 0; i < 40; i++) {
            await advanceTime(8000);
            await animationFrame();
        }
        expect(assigned).toEqual(["/"]);
    });

    test("stops as soon as the server answers", async () => {
        redirect("/odoo");
        browser.location.search = "";
        const assigned = [];
        patchWithCleanup(browser.location, { assign: (url) => assigned.push(url) });

        let attempts = 0;
        onRpc("/web/webclient/version_info", () => {
            attempts++;
            if (attempts < 3) {
                throw new Error("server is restarting");
            }
            return true;
        });

        await mountWithCleanup(WebClient);
        doHome();
        await animationFrame();

        await advanceTime(8000);
        await advanceTime(8000);
        await advanceTime(8000);
        await animationFrame();
        expect(attempts).toBe(3);
        expect(assigned).toEqual(["/"]);

        // Confirms the loop terminates on success, so the deadline case is
        // really about the server never answering, not a runaway timer.
        await advanceTime(10_000);
        expect(attempts).toBe(3);
    });
});
