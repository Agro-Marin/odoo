// @ts-check

/**
 * Pure unit tests for record_lifecycle.js — archive(), unarchive(), deleteRecord(),
 * duplicateRecord() extracted from RelationalRecord (see
 * workspaces/workspace-LMMG/brainstorms/2026-05-23-web-model-layer-decomposition.md).
 *
 * Mutex serialization (Invariant I4) is enforced by the class-method wrappers in
 * record.js, not by these helpers — tests call the helpers directly with a
 * hand-rolled mock record, bypassing the mutex on purpose: the helpers' contract
 * is "assume you run under the mutex; do not re-enter it".
 */

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import {
    archive,
    deleteRecord,
    duplicateRecord,
    unarchive,
} from "@web/model/relational_model/record_lifecycle";

// Mock factory

/**
 * Builds the minimal record mock shape required by the lifecycle helpers.
 *
 * Defaults exercise the happy paths:
 *  - resId=1, resIds=[1] (single-record case)
 *  - context={}, model.orm methods return success
 *  - hooks.ui.onDisplayArchiveAction returns whatever the caller passes
 *
 * @param {Object} [opts]
 * @param {number|false} [opts.resId=1]
 * @param {number[]} [opts.resIds=[1]]
 * @param {Function|null} [opts.unlink]
 * @param {Function|null} [opts.call] - ORM `call` stub (action_archive,
 *   action_unarchive, copy)
 * @param {Function|null} [opts.load] - model.load stub
 * @param {Function|null} [opts.onDisplayArchiveAction] - ui hook stub
 * @returns {Object}
 */
function makeRecord({
    resId = 1,
    resIds = [1],
    unlink = null,
    call = null,
    load = null,
    onDisplayArchiveAction = null,
} = {}) {
    /** @type {any} */
    const record = {
        resId,
        resIds,
        resModel: "res.partner",
        context: { uid: 1 },
        config: { resId, resIds, context: { uid: 1 } },
        // Three-layer state (Invariant I7 — see plan §3). deleteRecord
        // resets _values / _textValues / data when the deleted record
        // was the last in resIds.
        _values: markRaw({ id: resId, name: "Test" }),
        _textValues: markRaw({ name: "Test" }),
        _changes: markRaw({}),
        data: { id: resId, name: "Test" },
        // Protected methods deleteRecord calls when resetting state.
        _parseServerValues(defaults) {
            return { ...defaults };
        },
        _getDefaultValues() {
            return { id: false, name: false };
        },
        _clearChanges() {
            // Invariant I3 — pair _changes={} with dirty=false atomically.
            this._changes = markRaw({});
            this.dirty = false;
        },
        _setEvalContext() {},
        _load: async () => {},
        model: {
            orm: {
                unlink: unlink ?? (async () => true),
                call:
                    call ??
                    (async (model, method) => {
                        if (method === "copy") {
                            return [resId * 10]; // synthetic new id
                        }
                        // action_archive / action_unarchive
                        return false; // no follow-up action
                    }),
            },
            load: load ?? (async () => {}),
            _patchConfig: () => {},
            hooks: {
                ui: {
                    onDisplayArchiveAction:
                        onDisplayArchiveAction ?? ((_action, reload) => reload()),
                },
                lifecycle: {},
            },
        },
    };
    return record;
}

// archive() / unarchive() — ORM method routing

describe("archive / unarchive ORM method routing", () => {
    test("archive() calls orm.call with 'action_archive'", async () => {
        let calledMethod = null;
        const rec = makeRecord({
            call: async (_model, method) => {
                calledMethod = method;
                return false;
            },
        });
        await archive(rec);
        expect(calledMethod).toBe("action_archive");
    });

    test("unarchive() calls orm.call with 'action_unarchive'", async () => {
        let calledMethod = null;
        const rec = makeRecord({
            call: async (_model, method) => {
                calledMethod = method;
                return false;
            },
        });
        await unarchive(rec);
        expect(calledMethod).toBe("action_unarchive");
    });

    test("archive() passes [[resId]] as args and {context} as kwargs", async () => {
        let capturedArgs = null;
        let capturedKwargs = null;
        const rec = makeRecord({
            resId: 42,
            call: async (_model, _method, args, kwargs) => {
                capturedArgs = args;
                capturedKwargs = kwargs;
                return false;
            },
        });
        rec.context = { lang: "en_US", uid: 7 };
        await archive(rec);
        expect(capturedArgs).toEqual([[42]]);
        expect(capturedKwargs).toEqual({ context: { lang: "en_US", uid: 7 } });
    });
});

// archive() — hook routing

describe("archive hook routing", () => {
    test("server action result is forwarded to hooks.ui.onDisplayArchiveAction", async () => {
        const serverAction = { type: "ir.actions.act_window", res_id: 99 };
        let receivedAction = null;
        const rec = makeRecord({
            call: async () => serverAction,
            onDisplayArchiveAction: (action) => {
                receivedAction = action;
                return "hook-return-value";
            },
        });
        const result = await archive(rec);
        expect(receivedAction).toBe(serverAction);
        expect(result).toBe("hook-return-value");
    });

    test("the reload callback passed to the hook invokes record._load", async () => {
        let loadCalled = false;
        const rec = makeRecord({
            onDisplayArchiveAction: (_action, reload) => reload(),
        });
        rec._load = async () => {
            loadCalled = true;
        };
        await archive(rec);
        expect(loadCalled).toBe(true);
    });
});

