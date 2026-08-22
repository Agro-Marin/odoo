// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { x2ManyCommands } from "@web/core/network/commands";
import { StaticList } from "@web/model/relational_model/static_list";

/**
 * @param {Object} opts
 * @param {any[]} opts.commands
 * @param {Map<number | string, any>} [opts.cache]
 * @returns {any}
 */
function makeList({ commands, cache = new Map() }) {
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
            cache: new Map([
                [1, a],
                [2, b],
            ]),
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
            cache: new Map(
                /** @type {[number | string, any][]} */ ([
                    [1, a],
                    [9, rec("gone")],
                    ["virtual_1", rec("new")],
                ]),
            ),
        });

        expect(list.stagedMembershipDelta).toEqual({ add: [a], remove: [] });
    });

    test("drops ids the list has never materialised instead of yielding holes", () => {
        const a = rec("a");
        const list = makeList({
            commands: [
                [x2ManyCommands.LINK, 1, false],
                [x2ManyCommands.LINK, 404, false],
                [x2ManyCommands.UNLINK, 405, false],
            ],
            cache: new Map([[1, a]]),
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
            cache: new Map([
                [1, second],
                [2, first],
            ]),
        });

        expect(list.stagedMembershipDelta.add).toEqual([first, second]);
    });
});
