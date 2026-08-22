// @ts-check

import "@web/views/module_views";

import { expect, test } from "@odoo/hoot";
import { registry } from "@web/core/registry";

function getIsDisplayed() {
    return registry.category("cogMenu").get("reset-module-state-cog-menu").isDisplayed;
}

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
