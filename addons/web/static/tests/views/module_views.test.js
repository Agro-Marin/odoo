// @ts-check

import "@web/views/module_views";

import { expect, test } from "@odoo/hoot";
import { makeMockEnv, mockService } from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";

function getIsDisplayed() {
    return registry.category("cogMenu").get("reset-module-state-cog-menu").isDisplayed;
}

/** @param {{ resModel?: string, viewType?: string, call?: () => Promise<boolean> }} [options] */
async function makeEnv({
    resModel = "ir.module.module",
    viewType = "list",
    call = async () => false,
} = {}) {
    mockService("orm", { call });
    const env = await makeMockEnv();
    env.config = { viewType, actionId: 1 };
    env.searchModel = { resModel };
    return env;
}

test("isDisplayed swallows a rejected has_pending_module_update", async () => {
    const isDisplayed = getIsDisplayed();
    const env = await makeEnv({ call: () => Promise.reject(new Error("boom")) });
    expect(await isDisplayed(env)).toBe(false);
});

test("isDisplayed memoizes has_pending_module_update per action", async () => {
    let calls = 0;
    const isDisplayed = getIsDisplayed();
    const env = await makeEnv({
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
    expect(await isDisplayed(await makeEnv({ resModel: "res.partner", call }))).toBe(
        false,
    );
    expect(await isDisplayed(await makeEnv({ viewType: "form", call }))).toBe(false);
    expect(calls).toBe(0);
});
