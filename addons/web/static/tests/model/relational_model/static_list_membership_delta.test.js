// @ts-check

/**
 * Tests for ``StaticList.stagedMembershipDelta`` — the published answer to
 * "which records has this list been told to link, and which to unlink".
 *
 * It exists because ``dynamic_list.js`` built the many2many half of a save's
 * change report by reading ``_commands`` and re-deriving the answer, which put
 * the command encoding (tuple shape, opcode numbering, id at index 1) in a
 * caller with no other reason to know it. That reach was the last undeclared
 * cross-module private access in the addon.
 *
 * Uses ``Object.create(StaticList.prototype)`` so the real getter runs against a
 * hand-built state, mirroring static_list_pending_commands.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { x2ManyCommands } from "@web/model/relational_model/commands";
import { StaticList } from "@web/model/relational_model/static_list";

/**
 * @param {Object} opts
 * @param {any[]} opts.commands
 * @param {Record<string, any>} [opts.cache]
 * @returns {any}
 */
function makeList({ commands, cache = {} }) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, { _commands: commands, _cache: markRaw(cache) });
    return list;
}

const rec = (/** @type {string} */ name) => ({ name });

describe("StaticList.stagedMembershipDelta", () => {
    test("splits staged commands into linked and unlinked records", () => {
        const a = rec("a");
        const b = rec("b");
        const list = makeList({
            commands: [
                [x2ManyCommands.LINK, 1, false],
                [x2ManyCommands.UNLINK, 2, false],
            ],
            cache: { 1: a, 2: b },
        });

        expect(list.stagedMembershipDelta).toEqual({ add: [a], remove: [b] });
    });

    test("ignores command types that are not LINK or UNLINK", () => {
        const a = rec("a");
        const list = makeList({
            commands: [
                [x2ManyCommands.CREATE, "virtual_1", false],
                [x2ManyCommands.DELETE, 9, false],
                [x2ManyCommands.UPDATE, 1, false],
                [x2ManyCommands.LINK, 1, false],
            ],
            cache: { 1: a, 9: rec("gone"), virtual_1: rec("new") },
        });

        // Only the LINK contributes: CREATE/DELETE/UPDATE are a different
        // question, and the caller asked about membership.
        expect(list.stagedMembershipDelta).toEqual({ add: [a], remove: [] });
    });

    test("drops ids the list has never materialised instead of yielding holes", () => {
        // The behaviour the extraction fixed. `getCachedRecord` returns
        // undefined for an id with no datapoint, and the previous inline
        // `.map()` put that undefined straight into the reported delta — so a
        // consumer iterating `add` got an element with no record in it. A LINK
        // for a record this list never built has nothing to report.
        const a = rec("a");
        const list = makeList({
            commands: [
                [x2ManyCommands.LINK, 1, false],
                [x2ManyCommands.LINK, 404, false],
                [x2ManyCommands.UNLINK, 405, false],
            ],
            cache: { 1: a },
        });

        const delta = list.stagedMembershipDelta;
        expect(delta.add).toEqual([a]);
        expect(delta.remove).toEqual([]);
        expect(delta.add.every(Boolean)).toBe(true);
    });

    test("is empty when nothing is staged", () => {
        expect(makeList({ commands: [] }).stagedMembershipDelta).toEqual({
            add: [],
            remove: [],
        });
    });

    test("preserves the order commands were staged in", () => {
        const first = rec("first");
        const second = rec("second");
        const list = makeList({
            commands: [
                [x2ManyCommands.LINK, 2, false],
                [x2ManyCommands.LINK, 1, false],
            ],
            cache: { 1: second, 2: first },
        });

        expect(list.stagedMembershipDelta.add).toEqual([first, second]);
    });
});
