// @ts-check

/**
 * ``checkValidity`` skips an x2many child whose ``dirty`` flag is false. But
 * ``dirty`` is only raised by ``_update()``: a child mutated through
 * ``_applyChanges`` — which is how a server onchange's ``UPDATE`` command and
 * ``_applyDefaultValues`` reach a line — carries pending entries in
 * ``_changes`` with ``dirty === false``. Those entries are sent on save, so a
 * child made invalid that way must be validated like any other.
 */

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

/** @returns {any} a partial RelationalRecord, enough for checkValidity */
function makeParent(/** @type {any} */ child) {
    const list = {
        count: 1,
        _currentIds: [child.resId],
        _cache: { [child.resId]: child },
        // Both are published getters over working memory, for the same reason
        // they are on the real class: `_currentIds` / `_cache` are not in
        // `STATIC_LIST_CONTRACT_SURFACE`, and the validator must read the list
        // through what it publishes.
        get currentIds() {
            return this._currentIds;
        },
        get cachedRecords() {
            return Object.values(this._cache);
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
