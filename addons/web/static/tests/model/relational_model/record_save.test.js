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
import { mockSendBeacon } from "@odoo/hoot-mock";
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
        _clearChanges() {
            this._changes = markRaw({});
            this.dirty = false;
        },
        _discard: () => {},
        _load: async () => {},
        _setData: () => {},
        model: {
            _closeUrgentSaveNotification: null,
            // ``record_save.save`` reads ``model.urgentSave.isActive`` (see
            // :model/relational_model/record_save.js:69) — the legacy
            // ``_urgentSave: false`` shape was replaced by an observable
            // object so the urgent-save UI can react to mode changes.
            urgentSave: { isActive: false },
            useSendBeaconToSaveUrgently: false,
            env: { inDialog: false },
            load: async () => {},
            _updateConfig: () => {},
            _updateSimilarRecords: () => {},
            hooks: {
                lifecycle: {
                    onWillSaveRecord: async () => willSaveResult,
                    onRecordSaved: async () => {},
                    onWillLoadRoot: () => {},
                },
                ui: {},
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

// ---------------------------------------------------------------------------
// Urgent save (sendBeacon path) — must include last_write_date in kwargs so
// the server can reject the write under optimistic-locking. The normal-save
// path sets kwargs.last_write_date at record_save.js:135; the urgent path
// must mirror that or two users editing the same record can both close
// their tabs and the later beacon silently overwrites the earlier write.
// ---------------------------------------------------------------------------

describe("urgent save (sendBeacon path)", () => {
    test("includes string write_date as kwargs.last_write_date", async () => {
        let capturedBlob = null;
        mockSendBeacon((_url, blob) => {
            capturedBlob = blob;
            return true;
        });

        const rec = makeRecord({
            resId: 7,
            changes: { name: "Updated under urgent save" },
        });
        rec._values = markRaw({ write_date: "2026-05-01 12:00:00" });
        rec.model.urgentSave.isActive = true;
        rec.model.useSendBeaconToSaveUrgently = true;

        const result = await save(rec, { reload: false });

        expect(result).toBe(true);
        expect(capturedBlob).not.toBe(null);
        const payload = JSON.parse(await capturedBlob.text());
        expect(payload.params.method).toBe("web_save");
        expect(payload.params.kwargs.last_write_date).toBe("2026-05-01 12:00:00");
    });

    test("converts Luxon DateTime write_date via toISO() before sending", async () => {
        let capturedBlob = null;
        mockSendBeacon((_url, blob) => {
            capturedBlob = blob;
            return true;
        });

        // Minimal Luxon DateTime stub: only needs .toISO(), matching the
        // type-narrowing logic at record_save.js:135 (the normal save path).
        const luxonStub = { toISO: () => "2026-05-01T12:00:00.000-06:00" };

        const rec = makeRecord({
            resId: 7,
            changes: { name: "Updated under urgent save" },
        });
        rec._values = markRaw({ write_date: luxonStub });
        rec.model.urgentSave.isActive = true;
        rec.model.useSendBeaconToSaveUrgently = true;

        await save(rec, { reload: false });

        const payload = JSON.parse(await capturedBlob.text());
        expect(payload.params.kwargs.last_write_date).toBe(
            "2026-05-01T12:00:00.000-06:00",
        );
    });
});
