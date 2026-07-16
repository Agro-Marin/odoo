// @ts-check

/**
 * Tests for StaticList's floating-commands tracking (``_trackCommandsPromise``
 * / ``_commandsPromise``): rejection surfacing via the error service,
 * ``_discard`` → ``_pruneCache`` sequencing, and the ``record_save.save``
 * barrier.
 *
 * Uses ``Object.create(StaticList.prototype)`` so real methods (including
 * ``_applyCommands``) run against a hand-built state, mirroring
 * static_list_command_engine.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { markRaw } from "@odoo/owl";
import { save } from "@web/model/relational_model/record_save";
import { StaticList } from "@web/model/relational_model/static_list";

const LINK = 4;

// Mock factory

/**
 * Build a StaticList-shaped object backed by the real StaticList prototype.
 *
 * @param {Object} [opts]
 * @param {(config: Object) => Promise<any[]>} [opts.loadRecords]
 * @returns {any}
 */
function makeList({ loadRecords = async () => [] } = {}) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        id: "datapoint_test",
        // config/activeFields/fields/resModel/context are prototype getters
        // deriving from _config (see DataPoint)
        _config: {
            limit: 40,
            offset: 0,
            resIds: [],
            orderBy: [],
            resModel: "res.partner",
            context: {},
            activeFields: { display_name: {} },
            fields: { display_name: { type: "char" } },
        },
        records: [],
        count: 0,
        _cache: markRaw({}),
        _commands: [],
        _initialCommands: [],
        _commandsPromise: null,
        _savePoint: undefined,
        _unknownRecordCommands: {},
        _loadingStubIds: new Set(),
        _currentIds: [],
        _tmpIncreaseLimit: 0,
        _extendedRecords: new Set(),
        model: {
            _patchConfig: (config, patch) => Object.assign(config, patch),
            _loadRecords: (config) => loadRecords(config),
        },
        // simplified datapoint factory (the real one needs the full model)
        _createRecordDatapoint(data, params = {}) {
            const resId = data.id || false;
            const record = {
                resId,
                _virtualId: params.virtualId || null,
                activeFields: {},
                fields: {},
                fieldNames: [],
                data: { ...data },
                _changes: {},
                _discard() {},
                _applyChanges(changes) {
                    Object.assign(this.data, changes);
                },
                _applyValues(values) {
                    if (values) {
                        Object.assign(this.data, values);
                    }
                },
                _parseServerValues: (changes) => changes,
            };
            this._cache[resId || record._virtualId] = record;
            return record;
        },
    });
    return list;
}

// Rejection surfacing

describe("floating commands rejection", () => {
    test("a rejected commands load is surfaced, not silently dropped", async () => {
        expect.errors(1);
        const list = makeList({
            loadRecords: () => Promise.reject(new Error("load boom")),
        });

        // LINK without data forces a record-values fetch → async result that
        // the caller (a sync chain) cannot await.
        list._applyInitialCommands([[LINK, 42, false]]);
        expect(list._commandsPromise).not.toBe(null);

        await animationFrame();

        // The rejection reached the error surface (unhandledrejection)...
        expect.verifyErrors([/load boom/]);
        // ...and the tracked chain settled and was cleared, so later flows
        // (save barrier, discard prune) are not blocked by the failure.
        expect(list._commandsPromise).toBe(null);
    });

    test("synchronous command application does not create a pending promise", () => {
        const list = makeList();

        // LINK with data — fully synchronous application
        list._applyInitialCommands([[LINK, 7, { id: 7, display_name: "Rec 7" }]]);

        expect(list._commandsPromise).toBe(null);
        expect(list._currentIds).toInclude(7);
    });
});

// _discard × _pruneCache sequencing

describe("_discard prune sequencing", () => {
    test("_pruneCache runs only after the pending commands load settles", async () => {
        const def = new Deferred();
        const list = makeList({ loadRecords: () => def });

        // A stale cache entry not referenced by resIds/_currentIds: pruning
        // would evict it.
        list._cache["stale"] = { resId: false, _virtualId: "stale", _discard() {} };
        // Initial commands whose re-application on discard needs a fetch.
        list._initialCommands = [[LINK, 42, false]];

        list._discard();

        // The load is still in flight — the prune must not have run yet.
        expect(list._commandsPromise).not.toBe(null);
        expect("stale" in list._cache).toBe(true);

        def.resolve([{ id: 42, display_name: "Rec 42" }]);
        await animationFrame();

        // Load settled → prune ran → stale entry evicted, linked row loaded.
        expect("stale" in list._cache).toBe(false);
        expect(list._cache[42].data.display_name).toBe("Rec 42");
        expect(list._commandsPromise).toBe(null);
    });

    test("_pruneCache runs synchronously when nothing is pending", () => {
        const list = makeList();
        list._cache["stale"] = { resId: false, _virtualId: "stale", _discard() {} };

        list._discard();

        expect("stale" in list._cache).toBe(false);
    });
});

