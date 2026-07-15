// @ts-check

import { expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";
// eslint-disable-next-line simple-import-sort/imports -- order-sensitive:
// a prior `eslint --fix` hoisted this side-effect import to the top, ahead
// of `registry`; restored to its original (last) position. Not verified
// against the Hoot suite (harness unavailable in this environment) — treat
// this position as the known-safe one until it is.
import "@web/views/module_views";

function getIsDisplayed() {
    return registry.category("cogMenu").get("reset-module-state-cog-menu").isDisplayed;
}

/**
 * Build a fake CogMenu env for the `isDisplayed` predicate. The `config` object
 * is what the predicate memoizes on, so reuse the SAME env to simulate repeated
 * `onWillUpdateProps` evaluations of one action.
 */
function makeEnv({ resModel = "ir.module.module", viewType = "list", call } = {}) {
    return {
        config: { viewType, actionId: 1 },
        searchModel: { resModel },
        services: { orm: { silent: { call } } },
    };
}

test("isDisplayed swallows a rejected check_module_update", async () => {
    const isDisplayed = getIsDisplayed();
    const env = makeEnv({ call: () => Promise.reject(new Error("boom")) });
    // A rejected background RPC must not crash the Apps view: hide the item.
    expect(await isDisplayed(env)).toBe(false);
});

test("isDisplayed memoizes check_module_update per action", async () => {
    let calls = 0;
    const isDisplayed = getIsDisplayed();
    const env = makeEnv({
        call: () => {
            calls++;
            return Promise.resolve(true);
        },
    });
    expect(await isDisplayed(env)).toBe(true);
    // Simulate onWillUpdateProps re-evaluating with the same config object.
    expect(await isDisplayed(env)).toBe(true);
    expect(calls).toBe(1);
});

test("isDisplayed is false without an RPC outside ir.module.module list views", async () => {
    let calls = 0;
    const isDisplayed = getIsDisplayed();
    const call = () => {
        calls++;
        return Promise.resolve(true);
    };
    expect(await isDisplayed(makeEnv({ resModel: "res.partner", call }))).toBe(false);
    expect(await isDisplayed(makeEnv({ viewType: "form", call }))).toBe(false);
    expect(calls).toBe(0);
});
