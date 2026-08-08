// @ts-check

/**
 * `static_list_contract.js` names the `StaticList` operations an owner invokes.
 * Nothing checks a hand-written list against the class it describes, so a rename
 * in `StaticList` would leave the contract naming a member that no longer
 * exists — and every module annotated with the contract would then be
 * typechecked against a fiction.
 *
 * The record contract has the same guard in
 * `record_doubles_conformance.test.js`, against a real instance. `StaticList`
 * has no double and is expensive to construct, so this checks the prototype
 * instead. That is sound for this contract precisely because every member of it
 * is a method: the working-memory members (`_cache`, `_currentIds`, …) are
 * instance fields and are deliberately NOT part of the surface — they are
 * listed apart, as `INTERNAL_STATE_REACHED`.
 */

import { describe, expect, test } from "@odoo/hoot";
import { StaticList } from "@web/model/relational_model/static_list";
import {
    INTERNAL_STATE_REACHED,
    STATIC_LIST_OWNER_SURFACE,
} from "@web/model/relational_model/static_list_contract";

describe.current.tags("headless");

describe("the StaticList owner contract and the class agree", () => {
    test("StaticList carries every operation the contract names", () => {
        const missing = STATIC_LIST_OWNER_SURFACE.filter(
            (key) => !(key in StaticList.prototype),
        );
        expect(missing).toEqual([], {
            message:
                "STATIC_LIST_OWNER_SURFACE names something StaticList no longer " +
                "has -- update the contract, and every module annotated with it",
        });
    });

    test("every `_` member of the contract is an operation, not state", () => {
        // The point of the private half: an owner is meant to CALL these, not
        // read them. If one stopped being a method the `in` check above would go
        // quietly vacuous for it.
        //
        // Scoped to the `_` half on purpose. The public half is deliberately
        // getters (`cachedRecords`, `pendingCommands`, `hasStagedCommands`), and
        // `typeof /** @type {any} */ (StaticList.prototype)[key]` would INVOKE them against the
        // prototype rather than an instance — reading state off an object that
        // has none, which throws rather than answering.
        const notMethods = STATIC_LIST_OWNER_SURFACE.filter(
            (key) =>
                key.startsWith("_") &&
                typeof (/** @type {any} */ (StaticList.prototype)[key]) !== "function",
        );
        expect(notMethods).toEqual([], {
            message: "the private half of the owner surface must be operations",
        });
    });

    test("the internal-state list is disjoint from the contract", () => {
        const both = STATIC_LIST_OWNER_SURFACE.filter((key) =>
            INTERNAL_STATE_REACHED.includes(key),
        );
        expect(both).toEqual([], {
            message:
                "a member cannot be both the published interface and the " +
                "working memory nobody outside should touch",
        });
    });
});