// Save barrier

describe("save barrier on pending commands", () => {
    /**
     * Minimal record mock for record_save.save() holding one x2many whose
     * StaticList is backed by the real prototype (same shape as
     * record_save.test.js's factory, plus the x2many field).
     */
    function makeRecord(list, { webSave }) {
        return {
            resId: 1,
            resIds: [1],
            resModel: "res.partner",
            context: {},
            dirty: true,
            activeFields: { lines: {} },
            fields: { lines: { type: "one2many" } },
            fieldNames: ["lines"],
            data: { lines: list },
            config: { isRoot: false, context: {} },
            isInEdition: true,
            _changes: markRaw({}),
            _values: markRaw({}),
            _textValues: markRaw({}),
            _setEvalContext() {},
            _checkValidity: () => true,
            // Serialize the x2many through the real command serializer, as
            // record._getChanges does for a dirty x2many.
            _getChanges: () => ({ lines: list._getCommands() }),
            _clearChanges() {},
            _discard: () => {},
            _load: async () => {},
            _setData: () => {},
            model: {
                _closeUrgentSaveNotification: null,
                urgentSave: { isActive: false },
                useSendBeaconToSaveUrgently: false,
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
                orm: { webSave },
            },
        };
    }

    test("save waits for an in-flight commands load before serializing", async () => {
        const def = new Deferred();
        const list = makeList({ loadRecords: () => def });

        // Simulate an onchange returning a LINK command without values: the
        // sync chain applies it and tracks the resulting floating load.
        list._trackCommandsPromise(list._applyCommands([[LINK, 42, false]]));
        expect(list._commandsPromise).not.toBe(null);

        /** @type {any[]} */
        let savedChanges = null;
        const rec = makeRecord(list, {
            webSave: async (_model, _ids, changes) => {
                expect.step("webSave");
                savedChanges = changes;
                return [{ id: 1 }];
            },
        });

        // Save immediately, while the load is pending.
        const saveProm = save(rec, { reload: false });
        await animationFrame();
        // The barrier must hold the save back until the load settles.
        expect.verifySteps([]);

        def.resolve([{ id: 42, display_name: "Rec 42" }]);
        const result = await saveProm;

        expect(result).toBe(true);
        expect.verifySteps(["webSave"]);
        // The payload carries the linked row's command, serialized from a
        // stable (fully loaded) list state.
        expect(savedChanges.lines).toEqual([[LINK, 42, false]]);
        expect(list._cache[42].data.display_name).toBe("Rec 42");
    });

    test("save proceeds without delay when no commands load is pending", async () => {
        const list = makeList();
        list._applyCommands([[LINK, 7, { id: 7, display_name: "Rec 7" }]]);

        const rec = makeRecord(list, {
            webSave: async () => {
                expect.step("webSave");
                return [{ id: 1 }];
            },
        });

        const result = await save(rec, { reload: false });

        expect(result).toBe(true);
        expect.verifySteps(["webSave"]);
    });

    test("the barrier gives up after a bounded number of iterations", async () => {
        const list = makeList();
        list._applyCommands([[LINK, 7, { id: 7, display_name: "Rec 7" }]]);
        // A pathological list whose floating-commands promise regenerates on
        // every read: without the iteration cap the save would hang forever
        // inside the mutex with no diagnostic.
        Object.defineProperty(list, "_commandsPromise", {
            get: () => Promise.resolve(),
            set: () => {},
        });

        const rec = makeRecord(list, {
            webSave: async () => {
                expect.step("webSave");
                return [{ id: 1 }];
            },
        });

        const warnings = [];
        const originalWarn = console.warn;
        console.warn = (...args) => warnings.push(args.join(" "));
        let result;
        try {
            result = await save(rec, { reload: false });
        } finally {
            console.warn = originalWarn;
        }

        // Degraded mode: the save still goes through, loudly.
        expect(result).toBe(true);
        expect.verifySteps(["webSave"]);
        expect(warnings.length).toBe(1);
        expect(warnings[0]).toInclude("did not quiesce");
    });
});
