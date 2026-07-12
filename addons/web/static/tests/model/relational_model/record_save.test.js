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

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred, mockSendBeacon } from "@odoo/hoot-mock";
import { markRaw } from "@odoo/owl";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { FetchRecordError } from "@web/model/relational_model/errors";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { save } from "@web/model/relational_model/record_save";
import { computeChangeset } from "@web/model/relational_model/record_utils";
import { UrgentSaveCoordinator } from "@web/model/relational_model/urgent_save_coordinator";

// Mock factory

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
        _setEvalContext: () => {},
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
            _patchConfig: () => {},
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
                    webSave ?? (async () => (resId ? [{ id: resId }] : [{ id: 99 }])),
            },
        },
    };
}

// nextId on new record — throws immediately

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

// Validity guard — returns false without calling webSave

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

// No-changes short-circuit — returns true without calling webSave

describe("no-changes short-circuit", () => {
    test("returns true and skips webSave when an existing record has no changes", async () => {
        let webSaveCalled = false;
        const rec = makeRecord({
            resId: 1,
            changes: {},
            webSave: async () => {
                webSaveCalled = true;
                return [{ id: 1 }];
            },
        });
        let evalContextCalls = 0;
        rec._setEvalContext = () => evalContextCalls++;
        const result = await save(rec, { reload: false });
        expect(result).toBe(true);
        expect(webSaveCalled).toBe(false);
        // Internal state must be reset
        expect(rec.dirty).toBe(false);
        // ``data`` was rebuilt from ``_values``, so the eval contexts must
        // follow — otherwise modifiers evaluate against the discarded values.
        expect(evalContextCalls).toBe(1);
    });
});

// Creation path — webSave is called with empty ids array

