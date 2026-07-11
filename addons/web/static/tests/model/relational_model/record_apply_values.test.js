// @ts-check

/**
 * Pins ``record._applyValues``'s handling of x2many pending edits: a list
 * held in ``_changes`` with staged commands must be MERGED with the fresh
 * server rows (same datapoint, commands preserved), never wholesale-replaced
 * by a freshly parsed StaticList whose empty ``_commands`` would silently
 * drop the pending sub-edits from the next save. Reachable via
 * ``extendRecord``'s first-extension load, ``_updateSimilarRecords``
 * (m2m-grouped kanban), and ``_createRecordDatapoint``'s cached-dirty branch.
 *
 * Uses the REAL RelationalRecord and StaticList classes against a mock model.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

const LINK = 4;

function makeRecord({ lines = [] } = {}) {
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (config, patch) => Object.assign(config, patch),
        _loadRecords: async () => [],
    };
    const config = {
        resModel: "parent.model",
        resId: 1,
        resIds: [1],
        mode: "readonly",
        isMonoRecord: true,
        context: {},
        activeFields: {
            lines: {
                ...makeActiveField(),
                related: {
                    activeFields: { name: makeActiveField() },
                    fields: { name: { type: "char", name: "name" } },
                },
            },
        },
        fields: {
            lines: {
                type: "one2many",
                name: "lines",
                relation: "line.model",
                relation_field: false,
            },
        },
    };
    return new RelationalRecord(model, config, { id: 1, lines }, {});
}

describe("_applyValues x2many merge", () => {
    test("pending commands survive _applyValues (list merged, not replaced)", async () => {
        const record = makeRecord({ lines: [{ id: 10, name: "L1" }] });
        const list = record.data.lines;

        // Stage a user edit on the list (LINK with data: fully synchronous),
        // and register it in the pending-change layer as
        // preprocessX2manyChanges/_applyChanges do.
        await list._applyCommands([[LINK, 11, { id: 11, name: "Linked" }]]);
        record._applyChanges({ lines: list });
        expect(list._commands).toEqual([[LINK, 11, false]]);

        // Fresh server rows for the same field (e.g. extendRecord loading the
        // dialog's fuller field set).
        record._applyValues({ id: 1, lines: [{ id: 10, name: "L1-updated" }] });

        // Same datapoint everywhere — commands preserved.
        expect(record._changes.lines).toBe(list);
        expect(record._values.lines).toBe(list);
        expect(record.data.lines).toBe(list);
        expect(list._commands).toEqual([[LINK, 11, false]]);
        // The fresh row values were folded into the list's cache.
        expect(list._cache[10].data.name).toBe("L1-updated");
        expect(list.records.find((r) => r.resId === 10).data.name).toBe("L1-updated");
        // The linked row is still there.
        expect(list._currentIds).toEqual([10, 11]);
    });

    test("without pending commands the list is still replaced by fresh values", () => {
        const record = makeRecord({ lines: [{ id: 10, name: "L1" }] });
        const list = record.data.lines;
        // The pending layer holds the list, but with no staged commands.
        record._applyChanges({ lines: list });
        expect(list._commands).toEqual([]);

        record._applyValues({ id: 1, lines: [{ id: 10, name: "L1-updated" }] });

        // Wholesale replacement (historical behavior) is fine here: there is
        // nothing to lose, and the fresh list carries the new values.
        expect(record.data.lines).not.toBe(list);
        expect(record.data.lines._cache[10].data.name).toBe("L1-updated");
        expect(record._changes.lines).toBe(record.data.lines);
    });
});
