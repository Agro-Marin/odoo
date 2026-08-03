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
import { RECORD_STATE_TRANSITIONS } from "@web/../tests/model/relational_model/record_doubles";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { FetchRecordError } from "@web/model/relational_model/errors";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { save } from "@web/model/relational_model/record_save";
import { RecordSaveCoordinator } from "@web/model/relational_model/record_save_coordinator";
import { computeChangeset } from "@web/model/relational_model/record_utils";
import { UrgentSaveCoordinator } from "@web/model/relational_model/urgent_save_coordinator";

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
        saveState: new RecordSaveCoordinator(),
        context: {},
        dirty: true,
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
        ...RECORD_STATE_TRANSITIONS,
        _clearChanges() {
            this._changes = markRaw({});
            this.dirty = false;
        },
        _discard: () => {},
        _load: async () => {},
        _setData: () => {},
        _setEvalContext: () => {},
        model: {
            closeUrgentSaveNotification() {},
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
        expect(rec.dirty).toBe(false);
        expect(evalContextCalls).toBe(1);
    });
});

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
        expect(savedIds).toEqual([]);
    });
});

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

describe("reload:false save-in-place text-value baseline", () => {
    test("refreshes _initialTextValues and eval context from persisted state", async () => {
        const rec = makeRecord({
            resId: 7,
            changes: { name: "Typed value" },
            webSave: async () => [{ id: 7, name: "Typed value" }],
        });
        rec._textValues = markRaw({ name: "Typed value" });
        rec._initialTextValues = markRaw({ name: false });
        let evalContextCalls = 0;
        rec._setEvalContext = () => evalContextCalls++;

        const result = await save(rec, { reload: false });

        expect(result).toBe(true);
        expect(rec._initialTextValues).toEqual({ name: "Typed value" });
        expect(evalContextCalls).toBe(1);
    });
});

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

        expect(result).toBe("handled");
        expect(capturedError).toBe(serverError);
        expect(typeof capturedActions.discard).toBe("function");
        expect(typeof capturedActions.retry).toBe("function");
    });
});

describe("FetchRecordError on empty reload response", () => {
    test("throws FetchRecordError when webSave returns [] and reload is true", async () => {
        await makeMockEnv();

        const rec = makeRecord({
            resId: 1,
            changes: { name: "updated" },
            webSave: async () => [],
        });

        let caughtError = null;
        try {
            await save(rec);
        } catch (e) {
            caughtError = e;
        }

        expect(caughtError).toBeInstanceOf(FetchRecordError);
        expect(caughtError.resIds).toEqual([1]);
    });
});

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
        rec.fields = { name: { type: "char" } };
        rec._values = markRaw({ name: "Original name" });
        rec.model.urgentSave.isActive = true;
        rec.model.useSendBeaconToSaveUrgently = true;

        const result = await save(rec, { reload: false });

        expect(result).toBe(true);
        expect(capturedBlob).not.toBe(null);
        const payload = JSON.parse(await capturedBlob.text());
        expect(payload.params.method).toBe("web_save");
        expect(payload.params.kwargs.known_values).toEqual({ name: "Original name" });
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
        expect(payload.params.kwargs.known_values).toEqual({ name: "orig" });
    });

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
            partner_id: { display_name: "New Co" },
            line_ids: [[0, 0, { name: "child" }]],
        };

        const rec = makeRecord({ resId: 7, changes: {} });
        rec.fields = fields;
        rec.activeFields = activeFields;
        rec._values = markRaw({ name: "orig", partner_id: false, line_ids: [] });
        rec.data = { line_ids: { _abandonRecords() {}, _clearCommands() {} } };
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

        expect(result).toBe(true);
        expect(capturedBlob).not.toBe(null);
        const payload = JSON.parse(await capturedBlob.text());
        const sentChanges = payload.params.args[1];
        expect(sentChanges.name).toBe("kept");
        expect("partner_id" in sentChanges).toBe(false);
        expect("line_ids" in sentChanges).toBe(false);
    });

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
            saveState: new RecordSaveCoordinator(),
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
            ...RECORD_STATE_TRANSITIONS,
            _clearChanges() {
                this.clearChangesCalls++;
                this._changes = markRaw({});
            },
            _discard: () => {},
            _load: async () => {},
            _setData: () => {},
            _setEvalContext: () => {},
            model: {
                closeUrgentSaveNotification() {},
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
        expect(list.clearCommandsCalls).toBe(1);
        expect(rec.clearChangesCalls).toBe(1);
    });
});

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
        rec.saveState = new RecordSaveCoordinator();
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
        expect(rec.saveState.isInFlight).toBe(true);

        const urgentResult = await rec.urgentSave();
        expect(urgentResult).toBe(true);
        expect(beaconCalls).toBe(0);
        expect(webSaveCalls).toBe(1);

        def.resolve();
        await saveProm;
        expect(rec.saveState.isInFlight).toBe(false);
        expect(webSaveCalls).toBe(1);
    });

    test("urgentSave fires the beacon while a save is parked in onWillSaveRecord; the resumed save does not double-write", async () => {
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
        rec.model.hooks.lifecycle.onWillSaveRecord = async () => {
            await hookDef;
        };

        const saveProm = save(rec, { reload: false });
        await animationFrame();
        expect(webSaveCalls).toBe(0);
        expect(rec.saveState.isInFlight).toBe(false);

        const urgentResult = await rec.urgentSave();
        expect(urgentResult).toBe(true);
        expect(beaconCalls).toBe(1);
        expect(webSaveCalls).toBe(0);

        hookDef.resolve();
        expect(await saveProm).toBe(true);
        expect(rec.saveState.isInFlight).toBe(false);
        expect(webSaveCalls).toBe(0);
        expect(rec.saveState.beaconFired).toBe(false);
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

    test("a leaked beacon flag does not short-circuit a later real save", async () => {
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

        await rec.urgentSave();
        expect(beaconCalls).toBe(1);
        expect(rec.saveState.beaconFired).toBe(true);

        const result = await save(rec, { reload: false });
        expect(result).toBe(true);
        expect(webSaveCalls).toBe(1);
        expect(rec.saveState.beaconFired).toBe(false);
    });
});
