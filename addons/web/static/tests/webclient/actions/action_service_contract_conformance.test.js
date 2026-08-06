// @ts-check

/**
 * `action_service_contract.js` names what an executor may ask of the
 * `ActionManager`. Nothing checks that hand-written list against the class, so a
 * rename in `ActionManager` would leave the contract naming a member that no
 * longer exists — and every executor annotated with it would be typechecked
 * against a fiction.
 *
 * The `_` half is operations and lives on the prototype. The public half is
 * per-instance state (`env`, `router`, `controllerStack`, `dialog`), which the
 * prototype does not carry, so it is checked against a constructed manager.
 *
 * A previous revision also pinned that `_loadStateGeneration` stayed OUT of
 * the contract, keeping "should that counter be load_state's own?" open as
 * counted debt. The question was answered by deleting the counter: loadState
 * now mints on the manager's `navigation` clock (declared in the surface)
 * like every other navigation entry point, so there is nothing left to omit.
 */

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
            (key) => typeof ActionManager.prototype[key] !== "function",
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
        // Its job moved onto the shared `navigation` clock; a manager that
        // grows the counter again has re-forked the supersession authority.
        const env = await makeMockEnv();
        const manager = new ActionManager(/** @type {any} */ (env));
        expect("_loadStateGeneration" in manager).toBe(false);
        expect(ACTION_MANAGER_SURFACE).not.toInclude("_loadStateGeneration");
    });
});
