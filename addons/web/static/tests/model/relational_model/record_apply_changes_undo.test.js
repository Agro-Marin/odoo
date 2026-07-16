// @ts-check

/**
 * Regression test for ``RelationalRecord._applyChanges``'s undo closure.
 *
 * ``_applyChanges(changes, serverChanges)`` applies a server onchange result
 * and returns ``undoChanges`` — invoked on the error paths (onchange RPC
 * failure at ``_getOnchangeValues.onError``; a throwing ``_onUpdate``). For an
 * x2many field the onchange value is a command list that ``parseServerValues``
 * replays into the EXISTING ``StaticList`` IN PLACE (``_applyCommands``). The
 * undo shallow-snapshots ``this.data`` and restores the SAME list reference, so
 * without an explicit list revert the staged commands survive the undo and
 * ship on the next ``web_save``.
 *
 * Uses the REAL ``RelationalRecord`` and ``StaticList`` classes (peripheral
 * validity/eval-context machinery stubbed) so the undo contract is exercised
 * directly, mirroring static_list_link_full_page.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { StaticList } from "@web/model/relational_model/static_list";

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
    return new StaticList(model, config, data, { parent, onUpdate: async () => {} });
}

function makeRecordWith(list) {
    const record = Object.create(RelationalRecord.prototype);
    Object.assign(record, {
        // fields/activeFields/resModel/context are DataPoint getters deriving
        // from _config (see datapoint.js).
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
        // dirty/_changes/_textValues/_invalidFields proxy to _editState.
        _editState: new RecordEditState(),
        // Peripheral machinery unrelated to list command state — stubbed so
        // the test isolates the undo contract (not eval-context / validity).
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

        // Server onchange returns a LINK for the x2many: parseServerValues
        // replays it into the existing StaticList in place.
        const undoChanges = record._applyChanges(
            {},
            { line_ids: [[LINK, 99, SERVER_ROWS[99]]] },
        );

        // The command is staged in place (mutation is synchronous).
        expect(list._currentIds).toEqual([1, 2, 99]);
        expect(list._commands.length).toBe(1);
        expect(list.count).toBe(3);

        // The onchange consumer then failed (e.g. _onUpdate threw), so the
        // update is rolled back. undoChanges() must revert the list too, not
        // just record.data — otherwise a phantom LINK ships on the next save.
        undoChanges();

        expect(list._commands).toEqual([]);
        expect(list._currentIds).toEqual([1, 2]);
        expect(list.count).toBe(2);

        // Drain any tracked command promise so nothing floats past the test.
        if (list._commandsPromise) {
            await list._commandsPromise;
        }
    });

    test("after undo the x2many save payload carries no phantom command", async () => {
        // The concrete harm of the leak is a phantom command shipping on the
        // next web_save. ``_getCommands`` builds that payload from
        // ``_commands``, so the real guarantee is: undo empties it.
        const list = makeX2ManyList([1, 2]);
        expect(list._getCommands()).toEqual([]);

        const record = makeRecordWith(list);

        const undoChanges = record._applyChanges(
            {},
            { line_ids: [[LINK, 99, SERVER_ROWS[99]]] },
        );
        // The onchange staged a real command into the save payload.
        expect(list._getCommands().length).toBe(1);

        undoChanges();

        // ...which the undo must fully remove.
        expect(list._getCommands()).toEqual([]);

        if (list._commandsPromise) {
            await list._commandsPromise;
        }
    });
});
