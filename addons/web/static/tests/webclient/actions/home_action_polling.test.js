// @ts-check

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

function doHome() {
    getService("action").doAction({ type: "ir.actions.client", tag: "home" });
}

describe("home action: bounded server-wait loop", () => {
    test("probes immediately when the server is already up", async () => {
        redirect("/odoo");
        browser.location.search = "";
        patchWithCleanup(browser.location, { assign: () => {} });

        let elapsed = 0;
        const realSetTimeout = browser.setTimeout;
        patchWithCleanup(browser, {
            setTimeout(fn, delay) {
                return realSetTimeout.call(
                    this,
                    () => {
                        elapsed += delay || 0;
                        return fn();
                    },
                    delay,
                );
            },
        });

        let firstProbeAt = null;
        onRpc("/web/webclient/version_info", () => {
            firstProbeAt ??= elapsed;
            return true;
        });

        await mountWithCleanup(WebClient);
        doHome();
        await animationFrame();
        await advanceTime(1500);
        await animationFrame();

        expect(firstProbeAt).toBe(0);
    });

    test("backs off exponentially up to a ceiling instead of a flat 250ms", async () => {
        redirect("/odoo");
        browser.location.search = "";
        patchWithCleanup(browser.location, { assign: () => {} });

        const delays = [];
        const realSetTimeout = browser.setTimeout;
        patchWithCleanup(browser, {
            setTimeout(fn, delay) {
                if (delay !== undefined && [1000, 2000, 4000, 8000].includes(delay)) {
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

        for (let i = 0; i < 6; i++) {
            await advanceTime(8000);
            await animationFrame();
        }

        expect(attempts).toBe(7);
        expect(delays.slice(0, 5)).toEqual([1000, 2000, 4000, 8000, 8000]);
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

        await advanceTime(10_000);
        expect(attempts).toBe(3);
    });
});
