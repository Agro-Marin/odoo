// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { checkValidity } from "@web/model/relational_model/record_validator";

function makeChild(/** @type {any} */ { resId, dirty, changes }) {
    const editState = new RecordEditState();
    editState.changes = { ...changes };
    editState.dirty = dirty;
    return {
        resId,
        _virtualId: false,
        _editState: editState,
        get dirty() {
            return editState.dirty;
        },
        get hasPendingChanges() {
            return editState.hasPendingChanges;
        },
        get _changes() {
            return editState.changes;
        },
        get isValid() {
            return false;
        },
        _checkValidity: () => false,
    };
}

/** @returns {any} */
function makeParent(/** @type {any} */ child) {
    const list = {
        count: 1,
        _currentIds: [child.resId],
        _cache: new Map([[child.resId, child]]),
        get currentIds() {
            return this._currentIds;
        },
        get cachedRecords() {
            return [...this._cache.values()];
        },
    };
    const editState = new RecordEditState();
    return {
        fields: { line_ids: { type: "one2many", name: "line_ids" } },
        activeFields: { line_ids: {} },
        data: { line_ids: list },
        _editState: editState,
        get _invalidFields() {
            return editState.invalidFields;
        },
        get _unsetRequiredFields() {
            return editState.unsetRequiredFields;
        },
        setInvalidFieldsNotification(/** @type {any} */ _close) {},
        _isInvisible: () => false,
        _isRequired: () => false,
    };
}

describe("x2many child validity vs. the dirty flag", () => {
    test("a dirty invalid child invalidates the parent", () => {
        const child = makeChild({ resId: 1, dirty: true, changes: { name: false } });

        expect(checkValidity(makeParent(child))).toBe(false);
    });

    test("an invalid child with pending changes invalidates the parent too", () => {
        const child = makeChild({ resId: 1, dirty: false, changes: { name: false } });

        expect(checkValidity(makeParent(child))).toBe(false);
    });

    test("an invalid child with nothing pending is still skipped", () => {
        const child = makeChild({ resId: 1, dirty: false, changes: {} });

        expect(checkValidity(makeParent(child))).toBe(true);
    });
});
