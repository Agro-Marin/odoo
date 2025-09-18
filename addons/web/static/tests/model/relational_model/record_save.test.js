// @ts-check

/**
 * Pure unit tests for record_save.js.
 *
 * Tests the save() function — record persistence, creation vs update path,
 * validity guard, no-changes short-circuit, onError callback, and the
 * FetchRecordError thrown when webSave returns an empty array with reload:true.
 *
 * Uses plain mock objects (delegation pattern). OWL's markRaw() is imported
 * directly — it works in the Hoot browser environment without mounting a
 * component. The FetchRecordError test requires makeMockEnv() because
 * FetchRecordError calls _t() in its constructor.
 *
 * Module under test: model/relational_model/record_save.js
 */

import { markRaw } from "@odoo/owl";
import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { FetchRecordError } from "@web/model/relational_model/errors";
import { save } from "@web/model/relational_model/record_save";

// ---------------------------------------------------------------------------
// Mock factory
// ---------------------------------------------------------------------------

/**
 * Builds the minimal record mock shape required by save().
 *
 * Defaults:
 *  - resId=false  → creation path
 *  - resId=number → update path
 *  - validity=true → _checkValidity passes
 *  - changes={}   → no-changes short-circuit on existing records
 *
 * @param {Object} [opts]
 * @param {number|false} [opts.resId]
 * @param {number[]} [opts.resIds]
 * @param {Object} [opts.changes]
 * @param {boolean} [opts.validity]
 * @param {Function|null} [opts.webSave]
 * @param {*} [opts.willSaveResult] - return value of onWillSaveRecord hook
 * @returns {Object}
 */
function makeRecord({
    resId = false,
    resIds = [],
    changes = {},
    validity = true,
    webSave = null,
    willSaveResult = undefined,
} = {}) {
    return {
        resId,
        resIds,
        resModel: "res.partner",
        context: {},
        dirty: true,
        // Empty activeFields: the _abandonRecords loop and fieldNames loops are skipped,
        // and getFieldsSpec({}, {}, …) returns {} immediately.
        activeFields: {},
        fields: {},
        fieldNames: [],
        data: {},
        config: {
            isRoot: false,
            context: { uid: 1, allowed_company_ids: [1] },
        },
        isInEdition: true,
        _changes: markRaw({}),
        _values: markRaw({}),
        _checkValidity: () => validity,
        _getChanges: () => ({ ...changes }),
        _discard: () => {},
        _load: async () => {},
        _setData: () => {},
        model: {
            _closeUrgentSaveNotification: null,
            _urgentSave: false,
            useSendBeaconToSaveUrgently: false,
            env: { inDialog: false },
            load: async () => {},
            _updateConfig: () => {},
            _updateSimilarRecords: () => {},
            hooks: {
                onWillSaveRecord: async () => willSaveResult,
                onRecordSaved: async () => {},
                onWillLoadRoot: () => {},
            },
            orm: {
                webSave:
                    webSave ??
                    (async () => (resId ? [{ id: resId }] : [{ id: 99 }])),
            },
        },
    };
}

// ---------------------------------------------------------------------------
// nextId on new record — throws immediately
// ---------------------------------------------------------------------------

describe("nextId on new record", () => {
    test("throws when nextId is supplied for a new (unsaved) record", async () => {
        const rec = makeRecord({ resId: false });
        let threw = false;
        try {
            await save(rec, { nextId: 5 });
        } catch (e) {
            threw = true;
            expect(e.message).toInclude("nextId");
        }
        expect(threw).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// Validity guard — returns false without calling webSave
// ---------------------------------------------------------------------------

describe("validity guard", () => {
    test("returns false when _checkValidity fails", async () => {
        let webSaveCalled = false;
        const rec = makeRecord({
            resId: 1,
            validity: false,
            webSave: async () => {
                webSaveCalled = true;
                return [{ id: 1 }];
            },
        });
        const result = await save(rec, { reload: false });
        expect(result).toBe(false);
        expect(webSaveCalled).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// No-changes short-circuit — returns true without calling webSave
// ---------------------------------------------------------------------------

describe("no-changes short-circuit", () => {
    test("returns true and skips webSave when an existing record has no changes", async () => {
        let webSaveCalled = false;
        const rec = makeRecord({
            resId: 1,
            changes: {}, // empty — no changes
            webSave: async () => {
                webSaveCalled = true;
                return [{ id: 1 }];
            },
        });
        const result = await save(rec, { reload: false });
        expect(result).toBe(true);
        expect(webSaveCalled).toBe(false);
        // Internal state must be reset
        expect(rec.dirty).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// Creation path — webSave is called with empty ids array
// ---------------------------------------------------------------------------

describe("creation path", () => {
    test("calls webSave with [] ids for a new record and returns true", async () => {
        const savedIds = [];
        const rec = makeRecord({
            resId: false, // new record
            resIds: [],
            changes: { name: "New Partner" },
            webSave: async (model, ids, vals) => {
                savedIds.push(...ids);
                return [{ id: 99, name: "New Partner" }];
            },
        });
        const result = await save(rec, { reload: false });
        expect(result).toBe(true);
        // Creation must pass [] as the id list
        expect(savedIds).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// Update path — webSave is called with [resId]
// ---------------------------------------------------------------------------

describe("update path", () => {
    test("calls webSave with [resId] for an existing record and returns true", async () => {
        const savedIds = [];
        const rec = makeRecord({
            resId: 7,
            changes: { name: "Updated" },
            webSave: async (model, ids) => {
                savedIds.push(...ids);
                return [{ id: 7, name: "Updated" }];
            },
        });
        const result = await save(rec, { reload: false });
        expect(result).toBe(true);
        expect(savedIds).toEqual([7]);
    });
});

// ---------------------------------------------------------------------------
// onError callback — called with error and action helpers
// ---------------------------------------------------------------------------

describe("onError callback", () => {
    test("calls onError with the thrown error and discard/retry helpers", async () => {
        const serverError = new Error("server error");
        let capturedError = null;
        let capturedActions = null;

        const rec = makeRecord({
            resId: 1,
            changes: { name: "x" },
            webSave: async () => {
                throw serverError;
            },
        });

        const result = await save(rec, {
            reload: false,
            onError: (e, actions) => {
                capturedError = e;
                capturedActions = actions;
                return "handled";
            },
        });

        // onError return value is propagated as the save result
        expect(result).toBe("handled");
        expect(capturedError).toBe(serverError);
        expect(typeof capturedActions.discard).toBe("function");
        expect(typeof capturedActions.retry).toBe("function");
    });
});

// ---------------------------------------------------------------------------
// FetchRecordError — thrown when webSave returns empty with reload:true
// ---------------------------------------------------------------------------

describe("FetchRecordError on empty reload response", () => {
    test("throws FetchRecordError when webSave returns [] and reload is true", async () => {
        // FetchRecordError calls _t() in its constructor — requires mock env
        await makeMockEnv();

        const rec = makeRecord({
            resId: 1,
            changes: { name: "updated" },
            webSave: async () => [], // empty response
        });

        let caughtError = null;
        try {
            // reload:true is the default — triggers the empty-records check
            await save(rec);
        } catch (e) {
            caughtError = e;
        }

        expect(caughtError).toBeInstanceOf(FetchRecordError);
        expect(caughtError.resIds).toEqual([1]);
    });
});
