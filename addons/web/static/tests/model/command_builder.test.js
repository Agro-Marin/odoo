// @ts-check

/**
 * Unit tests for command_builder.js: x2many command serialization and
 * deduplication, without OWL, DOM, or mock server.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    absorbUnlinkIntoSet,
    isUpdateRedundant,
    serializeCommands,
    shouldEmitDelete,
    shouldEmitUnlink,
} from "@web/model/relational_model/command_builder";

// Command constants (mirroring x2ManyCommands)
const CREATE = 0;
const UPDATE = 1;
const DELETE = 2;
const UNLINK = 3;
const LINK = 4;
const SET = 6;

describe("serializeCommands", () => {
    const fields = { name: { type: "char" } };
    const activeFields = { name: { readonly: false } };

    function makeParams(overrides = {}) {
        return {
            unknownRecordCommands: {},
            fields,
            activeFields,
            context: {},
            withReadonly: false,
            getRecord: () => undefined,
            getRecordChanges: () => ({}),
            convertUnityValues: (v) => v,
            ...overrides,
        };
    }

    test("passes through DELETE commands unchanged", () => {
        const commands = [[DELETE, 1]];
        const result = serializeCommands(commands, makeParams());
        expect(result).toEqual([[DELETE, 1]]);
    });

    test("passes through UNLINK commands unchanged", () => {
        const commands = [[UNLINK, 5]];
        const result = serializeCommands(commands, makeParams());
        expect(result).toEqual([[UNLINK, 5]]);
    });

    test("passes through LINK commands unchanged", () => {
        const commands = [[LINK, 3]];
        const result = serializeCommands(commands, makeParams());
        expect(result).toEqual([[LINK, 3]]);
    });

    test("passes through SET commands unchanged", () => {
        const commands = [[SET, false, [1, 2, 3]]];
        const result = serializeCommands(commands, makeParams());
        expect(result).toEqual([[SET, false, [1, 2, 3]]]);
    });

    test("serializes CREATE command with record changes", () => {
        const commands = [[CREATE, "virtual_1"]];
        const params = makeParams({
            getRecord: (id) => ({ resId: false }),
            getRecordChanges: () => ({ name: "New Record" }),
        });
        const result = serializeCommands(commands, params);
        expect(result).toEqual([[CREATE, "virtual_1", { name: "New Record" }]]);
    });

    test("converts CREATE to LINK when record has resId", () => {
        const commands = [[CREATE, "virtual_1"]];
        const params = makeParams({
            getRecord: () => ({ resId: 42 }),
            getRecordChanges: () => ({}),
        });
        const result = serializeCommands(commands, params);
        expect(result).toEqual([[LINK, 42, false]]);
    });

    test("serializes UPDATE command with record changes", () => {
        const commands = [[UPDATE, 1]];
        const params = makeParams({
            getRecord: () => ({ resId: 1 }),
            getRecordChanges: () => ({ name: "Updated" }),
        });
        const result = serializeCommands(commands, params);
        expect(result).toEqual([[UPDATE, 1, { name: "Updated" }]]);
    });

    test("skips UPDATE with empty changes", () => {
        const commands = [[UPDATE, 1]];
        const params = makeParams({
            getRecord: () => ({ resId: 1 }),
            getRecordChanges: () => ({}),
        });
        const result = serializeCommands(commands, params);
        expect(result).toEqual([]);
    });

    test("always includes CREATE even with empty changes", () => {
        const commands = [[CREATE, "virtual_1"]];
        const params = makeParams({
            getRecord: () => ({ resId: false }),
            getRecordChanges: () => ({}),
        });
        const result = serializeCommands(commands, params);
        expect(result).toEqual([[CREATE, "virtual_1", {}]]);
    });

    test("handles unknown record commands via convertUnityValues", () => {
        const commands = [[UPDATE, 99]];
        const params = makeParams({
            unknownRecordCommands: {
                99: [[UPDATE, 99, { name: "unity_value" }]],
            },
            convertUnityValues: (values) => ({
                name: `converted_${values.name}`,
            }),
        });
        const result = serializeCommands(commands, params);
        expect(result).toEqual([[UPDATE, 99, { name: "converted_unity_value" }]]);
    });

    test("merges multiple unknown record commands for same id (last wins)", () => {
        const commands = [[UPDATE, 99]];
        const params = makeParams({
            unknownRecordCommands: {
                99: [
                    [UPDATE, 99, { name: "first" }],
                    [UPDATE, 99, { name: "second" }],
                ],
            },
            convertUnityValues: (v) => v,
        });
        const result = serializeCommands(commands, params);
        // One merged UPDATE: sequential writes of the same key collapse to
        // the last value, matching what the server would compute anyway.
        expect(result).toEqual([[UPDATE, 99, { name: "second" }]]);
    });

    test("cached record's own changes are merged over deferred slices", () => {
        // Regression: a loaded record whose onchange carried a sub-x2many
        // slice its view doesn't display gets that slice stashed in
        // unknownRecordCommands. The stash used to fully SHADOW the record's
        // own changeset at serialize time, silently dropping later inline
        // user edits to that row from the save payload.
        const commands = [[UPDATE, 42]];
        const params = makeParams({
            unknownRecordCommands: {
                42: [[UPDATE, 42, { invisible_lines: [[5, 0, 0]] }]],
            },
            convertUnityValues: (v) => v,
            getRecord: (id) => (id === 42 ? { resId: 42 } : undefined),
            getRecordChanges: () => ({ name: "user edit" }),
        });
        const result = serializeCommands(commands, params);
        expect(result).toEqual([
            [UPDATE, 42, { invisible_lines: [[5, 0, 0]], name: "user edit" }],
        ]);
    });

    test("handles mixed command types", () => {
        const commands = [
            [CREATE, "v1"],
            [UPDATE, 1],
            [DELETE, 2],
            [LINK, 3],
        ];
        const params = makeParams({
            getRecord: (id) => {
                if (id === "v1") {
                    return { resId: false };
                }
                return { resId: id };
            },
            getRecordChanges: (record) => {
                if (!record.resId) {
                    return { name: "new" };
                }
                return { name: "updated" };
            },
        });
        const result = serializeCommands(commands, params);
        expect(result.length).toBe(4);
        expect(result[0][0]).toBe(CREATE);
        expect(result[1][0]).toBe(UPDATE);
        expect(result[2][0]).toBe(DELETE);
        expect(result[3][0]).toBe(LINK);
    });
});

describe("shouldEmitDelete", () => {
    test("returns true when no CREATE exists (real record)", () => {
        const ownCommands = [{ command: [UPDATE, 1], index: 0 }];
        expect(shouldEmitDelete(ownCommands)).toBe(true);
        // Should clear all commands
        expect(ownCommands.length).toBe(0);
    });

    test("returns false when CREATE exists (cancels out)", () => {
        const ownCommands = [
            { command: [CREATE, "v1"], index: 0 },
            { command: [UPDATE, "v1"], index: 1 },
        ];
        expect(shouldEmitDelete(ownCommands)).toBe(false);
        expect(ownCommands.length).toBe(0);
    });

    test("clears commands even when returning true", () => {
        const ownCommands = [
            { command: [UPDATE, 5], index: 0 },
            { command: [UPDATE, 5], index: 1 },
        ];
        shouldEmitDelete(ownCommands);
        expect(ownCommands.length).toBe(0);
    });

    test("handles empty command list", () => {
        const ownCommands = [];
        expect(shouldEmitDelete(ownCommands)).toBe(true);
    });
});

describe("shouldEmitUnlink", () => {
    test("returns true when no LINK exists", () => {
        const ownCommands = [{ command: [UPDATE, 3], index: 0 }];
        expect(shouldEmitUnlink(ownCommands)).toBe(true);
        expect(ownCommands.length).toBe(1); // UPDATE not removed
    });

    test("returns false when LINK exists (cancels out)", () => {
        const ownCommands = [
            { command: [LINK, 3], index: 0 },
            { command: [UPDATE, 3], index: 1 },
        ];
        expect(shouldEmitUnlink(ownCommands)).toBe(false);
        // Every command for the id is dropped — "net effect: nothing happened".
        // A surviving UPDATE would still serialize (the record stays in
        // `_cache` after an UNLINK) and write edits to a record the user just
        // removed from the relation.
        expect(ownCommands.length).toBe(0);
    });

    test("handles empty command list", () => {
        const ownCommands = [];
        expect(shouldEmitUnlink(ownCommands)).toBe(true);
    });

    test("only removes first LINK", () => {
        const ownCommands = [
            { command: [LINK, 3], index: 0 },
            { command: [LINK, 3], index: 1 },
        ];
        expect(shouldEmitUnlink(ownCommands)).toBe(false);
        expect(ownCommands.length).toBe(1);
    });

    test("returns false and clears when a CREATE exists (cancels out)", () => {
        // Symmetric with shouldEmitDelete: an inline-created row (CREATE, no
        // LINK) that is then UNLINKed never existed server-side, so NOTHING is
        // emitted and every staged command is dropped. Previously the CREATE
        // survived and the "removed" row got created anyway.
        const ownCommands = [{ command: [CREATE, "v1"], index: 0 }];
        expect(shouldEmitUnlink(ownCommands)).toBe(false);
        expect(ownCommands.length).toBe(0);
    });

    test("returns false and clears a CREATE with pending UPDATEs", () => {
        const ownCommands = [
            { command: [CREATE, "v1"], index: 0 },
            { command: [UPDATE, "v1"], index: 1 },
        ];
        expect(shouldEmitUnlink(ownCommands)).toBe(false);
        expect(ownCommands.length).toBe(0);
    });
});

describe("absorbUnlinkIntoSet", () => {
    test("returns false when no commands exist", () => {
        expect(absorbUnlinkIntoSet([], 1)).toBe(false);
    });

    test("returns false when first command is not SET", () => {
        const commands = [[UPDATE, 1, {}]];
        expect(absorbUnlinkIntoSet(commands, 1)).toBe(false);
    });

    test("returns false when id is not in SET list", () => {
        const commands = [[SET, false, [2, 3, 4]]];
        expect(absorbUnlinkIntoSet(commands, 1)).toBe(false);
        expect(commands[0][2]).toEqual([2, 3, 4]);
    });

    test("absorbs unlink by removing id from SET list", () => {
        const commands = [[SET, false, [1, 2, 3]]];
        expect(absorbUnlinkIntoSet(commands, 2)).toBe(true);
        expect(commands[0][2]).toEqual([1, 3]);
    });

    test("handles last id in SET list", () => {
        const commands = [[SET, false, [5]]];
        expect(absorbUnlinkIntoSet(commands, 5)).toBe(true);
        expect(commands[0][2]).toEqual([]);
    });

    test("also drops orphaned UPDATE commands for the absorbed id", () => {
        // _replaceWith keeps [SET(ids), ...UPDATE]. Unlinking an id must remove
        // it from the SET AND drop its UPDATE, else the server applies SET
        // (removing the row) then writes edits into a record no longer in the
        // relation.
        const commands = [
            [SET, false, [1, 2, 3]],
            [UPDATE, 2, { name: "edited" }],
            [UPDATE, 3, { name: "keep" }],
        ];
        expect(absorbUnlinkIntoSet(commands, 2)).toBe(true);
        expect(commands[0][2]).toEqual([1, 3]);
        // the UPDATE for 2 is gone; the UPDATE for 3 (still in the SET) survives
        expect(commands).toEqual([
            [SET, false, [1, 3]],
            [UPDATE, 3, { name: "keep" }],
        ]);
    });
});

describe("isUpdateRedundant", () => {
    test("returns false for empty commands", () => {
        expect(isUpdateRedundant([])).toBe(false);
    });

    test("returns true when CREATE exists", () => {
        const commands = [{ command: [CREATE, "v1"], index: 0 }];
        expect(isUpdateRedundant(commands)).toBe(true);
    });

    test("returns true when UPDATE exists", () => {
        const commands = [{ command: [UPDATE, 1], index: 0 }];
        expect(isUpdateRedundant(commands)).toBe(true);
    });

    test("returns false when only non-CREATE/UPDATE commands exist", () => {
        const commands = [
            { command: [LINK, 1], index: 0 },
            { command: [DELETE, 2], index: 1 },
        ];
        expect(isUpdateRedundant(commands)).toBe(false);
    });
});
