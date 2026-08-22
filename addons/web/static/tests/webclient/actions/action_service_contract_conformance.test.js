// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { ActionManager } from "@web/webclient/actions";
import { ACTION_MANAGER_SURFACE } from "@web/webclient/actions/action_service_contract";

describe.current.tags("headless");

const PRIVATE = ACTION_MANAGER_SURFACE.filter((k) => k.startsWith("_"));
const PUBLIC = ACTION_MANAGER_SURFACE.filter((k) => !k.startsWith("_"));

describe("the ActionManager contract and the class agree", () => {
    test("every operation the contract names is a method on the class", () => {
        const missing = PRIVATE.filter(
            (key) =>
                typeof (/** @type {any} */ (ActionManager.prototype)[key]) !==
                "function",
        );
        expect(missing).toEqual([], {
            message:
                "ACTION_MANAGER_SURFACE names an operation ActionManager no " +
                "longer has -- update the contract, and every executor using it",
        });
    });

    test("every public member the contract names exists on a real manager", async () => {
        const env = await makeMockEnv();
        const manager = new ActionManager(/** @type {any} */ (env));
        const missing = PUBLIC.filter((key) => !(key in manager));
        expect(missing).toEqual([], {
            message:
                "the public half is per-instance state, so it is checked " +
                "against a constructed manager rather than the prototype",
        });
    });

    test("control: the halves are populated", () => {
        expect(PRIVATE.length).toBeGreaterThan(10);
        expect(PUBLIC.length).toBeGreaterThan(8);
    });

    test("the retired `_loadStateGeneration` counter must not come back", async () => {
        const env = await makeMockEnv();
        const manager = new ActionManager(/** @type {any} */ (env));
        expect("_loadStateGeneration" in manager).toBe(false);
        expect(ACTION_MANAGER_SURFACE).not.toInclude("_loadStateGeneration");
    });
});
