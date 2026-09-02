// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { ActionManager } from "@web/webclient/actions";
import { ACTION_MANAGER_SURFACE } from "@web/webclient/actions/action_service_contract";

describe.current.tags("headless");

const isPrototypeMethod = (/** @type {string} */ key) =>
    typeof Object.getOwnPropertyDescriptor(ActionManager.prototype, key)?.value ===
    "function";
const OPERATIONS = ACTION_MANAGER_SURFACE.filter(isPrototypeMethod);
const STATE = ACTION_MANAGER_SURFACE.filter((key) => !isPrototypeMethod(key));

describe("the ActionManager contract and the class agree", () => {
    test("every operation an executor calls is a method on the class", () => {
        const called = [
            "makeController",
            "updateUI",
            "confirmLeave",
            "getActionInfo",
            "removeDialog",
            "fetchAction",
            "executeCloseAction",
            "getBreadcrumbs",
            "nextId",
            "getViewInfo",
            "getView",
            "controllersFromState",
            "getActionParams",
        ];
        expect(called.filter((key) => !OPERATIONS.includes(key))).toEqual([], {
            message:
                "ACTION_MANAGER_SURFACE names an operation ActionManager no " +
                "longer has -- update the contract, and every executor using it",
        });
    });

    test("every state member the contract names exists on a real manager", async () => {
        const env = await makeMockEnv();
        const manager = new ActionManager(/** @type {any} */ (env));
        const missing = STATE.filter((key) => !(key in manager));
        expect(missing).toEqual([], {
            message:
                "the state half is per-instance, so it is checked " +
                "against a constructed manager rather than the prototype",
        });
    });

    test("control: the halves are populated, and nothing is spelled private", () => {
        expect(OPERATIONS.length).toBeGreaterThan(20);
        expect(STATE.length).toBeGreaterThan(8);
        expect(ACTION_MANAGER_SURFACE.filter((key) => key.startsWith("_"))).toEqual(
            [],
            {
                message:
                    "a member executors reach is public; the underscore was the lie",
            },
        );
    });

    test("the retired `_loadStateGeneration` counter must not come back", async () => {
        const env = await makeMockEnv();
        const manager = new ActionManager(/** @type {any} */ (env));
        expect("_loadStateGeneration" in manager).toBe(false);
        expect(ACTION_MANAGER_SURFACE).not.toInclude("_loadStateGeneration");
    });
});
