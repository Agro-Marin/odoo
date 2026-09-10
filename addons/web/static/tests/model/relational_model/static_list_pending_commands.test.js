// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { markRaw } from "@odoo/owl";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { save } from "@web/model/relational_model/record_save";
import { StaticList } from "@web/model/relational_model/static_list";

import { makeTestRecordWithLines } from "./model_test_helpers.js";

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
            patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
                Object.assign(config, patch),
            loadRecords: (/** @type {any} */ config) => loadRecords(config),
        },
        _createRecordDatapoint(/** @type {any} */ data, params = {}) {
            const resId = data.id || false;
            const record = {
                resId,
                virtualId: params.virtualId || null,
                activeFields: {},
                fields: {},
                fieldNames: /** @type {string[]} */ ([]),
                loadedFieldNames: new Set(Object.keys(data)),
                data: { ...data },
                changes: {},
                discardLocked() {},
                applyChanges(/** @type {any} */ changes, serverChanges = {}) {
                    Object.assign(
                        this.data,
                        changes,
                        this.parseServerValues(serverChanges),
                    );
                },
                applyValues(/** @type {any} */ values) {
                    if (values) {
                        Object.assign(this.data, values);
                    }
                },
                parseServerValues: (/** @type {any} */ changes) => changes,
            };
            this._cache.set(resId || record.virtualId, record);
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

        list.applyInitialCommands([[LINK, 42, false]]);
        expect(list._commandsPromise).not.toBe(null);

        await animationFrame();

        expect.verifyErrors([/load boom/]);
        expect(list._commandsPromise).toBe(null);
    });

    test("synchronous command application does not create a pending promise", () => {
        const list = makeList();

        list.applyInitialCommands([[LINK, 7, { id: 7, display_name: "Rec 7" }]]);

        expect(list._commandsPromise).toBe(null);
        expect(list._currentIds).toInclude(7);
    });
});

describe("discardLocked prune sequencing", () => {
    test("_removeUnpinnedRecords runs only after the pending commands load settles", async () => {
        const def = new Deferred();
        const list = makeList({ loadRecords: () => def });

        list._cache.set("stale", {
            resId: false,
            virtualId: "stale",
            discardLocked() {},
        });
        list._initialCommands = [[LINK, 42, false]];

        list.discardLocked();

        expect(list._commandsPromise).not.toBe(null);
        expect(list._cache.has("stale")).toBe(true);

        def.resolve([{ id: 42, display_name: "Rec 42" }]);
        await animationFrame();

        expect(list._cache.has("stale")).toBe(false);
        expect(list._cache.get(42).data.display_name).toBe("Rec 42");
        expect(list._commandsPromise).toBe(null);
    });

    test("_removeUnpinnedRecords runs synchronously when nothing is pending", () => {
        const list = makeList();
        list._cache.set("stale", {
            resId: false,
            virtualId: "stale",
            discardLocked() {},
        });

        list.discardLocked();

        expect(list._cache.has("stale")).toBe(false);
    });
});

describe("save barrier on pending commands", () => {
    /**
     * @param {StaticList} list
     * @param {{webSave: import("services").ServiceFactories["orm"]["webSave"]}} options
     */
    async function makeRecord(list, { webSave }) {
        const record = await makeTestRecordWithLines();
        patchWithCleanup(record.model.orm, { webSave });
        patchWithCleanup(record, {
            checkValidityLocked: () => true,
            getChangesLocked: () => ({ lines: list.getCommands() }),
            setEvalContext() {},
        });
        record._values.lines = list;
        record.applyChanges({ lines: list });
        record.dirty = true;
        return record;
    }

    test("save waits for an in-flight commands load before serializing", async () => {
        const def = new Deferred();
        const list = makeList({ loadRecords: () => def });

        list._trackCommandsPromise(list.applyCommandsLocked([[LINK, 42, false]]));
        expect(list._commandsPromise).not.toBe(null);

        /** @type {Record<string, unknown>} */
        let savedChanges = null;
        const rec = await makeRecord(list, {
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
        list.applyCommandsLocked([[LINK, 7, { id: 7, display_name: "Rec 7" }]]);

        const rec = await makeRecord(list, {
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

        list._trackCommandsPromise(list.applyCommandsLocked([[LINK, 42, false]]));
        await animationFrame();
        expect.verifyErrors([/replay boom/]);

        expect(list._cache.get(42).data).toEqual({ id: 42 });
        expect(list._replayFailed).toBe(true);

        failLoads = false;
        /** @type {any} */
        let savedChanges = null;
        const rec = await makeRecord(list, {
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

        const result = await save(rec, { reload: false });
        await list._commandsPromise;

        expect(result).toBe(true);
        expect(savedChanges.lines).toEqual([[LINK, 42, false]]);
        expect(list._cache.get(42).data.display_name).toBe("Rec 42");
        expect(list._replayFailed).toBe(false);
    });

    test("the barrier gives up after a bounded number of iterations", async () => {
        const list = makeList();
        list.applyCommandsLocked([[LINK, 7, { id: 7, display_name: "Rec 7" }]]);
        Object.defineProperty(list, "_commandsPromise", {
            get: () => Promise.resolve(),
            set: () => {},
        });

        const rec = await makeRecord(list, {
            webSave: async () => {
                expect.step("webSave");
                return [{ id: 1 }];
            },
        });

        /** @type {string[]} */
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
