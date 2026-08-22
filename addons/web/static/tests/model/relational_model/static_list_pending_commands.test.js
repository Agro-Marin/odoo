// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { markRaw } from "@odoo/owl";
import { MODEL_LIFECYCLE_PROTO } from "@web/../tests/model/relational_model/model_doubles";
import {
    installEditState,
    RECORD_STATE_TRANSITIONS,
} from "@web/../tests/model/relational_model/record_doubles";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { save } from "@web/model/relational_model/record_save";
import { RecordSaveCoordinator } from "@web/model/relational_model/record_save_coordinator";
import { StaticList } from "@web/model/relational_model/static_list";

const LINK = 4;

/**
 * @param {Object} [opts]
 * @param {(config: Object) => Promise<any[]>} [opts.loadRecords]
 * @returns {any}
 */
function makeList({ loadRecords = async () => [] } = {}) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        _membership: new ListMembership(),
        id: "datapoint_test",
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
        _cache: markRaw(new Map()),
        _commands: [],
        _initialCommands: [],
        _commandsPromise: null,
        _savePoint: undefined,
        _unknownRecordCommands: new Map(),
        _loadingStubIds: new Set(),
        _currentIds: [],
        _tmpIncreaseLimit: 0,
        _extendedRecords: new Set(),
        model: {
            _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
                Object.assign(config, patch),
            _loadRecords: (/** @type {any} */ config) => loadRecords(config),
        },
        _createRecordDatapoint(/** @type {any} */ data, params = {}) {
            const resId = data.id || false;
            const record = {
                resId,
                _virtualId: params.virtualId || null,
                activeFields: {},
                fields: {},
                fieldNames: [],
                _loadedFieldNames: new Set(Object.keys(data)),
                data: { ...data },
                _changes: {},
                _discard() {},
                _applyChanges(/** @type {any} */ changes, serverChanges = {}) {
                    Object.assign(
                        this.data,
                        changes,
                        this._parseServerValues(serverChanges),
                    );
                },
                _applyValues(/** @type {any} */ values) {
                    if (values) {
                        Object.assign(this.data, values);
                    }
                },
                _parseServerValues: (/** @type {any} */ changes) => changes,
            };
            this._cache.set(resId || record._virtualId, record);
            return record;
        },
    });
    return list;
}

describe("floating commands rejection", () => {
    test("a rejected commands load is surfaced, not silently dropped", async () => {
        expect.errors(1);
        const list = makeList({
            loadRecords: () => Promise.reject(new Error("load boom")),
        });

        list._applyInitialCommands([[LINK, 42, false]]);
        expect(list._commandsPromise).not.toBe(null);

        await animationFrame();

        expect.verifyErrors([/load boom/]);
        expect(list._commandsPromise).toBe(null);
    });

    test("synchronous command application does not create a pending promise", () => {
        const list = makeList();

        list._applyInitialCommands([[LINK, 7, { id: 7, display_name: "Rec 7" }]]);

        expect(list._commandsPromise).toBe(null);
        expect(list._currentIds).toInclude(7);
    });
});

describe("_discard prune sequencing", () => {
    test("_pruneCache runs only after the pending commands load settles", async () => {
        const def = new Deferred();
        const list = makeList({ loadRecords: () => def });

        list._cache.set("stale", { resId: false, _virtualId: "stale", _discard() {} });
        list._initialCommands = [[LINK, 42, false]];

        list._discard();

        expect(list._commandsPromise).not.toBe(null);
        expect(list._cache.has("stale")).toBe(true);

        def.resolve([{ id: 42, display_name: "Rec 42" }]);
        await animationFrame();

        expect(list._cache.has("stale")).toBe(false);
        expect(list._cache.get(42).data.display_name).toBe("Rec 42");
        expect(list._commandsPromise).toBe(null);
    });

    test("_pruneCache runs synchronously when nothing is pending", () => {
        const list = makeList();
        list._cache.set("stale", { resId: false, _virtualId: "stale", _discard() {} });

        list._discard();

        expect(list._cache.has("stale")).toBe(false);
    });
});

