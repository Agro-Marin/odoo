// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";

describe.current.tags("headless");

function makeSetDataProbeRecord({ dirty, changes = {} } = {}) {
    const editState = new RecordEditState();
    editState.changes = changes;
    editState.dirty = dirty;
    return {
        _editState: editState,
        get dirty() {
            return editState.dirty;
        },
        set dirty(value) {
            editState.dirty = value;
        },
        get changes() {
            return editState.changes;
        },
        get _hasChanges() {
            return !editState.isChangeSetEmpty;
        },
        _clearChanges: () => editState.clearChanges(),
        clearValidity: () => editState.clearValidity(),
        resModel: "test.model",
        resId: 42,
        _textValues: {},
        isNew: false,
        isInEdition: false,
        _parentRecord: null,
        parseServerValues: (data) => data,
        _getTextValues: () => ({}),
        setEvalContext() {},
        setData: RelationalRecord.prototype.setData,
    };
}

describe("setData(keepChanges) dirty derivation", () => {
    test("Invariant-1 window: dirty=true with an empty changeSet survives a reload", () => {
        const rec = makeSetDataProbeRecord({ dirty: true, changes: {} });
        rec.setData({ id: 1 }, { keepChanges: true });
        expect(rec.dirty).toBe(true);
    });

    test("clean record with pending changes becomes dirty", () => {
        const rec = makeSetDataProbeRecord({ dirty: false, changes: { name: "x" } });
        rec.setData({ id: 1 }, { keepChanges: true });
        expect(rec.dirty).toBe(true);
    });

    test("clean record with no pending changes stays clean", () => {
        const rec = makeSetDataProbeRecord({ dirty: false, changes: {} });
        rec.setData({ id: 1 }, { keepChanges: true });
        expect(rec.dirty).toBe(false);
    });
});
