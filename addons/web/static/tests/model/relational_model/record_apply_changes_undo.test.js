// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { StaticList } from "@web/model/relational_model/static_list";

describe.current.tags("headless");

const LINK = 4;

const SERVER_ROWS = {
    1: { id: 1, display_name: "Rec 1" },
    2: { id: 2, display_name: "Rec 2" },
    99: { id: 99, display_name: "Rec 99" },
};

function makeX2ManyList(resIds) {
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (config, patch) => Object.assign(config, patch),
        _loadRecords: async ({ resIds: ids }) => ids.map((id) => SERVER_ROWS[id]),
    };
    const config = {
        resModel: "res.partner",
        activeFields: { display_name: makeActiveField() },
        fields: { display_name: { type: "char", name: "display_name" } },
        relationField: false,
        offset: 0,
        limit: 40,
        resIds,
        orderBy: [],
        context: {},
    };
    const parent = {
        evalContext: {},
        evalContextWithVirtualIds: {},
        _isEvalContextReady: true,
    };
    const data = resIds.map((id) => SERVER_ROWS[id]);
    return new StaticList(/** @type {any} */ (model), config, data, {
        parent,
        onUpdate: async () => {},
    });
}

function makeRecordWith(list) {
    const record = Object.create(RelationalRecord.prototype);
    Object.assign(record, {
        _config: {
            resModel: "some.model",
            context: {},
            activeFields: { line_ids: makeActiveField() },
            fields: {
                line_ids: {
                    type: "one2many",
                    name: "line_ids",
                    relation: "res.partner",
                },
            },
        },
        data: { line_ids: list },
        _editState: new RecordEditState(),
        _setEvalContext() {},
        _checkValidity() {},
        _removeInvalidFields() {},
        _getTextValues() {
            return {};
        },
    });
    return record;
}

describe("RelationalRecord._applyChanges undo — x2many sub-list", () => {
    test("undoChanges reverts an in-place onchange LINK on the x2many list", async () => {
        const list = makeX2ManyList([1, 2]);
        expect(list._commands).toEqual([]);
        expect(list._currentIds).toEqual([1, 2]);
        expect(list.count).toBe(2);

        const record = makeRecordWith(list);

        const undoChanges = record._applyChanges(
            {},
            { line_ids: [[LINK, 99, SERVER_ROWS[99]]] },
            { undoable: true },
        );

        expect(list._currentIds).toEqual([1, 2, 99]);
        expect(list._commands.length).toBe(1);
        expect(list.count).toBe(3);

        undoChanges();

        expect(list._commands).toEqual([]);
        expect(list._currentIds).toEqual([1, 2]);
        expect(list.count).toBe(2);

        if (list._commandsPromise) {
            await list._commandsPromise;
        }
    });

    test("after undo the x2many save payload carries no phantom command", async () => {
        const list = makeX2ManyList([1, 2]);
        expect(list._getCommands()).toEqual([]);

        const record = makeRecordWith(list);

        const undoChanges = record._applyChanges(
            {},
            { line_ids: [[LINK, 99, SERVER_ROWS[99]]] },
            { undoable: true },
        );
        expect(list._getCommands().length).toBe(1);

        undoChanges();

        expect(list._getCommands()).toEqual([]);

        if (list._commandsPromise) {
            await list._commandsPromise;
        }
    });
});
