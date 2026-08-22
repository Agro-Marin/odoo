// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

describe.current.tags("headless");

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

        await list._applyCommands([[LINK, 11, { id: 11, name: "Linked" }]]);
        record._applyChanges({ lines: list });
        expect(list._commands).toEqual([[LINK, 11, false]]);

        record._applyValues({ id: 1, lines: [{ id: 10, name: "L1-updated" }] });

        expect(record._changes.lines).toBe(list);
        expect(record._values.lines).toBe(list);
        expect(record.data.lines).toBe(list);
        expect(list._commands).toEqual([[LINK, 11, false]]);
        expect(list._cache.get(10).data.name).toBe("L1-updated");
        expect(list.records.find((r) => r.resId === 10).data.name).toBe("L1-updated");
        expect(list._currentIds).toEqual([10, 11]);
    });

    test("without pending commands the list is still replaced by fresh values", () => {
        const record = makeRecord({ lines: [{ id: 10, name: "L1" }] });
        const list = record.data.lines;
        record._applyChanges({ lines: list });
        expect(list._commands).toEqual([]);

        record._applyValues({ id: 1, lines: [{ id: 10, name: "L1-updated" }] });

        expect(record.data.lines).not.toBe(list);
        expect(record.data.lines._cache.get(10).data.name).toBe("L1-updated");
        expect(record._changes.lines).toBe(record.data.lines);
    });
});