describe("creation path", () => {
    test("calls webSave with [] ids for a new record and returns true", async () => {
        const savedIds = [];
        const rec = makeRecord({
            resId: false,
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

// Update path — webSave is called with [resId]

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

// onError callback — called with error and action helpers

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

// FetchRecordError — thrown when webSave returns empty with reload:true

describe("FetchRecordError on empty reload response", () => {
    test("throws FetchRecordError when webSave returns [] and reload is true", async () => {
        // FetchRecordError calls _t() in its constructor — requires mock env
        await makeMockEnv();

        const rec = makeRecord({
            resId: 1,
            changes: { name: "updated" },
            webSave: async () => [],
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

// Urgent save (sendBeacon path) — must mirror the normal-save path's
// field-scoped optimistic locking so the server can reject a genuine
// concurrent edit even when the save was initiated by sendBeacon on tab
// close. Both paths send the originally-loaded baseline of the written
// fields as kwargs.known_values (record_save.js:111-115 for the urgent
// branch, :171-176 for the normal branch). Without it, two users editing
// the same record could both close their tabs and the later beacon would
// silently overwrite the earlier write.
//
// NB: the mechanism is field-scoped (known_values), NOT timestamp-based
// (last_write_date). The latter was the pre-2026-06 design, replaced by
// commits "field-scoped optimistic locking in web_save" and "exclude
// jsonb-backed fields from web_save optimistic locking".

describe("urgent save (sendBeacon path)", () => {
    test("sends comparable changed fields as kwargs.known_values baseline", async () => {
        let capturedBlob = null;
        mockSendBeacon((_url, blob) => {
            capturedBlob = blob;
            return true;
        });

        const rec = makeRecord({
            resId: 7,
            changes: { name: "Updated under urgent save" },
        });
        // concurrencyBaseline reads record.fields[f].type and record._values[f]
        // for each changed field, so the mock must supply both.
        rec.fields = { name: { type: "char" } };
        rec._values = markRaw({ name: "Original name" });
        rec.model.urgentSave.isActive = true;
        rec.model.useSendBeaconToSaveUrgently = true;

        const result = await save(rec, { reload: false });

        expect(result).toBe(true);
        expect(capturedBlob).not.toBe(null);
        const payload = JSON.parse(await capturedBlob.text());
        expect(payload.params.method).toBe("web_save");
        // The baseline (pre-edit value) of the written scalar field is sent so
        // the server can detect a genuine concurrent write to THIS field.
        expect(payload.params.kwargs.known_values).toEqual({ name: "Original name" });
        // The obsolete timestamp-based contract must not reappear.
        expect(payload.params.kwargs.last_write_date).toBe(undefined);
    });

    test("omits non-comparable field types from kwargs.known_values", async () => {
        let capturedBlob = null;
        mockSendBeacon((_url, blob) => {
            capturedBlob = blob;
            return true;
        });

        const rec = makeRecord({
            resId: 7,
            // A comparable char field alongside types the baseline must skip:
            // datetime (not safely comparable) and a translate-flagged char
            // (jsonb-backed; server reads a per-lang dict, never the scalar).
            changes: { name: "X", deadline: "2026-05-01 12:00:00", note: "hi" },
        });
        rec.fields = {
            name: { type: "char" },
            deadline: { type: "datetime" },
            note: { type: "char", translate: true },
        };
        rec._values = markRaw({
            name: "orig",
            deadline: "2026-01-01 00:00:00",
            note: "hola",
        });
        rec.model.urgentSave.isActive = true;
        rec.model.useSendBeaconToSaveUrgently = true;

        await save(rec, { reload: false });

        const payload = JSON.parse(await capturedBlob.text());
        // Only the plain scalar survives; datetime and translate-flagged
        // fields are excluded so the server fails open on them.
        expect(payload.params.kwargs.known_values).toEqual({ name: "orig" });
    });

    // HIGH regression: on tab close the 6 async preprocessors do NOT run, so
    // `_changes` can still hold RAW values — a many2one still awaiting its
    // name_create (`{display_name}`, no id) and a raw x2many command array
    // (not a StaticList). Before the defensive normalization in
    // computeChangeset, the m2o serialized to `undefined` (silently dropped by
    // JSON.stringify → field lost) and the raw x2many array threw a TypeError
    // inside `_getChanges` → the beacon NEVER fired and ALL pending fields were
    // lost. The save must now still fire the beacon, dropping only the two
    // un-preprocessed fields while every serializable field reaches the server.
    test("urgent beacon drops un-preprocessed m2o/x2many, keeps serializable fields", async () => {
        let capturedBlob = null;
        mockSendBeacon((_url, blob) => {
            capturedBlob = blob;
            return true;
        });

        const fields = {
            name: { type: "char" },
            partner_id: { type: "many2one" },
            line_ids: { type: "one2many" },
        };
        const activeFields = {
            name: { readonly: false },
            partner_id: { readonly: false },
            line_ids: { readonly: false },
        };
        const rawChanges = {
            name: "kept",
            partner_id: { display_name: "New Co" }, // no id → name_create pending
            line_ids: [[0, 0, { name: "child" }]], // raw command array, not a StaticList
        };

        const rec = makeRecord({ resId: 7, changes: {} });
        rec.fields = fields;
        rec.activeFields = activeFields;
        rec._values = markRaw({ name: "orig", partner_id: false, line_ids: [] });
        // The pre-save _abandonRecords loop touches x2many datapoints in data.
        rec.data = { line_ids: { _abandonRecords() {} } };
        // Delegate to the REAL changeset builder over the raw (un-preprocessed)
        // changes, exactly as record._getChanges does in production.
        rec._getChanges = () =>
            computeChangeset({
                changes: rawChanges,
                values: rec._values,
                isNew: false,
                fields,
                activeFields,
                evalContext: {},
                getCommands: (f, value, wr) => value._getCommands({ withReadonly: wr }),
            });
        rec.model.urgentSave.isActive = true;
        rec.model.useSendBeaconToSaveUrgently = true;

        const result = await save(rec, { reload: false });

        // The beacon fired instead of throwing on the raw x2many array.
        expect(result).toBe(true);
        expect(capturedBlob).not.toBe(null);
        const payload = JSON.parse(await capturedBlob.text());
        const sentChanges = payload.params.args[1];
        expect(sentChanges.name).toBe("kept");
        // The un-preprocessed m2o (no id) and x2many (raw array) are dropped —
        // NOT emitted as `undefined`, NOT the cause of a thrown beacon.
        expect("partner_id" in sentChanges).toBe(false);
        expect("line_ids" in sentChanges).toBe(false);
    });

    // The beacon-success branch merges _changes into _values and clears the
    // change bag, but — like the reload:false branch — must ALSO clear each
    // x2many list's staged commands. Otherwise, if the page survives the beacon
    // (bfcache Back after tab close), the stale CREATE/LINK commands remain and
    // the next save re-serializes them, duplicating child rows.
    test("clears x2many list commands on beacon success", async () => {
        mockSendBeacon(() => true);

        const list = {
            clearCommandsCalls: 0,
            _clearCommands() {
                this.clearCommandsCalls++;
            },
            _abandonRecords() {},
            _getCommands() {
                return [[0, "virt-1", { name: "child" }]];
            },
        };
        const rec = {
            resId: 7,
            resIds: [7],
            resModel: "res.partner",
            context: {},
            dirty: true,
            activeFields: { lines: {} },
            fields: { lines: { type: "one2many" } },
            fieldNames: ["lines"],
            data: { lines: list },
            config: { isRoot: false, context: {} },
            isInEdition: true,
            _changes: markRaw({ lines: list }),
            _values: markRaw({}),
            _textValues: markRaw({}),
            _initialTextValues: markRaw({}),
            _checkValidity: () => true,
            _getChanges: () => ({ lines: list._getCommands() }),
            clearChangesCalls: 0,
            _clearChanges() {
                this.clearChangesCalls++;
                this._changes = markRaw({});
            },
            _discard: () => {},
            _load: async () => {},
            _setData: () => {},
            _setEvalContext: () => {},
            model: {
                _closeUrgentSaveNotification: null,
                urgentSave: { isActive: true },
                useSendBeaconToSaveUrgently: true,
                env: { inDialog: false },
                load: async () => {},
                _patchConfig: () => {},
                _updateSimilarRecords: () => {},
                hooks: {
                    lifecycle: {
                        onWillSaveRecord: async () => {},
                        onRecordSaved: async () => {},
                        onWillLoadRoot: () => {},
                    },
                    ui: {},
                },
                orm: { webSave: async () => [{ id: 7 }] },
            },
        };

        const result = await save(rec, { reload: false });

        expect(result).toBe(true);
        // The x2many list's staged commands were cleared exactly once, before
        // the change bag was emptied.
        expect(list.clearCommandsCalls).toBe(1);
        expect(rec.clearChangesCalls).toBe(1);
    });
});

// urgentSave duplicate-beacon guard — a save whose web_save RPC is still on
// the wire keeps ``_changes`` fully populated (x2many CREATE commands
// included, which are NOT idempotent) until the RPC settles. If the tab
// closes in that window, urgentSave() must skip the beacon instead of
// re-sending the same payload and duplicating child rows. The guard is the
// ``_saveInFlight`` flag record_save.save holds from the RPC until the
// change bag is cleared.

describe("urgentSave in-flight guard", () => {
    /**
     * Record mock backed by the real RelationalRecord prototype, so the real
     * ``urgentSave()``/``_save()``/``_clearChanges()`` methods run against
     * record_save.save. State goes through ``_config``/``_editState`` so the
     * prototype getters (resId, fields, fieldNames, dirty, _changes, …) work
     * unmodified.
     */
    function makeProtoRecord({ webSave }) {
        const rec = Object.create(RelationalRecord.prototype);
        rec._editState = new RecordEditState();
        rec._config = {
            resModel: "res.partner",
            resId: 7,
            resIds: [7],
            mode: "edit",
            context: {},
            activeFields: {},
            fields: { name: { type: "char" } },
            isRoot: false,
        };
        rec.data = {};
        rec.dirty = true;
        rec._saveInFlight = false;
        rec._values = markRaw({ name: "orig" });
        rec._checkValidity = () => true;
        rec._getChanges = () => ({ name: "X" });
        rec._discard = () => {};
        rec._load = async () => {};
        rec._setData = () => {};
        rec._setEvalContext = () => {};
        rec.model = makeRecord({ resId: 7, webSave }).model;
        rec.model.urgentSave = new UrgentSaveCoordinator();
        rec.model.useSendBeaconToSaveUrgently = true;
        return rec;
    }

    test("urgentSave skips the beacon while a save is on the wire", async () => {
        let beaconCalls = 0;
        mockSendBeacon(() => {
            beaconCalls++;
            return true;
        });
        const def = new Deferred();
        let webSaveCalls = 0;
        const rec = makeProtoRecord({
            webSave: async () => {
                webSaveCalls++;
                await def;
                return [{ id: 7 }];
            },
        });

        const saveProm = save(rec, { reload: false });
        await animationFrame();
        expect(webSaveCalls).toBe(1);
        expect(rec._saveInFlight).toBe(true);

        // Tab closes while the RPC is pending: only ONE web_save may reach
        // the server.
        const urgentResult = await rec.urgentSave();
        expect(urgentResult).toBe(true);
        expect(beaconCalls).toBe(0);
        expect(webSaveCalls).toBe(1);

        def.resolve();
        await saveProm;
        expect(rec._saveInFlight).toBe(false);
        expect(webSaveCalls).toBe(1);
    });

    test("urgentSave skips the beacon while a save is parked in onWillSaveRecord", async () => {
        let beaconCalls = 0;
        mockSendBeacon(() => {
            beaconCalls++;
            return true;
        });
        const hookDef = new Deferred();
        let webSaveCalls = 0;
        const rec = makeProtoRecord({
            webSave: async () => {
                webSaveCalls++;
                return [{ id: 7 }];
            },
        });
        // Enterprise controllers override this hook with dialogs/RPCs that
        // can park a save for seconds before its RPC fires.
        rec.model.hooks.lifecycle.onWillSaveRecord = async () => {
            await hookDef;
        };

        const saveProm = save(rec, { reload: false });
        await animationFrame();
        // Parked in the hook: no RPC yet, but the in-flight marker is up.
        expect(webSaveCalls).toBe(0);
        expect(rec._saveInFlight).toBe(true);

        // Tab closes while the save is parked: the beacon must be skipped —
        // the beacon + the parked webSave used to double-write the same
        // changes (duplicate x2many CREATEs the server cannot reject).
        const urgentResult = await rec.urgentSave();
        expect(urgentResult).toBe(true);
        expect(beaconCalls).toBe(0);
        expect(webSaveCalls).toBe(0);

        hookDef.resolve();
        await saveProm;
        expect(rec._saveInFlight).toBe(false);
        expect(webSaveCalls).toBe(1);
    });

    test("urgentSave still fires when no save is in flight", async () => {
        let beaconCalls = 0;
        mockSendBeacon(() => {
            beaconCalls++;
            return true;
        });
        let webSaveCalls = 0;
        const rec = makeProtoRecord({
            webSave: async () => {
                webSaveCalls++;
                return [{ id: 7 }];
            },
        });

        const result = await rec.urgentSave();

        expect(result).toBe(true);
        expect(beaconCalls).toBe(1);
        expect(webSaveCalls).toBe(0);
    });
});
