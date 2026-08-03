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
 * The last test is the one with teeth. `_loadStateGeneration` is left OUT of the
 * contract on purpose, so that `load_state.js` reading it keeps counting as
 * debt; without a test, "deliberately omitted" and "forgotten" look identical
 * the day someone adds it to quiet the gate.
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

    test("`_loadStateGeneration` is omitted on purpose, and stays omitted", () => {
        // It is a navigation counter `load_state.js` reads to detect a
        // superseded load -- state, not an operation. Leaving it out keeps the
        // question "should that generation be load_state's own?" open and
        // counted. Declaring it would retire the question rather than answer it.
        expect(ACTION_MANAGER_SURFACE).not.toInclude("_loadStateGeneration", {
            message:
                "if this is now genuinely part of the interface, delete this " +
                "test in the same commit -- do not let it drift in silently",
        });
    });
});