describe("save barrier on pending commands", () => {
    function makeRecord(/** @type {any} */ list, { /** @type {any} */ webSave }) {
        const record = {
            resId: 1,
            resIds: [1],
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
            _changes: markRaw({}),
            _values: markRaw({}),
            _textValues: markRaw({}),
            _setEvalContext() {},
            _checkValidity: () => true,
            _getChanges: () => ({ lines: list._getCommands() }),
            ...RECORD_STATE_TRANSITIONS,
            _clearChanges() {},
            _discard: () => {},
            _load: async () => {},
            _setData: () => {},
            model: {
                closeUrgentSaveNotification() {},
                urgentSave: { isActive: false },
                useSendBeaconToSaveUrgently: false,
                env: { inDialog: false },
                load: async () => {},
                _patchConfig: () => {},
                _updateSimilarRecords: () => {},
                __proto__: MODEL_LIFECYCLE_PROTO,
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
        installEditState(record, { dirty: true });
        return record;
    }

    test("save waits for an in-flight commands load before serializing", async () => {
        const def = new Deferred();
        const list = makeList({ loadRecords: () => def });

        list._trackCommandsPromise(list._applyCommands([[LINK, 42, false]]));
        expect(list._commandsPromise).not.toBe(null);

        /** @type {any[]} */
        let savedChanges = null;
        const rec = makeRecord(list, {
            webSave: async (
                /** @type {any} */ _model,
                /** @type {any} */ _ids,
                /** @type {any} */ changes,
            ) => {
                expect.step("webSave");
                savedChanges = changes;
                return [{ id: 1 }];
            },
        });

        const saveProm = save(rec, { reload: false });
        await animationFrame();
        expect.verifySteps([]);

        def.resolve([{ id: 42, display_name: "Rec 42" }]);
        const result = await saveProm;

        expect(result).toBe(true);
        expect.verifySteps(["webSave"]);
        expect(savedChanges.lines).toEqual([[LINK, 42, false]]);
        expect(list._cache.get(42).data.display_name).toBe("Rec 42");
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

    test("a failed replay's stub rows are re-fetched after the next successful save", async () => {
        expect.errors(1);
        let failLoads = true;
        const list = makeList({
            loadRecords: async ({ resIds }) => {
                if (failLoads) {
                    throw new Error("replay boom");
                }
                return resIds.map((/** @type {any} */ id) => ({
                    id,
                    display_name: `Rec ${id}`,
                }));
            },
        });

        list._trackCommandsPromise(list._applyCommands([[LINK, 42, false]]));
        await animationFrame();
        expect.verifyErrors([/replay boom/]);

        expect(list._cache.get(42).data).toEqual({ id: 42 });
        expect(list._replayFailed).toBe(true);

        failLoads = false;
        /** @type {any} */
        let savedChanges = null;
        const rec = makeRecord(list, {
            webSave: async (
                /** @type {any} */ _model,
                /** @type {any} */ _ids,
                /** @type {any} */ changes,
            ) => {
                savedChanges = changes;
                return [{ id: 1 }];
            },
        });
        rec._values = markRaw({ lines: list });

        const result = await save(/** @type {any} */ (rec), { reload: false });
        await list._commandsPromise;

        expect(result).toBe(true);
        expect(savedChanges.lines).toEqual([[LINK, 42, false]]);
        expect(list._cache.get(42).data.display_name).toBe("Rec 42");
        expect(list._replayFailed).toBe(false);
    });

    test("the barrier gives up after a bounded number of iterations", async () => {
        const list = makeList();
        list._applyCommands([[LINK, 7, { id: 7, display_name: "Rec 7" }]]);
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

        expect(result).toBe(true);
        expect.verifySteps(["webSave"]);
        expect(warnings.length).toBe(1);
        expect(warnings[0]).toInclude("did not quiesce");
    });
});