// deleteRecord() — veto + navigation + state-reset paths

describe("deleteRecord veto", () => {
    test("returns false when orm.unlink returns falsy and does not mutate state", async () => {
        let loadCalled = false;
        let clearChangesCalled = false;
        const rec = makeRecord({
            unlink: async () => false,
            load: async () => {
                loadCalled = true;
            },
        });
        rec._clearChanges = () => {
            clearChangesCalled = true;
        };
        const result = await deleteRecord(rec);
        expect(result).toBe(false);
        expect(loadCalled).toBe(false);
        expect(clearChangesCalled).toBe(false);
    });
});

describe("deleteRecord navigation", () => {
    test("with non-last position, navigates to the next record in resIds", async () => {
        let loadArgs = null;
        const rec = makeRecord({
            resId: 5,
            resIds: [3, 5, 7, 9],
            load: async (args) => {
                loadArgs = args;
            },
        });
        await deleteRecord(rec);
        // After deleting 5, resIds becomes [3, 7, 9]; index was 1, so we
        // navigate to position 1 of the new list — which is 7.
        expect(loadArgs).toEqual({ resId: 7, resIds: [3, 7, 9] });
    });

    test("with last position, navigates to the previous record in resIds", async () => {
        let loadArgs = null;
        const rec = makeRecord({
            resId: 9,
            resIds: [3, 5, 7, 9],
            load: async (args) => {
                loadArgs = args;
            },
        });
        await deleteRecord(rec);
        // After deleting 9, resIds becomes [3, 5, 7]; index was 3, clamped to
        // length-1=2, so we navigate to 7.
        expect(loadArgs).toEqual({ resId: 7, resIds: [3, 5, 7] });
    });
});

describe("deleteRecord state reset (last record)", () => {
    test("when resIds becomes empty, resets _values / _textValues / _changes / data", async () => {
        let loadCalled = false;
        let patchConfigArgs = null;
        let setEvalContextCalled = false;
        const rec = makeRecord({
            resId: 1,
            resIds: [1],
            load: async () => {
                loadCalled = true;
            },
        });
        rec.model._patchConfig = (_config, patch) => {
            patchConfigArgs = { patch };
        };
        rec._setEvalContext = () => {
            setEvalContextCalled = true;
        };
        await deleteRecord(rec);
        // Navigation MUST NOT occur — instead local state is reset in place.
        expect(loadCalled).toBe(false);
        // _patchConfig (sync, no reload by construction) must clear the resId.
        expect(patchConfigArgs).toEqual({
            patch: { resId: false },
        });
        // State reset:
        expect(rec._textValues).toEqual({});
        // _values is re-derived from _getDefaultValues() through _parseServerValues
        expect(rec._values).toEqual({ id: false, name: false });
        // data is rebuilt from _values
        expect(rec.data).toEqual({ id: false, name: false });
        // dirty was reset by _clearChanges (Invariant I3)
        expect(rec.dirty).toBe(false);
        // Eval context refreshed
        expect(setEvalContextCalled).toBe(true);
    });
});

// duplicateRecord() — copy + resIds insertion + navigation

describe("duplicateRecord", () => {
    test("calls orm.call with 'copy' passing [[resId]]", async () => {
        let copyArgs = null;
        const rec = makeRecord({
            resId: 7,
            call: async (_model, method, args) => {
                if (method === "copy") {
                    copyArgs = args;
                    return [42];
                }
                return false;
            },
        });
        await duplicateRecord(rec);
        expect(copyArgs).toEqual([[7]]);
    });

    test("inserts the new resId immediately AFTER the source in resIds", async () => {
        let loadArgs = null;
        const rec = makeRecord({
            resId: 5,
            resIds: [3, 5, 7, 9],
            call: async (_model, method) => {
                if (method === "copy") {
                    return [42];
                }
                return false;
            },
            load: async (args) => {
                loadArgs = args;
            },
        });
        await duplicateRecord(rec);
        // 5 is at index 1 → new id 42 inserted at index 2 → [3, 5, 42, 7, 9]
        expect(loadArgs).toEqual({
            resId: 42,
            resIds: [3, 5, 42, 7, 9],
            mode: "edit",
        });
    });

    test("navigation uses mode 'edit' so the duplicate is immediately editable", async () => {
        let loadMode = null;
        const rec = makeRecord({
            call: async (_model, method) => {
                if (method === "copy") {
                    return [99];
                }
                return false;
            },
            load: async (args) => {
                loadMode = args.mode;
            },
        });
        await duplicateRecord(rec);
        expect(loadMode).toBe("edit");
    });

    test("copy passes {context} as kwargs", async () => {
        let copyKwargs = null;
        const rec = makeRecord({
            call: async (_model, method, _args, kwargs) => {
                if (method === "copy") {
                    copyKwargs = kwargs;
                    return [99];
                }
                return false;
            },
        });
        rec.context = { default_user_id: 3, lang: "fr_FR" };
        await duplicateRecord(rec);
        expect(copyKwargs).toEqual({
            context: { default_user_id: 3, lang: "fr_FR" },
        });
    });
});
