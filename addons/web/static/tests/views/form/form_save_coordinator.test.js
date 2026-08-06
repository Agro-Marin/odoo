// @ts-check

/**
 * Pure unit tests for FormSaveCoordinator: the state machine and dispatch
 * logic centralizing the form controller's 9 save-related entry points.
 * Uses plain mock objects (delegation pattern, mirrors record_save.test.js)
 * — no component mount.
 *
 * Module under test: views/form/form_save_coordinator.js
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    FormSaveCoordinator,
    InvalidFormSaveTransitionError,
} from "@web/views/form/form_save_coordinator";

/**
 * Builds the minimal record + model + hooks shape required by the
 * coordinator.  Each option lets a test substitute a specific behavior
 * without needing to wire a full RelationalRecord.
 *
 * @param {Object} [opts]
 * @param {boolean} [opts.dirty=true]
 * @param {Function} [opts.save]            stub for ``record.save``
 * @param {Function} [opts.urgentSave]      stub for ``record.urgentSave``
 * @param {Function} [opts.discard]         stub for ``record.discard``
 * @param {Object}   [opts.hooks]           override individual hooks
 */
function makeContext({
    dirty = true,
    save,
    urgentSave,
    discard,
    hooks: hookOverrides,
} = {}) {
    const record = {
        dirty,
        async isDirty() {
            return dirty;
        },
        save: save ?? (async () => true),
        urgentSave: urgentSave ?? (async () => true),
        discard: discard ?? (async () => undefined),
    };
    const model = { root: record };
    const hooks = {
        onSaveError: async () => true,
        onUrgentSaveFailed: () => undefined,
        recoverFromSaveError: () => false,
        ...hookOverrides,
    };
    const coordinator = new FormSaveCoordinator(model, hooks);
    return { coordinator, record, model, hooks };
}

describe("FormSaveCoordinator — initial state", () => {
    test("status defaults to 'clean'", () => {
        const { coordinator } = makeContext({ dirty: false });
        expect(coordinator.status).toBe("clean");
        expect(coordinator.lastError).toBe(null);
        expect(coordinator.isSaving).toBe(false);
    });
});

describe("FormSaveCoordinator — requestSave (checkDirty)", () => {
    test("returns true without calling record.save when checkDirty=true and not dirty", async () => {
        let saveCalled = false;
        const { coordinator } = makeContext({
            dirty: false,
            save: async () => {
                saveCalled = true;
                return true;
            },
        });
        const result = await coordinator.requestSave({ checkDirty: true });
        expect(result).toBe(true);
        expect(saveCalled).toBe(false);
        expect(coordinator.status).toBe("clean");
    });

    test("calls record.save when checkDirty=true and record is dirty", async () => {
        let saveCalled = false;
        const { coordinator } = makeContext({
            dirty: true,
            save: async () => {
                saveCalled = true;
                return true;
            },
        });
        const result = await coordinator.requestSave({ checkDirty: true });
        expect(result).toBe(true);
        expect(saveCalled).toBe(true);
    });

    test("calls record.save when checkDirty is omitted (default)", async () => {
        let saveCalled = false;
        const { coordinator } = makeContext({
            dirty: false,
            save: async () => {
                saveCalled = true;
                return true;
            },
        });
        await coordinator.requestSave();
        expect(saveCalled).toBe(true);
    });
});

describe("FormSaveCoordinator — requestSave (status transitions)", () => {
    test("transitions clean → saving → clean on success", async () => {
        let statusDuringSave = null;
        const { coordinator } = makeContext({
            save: async () => {
                statusDuringSave = coordinator.status;
                return true;
            },
        });
        expect(coordinator.status).toBe("clean");
        const result = await coordinator.requestSave();
        expect(statusDuringSave).toBe("saving");
        expect(result).toBe(true);
        expect(coordinator.status).toBe("clean");
        expect(coordinator.isSaving).toBe(false);
    });

    test("returns the value record.save returned (false short-circuits)", async () => {
        const { coordinator } = makeContext({ save: async () => false });
        const result = await coordinator.requestSave();
        expect(result).toBe(false);
        expect(coordinator.status).toBe("dirty");
    });
});

describe("FormSaveCoordinator — errorMode", () => {
    test("errorMode='dialog' invokes hooks.onSaveError on RPC failure", async () => {
        let onSaveErrorCalls = 0;
        let capturedError = null;
        let onErrorPassedToSave = null;
        const fakeError = Object.assign(new Error("rpc-failed"), {
            data: { message: "rpc-failed" },
        });
        const { coordinator } = makeContext({
            save: async ({ onError } = {}) => {
                onErrorPassedToSave = onError;
                if (!onError) {
                    throw fakeError;
                }
                return await onError(fakeError, {
                    discard: () => {},
                    retry: () => true,
                });
            },
            hooks: {
                onSaveError: async (error, _callbacks) => {
                    onSaveErrorCalls++;
                    capturedError = error;
                    return false;
                },
            },
        });

        const result = await coordinator.requestSave({ errorMode: "dialog" });

        expect(typeof onErrorPassedToSave).toBe("function");
        expect(onSaveErrorCalls).toBe(1);
        expect(capturedError).toBe(fakeError);
        expect(result).toBe(false);
        expect(coordinator.lastError).toBe(fakeError);
    });

    test("errorMode='dialog' rethrows payload-less errors instead of opening the dialog", async () => {
        let dialogCalls = 0;
        const connectionError = new Error("Connection lost");
        const { coordinator } = makeContext({
            save: async ({ onError } = {}) =>
                await onError(connectionError, {
                    discard: () => {},
                    retry: () => true,
                }),
            hooks: {
                onSaveError: async () => {
                    dialogCalls++;
                    return true;
                },
            },
        });

        const result = await coordinator.requestSave({ errorMode: "dialog" });

        expect(dialogCalls).toBe(0);
        expect(result).toBe(false);
        expect(coordinator.status).toBe("error");
        expect(coordinator.lastError).toBe(connectionError);
    });

    test("errorMode='rethrow' propagates the error to the caller", async () => {
        const fakeError = new Error("rpc-failed");
        const { coordinator } = makeContext({
            save: async ({ onError } = {}) => {
                if (onError) {
                    return await onError(fakeError, {
                        discard: () => {},
                        retry: () => false,
                    });
                }
                throw fakeError;
            },
        });

        let caught = null;
        try {
            await coordinator.requestSave({ errorMode: "rethrow" });
        } catch (e) {
            caught = e;
        }
        expect(caught).toBe(fakeError);
        expect(coordinator.status).toBe("error");
        expect(coordinator.lastError).toBe(fakeError);
    });

    test("errorMode='silent' swallows the error and returns false", async () => {
        const fakeError = new Error("rpc-failed");
        const { coordinator } = makeContext({
            save: async () => {
                throw fakeError;
            },
        });
        const result = await coordinator.requestSave({ errorMode: "silent" });
        expect(result).toBe(false);
        expect(coordinator.status).toBe("error");
        expect(coordinator.lastError).toBe(fakeError);
    });
});

describe("FormSaveCoordinator — multi-company recovery", () => {
    test("recoverFromSaveError shortcuts the dialog UX with retry()", async () => {
        let recoverCalls = 0;
        let retryCalls = 0;
        let dialogCalls = 0;
        const accessError = new Error("AccessError with suggested_company");
        const { coordinator } = makeContext({
            save: async ({ onError } = {}) => {
                if (!onError) {
                    throw accessError;
                }
                return await onError(accessError, {
                    discard: () => {},
                    retry: () => {
                        retryCalls++;
                        return true;
                    },
                });
            },
            hooks: {
                recoverFromSaveError: () => {
                    recoverCalls++;
                    return true;
                },
                onSaveError: async () => {
                    dialogCalls++;
                    return true;
                },
            },
        });

        const result = await coordinator.requestSave({ errorMode: "dialog" });
        expect(recoverCalls).toBe(1);
        expect(retryCalls).toBe(1);
        expect(dialogCalls).toBe(0);
        expect(result).toBe(true);
    });
});

describe("FormSaveCoordinator — saveOverride", () => {
    test("invokes saveOverride instead of record.save when provided", async () => {
        let recordSaveCalls = 0;
        let overrideCalls = 0;
        let overrideArgs = null;
        const { coordinator, record } = makeContext({
            save: async () => {
                recordSaveCalls++;
                return true;
            },
        });
        const saveOverride = async (rec, params) => {
            overrideCalls++;
            overrideArgs = { rec, params };
            return true;
        };
        await coordinator.requestSave({ saveOverride, params: { custom: "arg" } });
        expect(recordSaveCalls).toBe(0);
        expect(overrideCalls).toBe(1);
        expect(overrideArgs.rec.save).toBe(record.save);
        expect(overrideArgs.params.custom).toBe("arg");
    });

    test("a throwing saveOverride surfaces the error instead of returning false", async () => {
        const boom = new Error("embedder save failed");
        const { coordinator } = makeContext();
        const saveOverride = async () => {
            throw boom;
        };
        let caught = null;
        try {
            await coordinator.requestSave({ saveOverride });
        } catch (e) {
            caught = e;
        }
        expect(caught).toBe(boom);
        expect(coordinator.lastError).toBe(boom);
        expect(coordinator.status).toBe("error");
    });
});

describe("FormSaveCoordinator — requestUrgentSave", () => {
    test("calls record.urgentSave and returns its result", async () => {
        let urgentCalls = 0;
        const { coordinator } = makeContext({
            urgentSave: async () => {
                urgentCalls++;
                return true;
            },
        });
        const result = await coordinator.requestUrgentSave();
        expect(urgentCalls).toBe(1);
        expect(result).toBe(true);
        expect(coordinator.status).toBe("clean");
    });

    test("requestUrgentSave during an in-flight save defers settlement to that save", async () => {
        let rejectSave;
        const savePromise = new Promise((_, reject) => (rejectSave = reject));
        let urgentCalls = 0;
        const lateFailure = new Error("late-failure");
        const { coordinator } = makeContext({
            save: () => savePromise,
            urgentSave: async () => {
                urgentCalls++;
                return true;
            },
        });

        const savePending = coordinator.requestSave({ errorMode: "silent" });
        await Promise.resolve();
        expect(coordinator.status).toBe("saving");
        const epochBefore = coordinator._saveEpoch;

        const succeeded = await coordinator.requestUrgentSave();
        expect(succeeded).toBe(true);
        expect(urgentCalls).toBe(1);
        expect(coordinator._saveEpoch).toBe(epochBefore);
        expect(coordinator.status).toBe("saving");

        rejectSave(lateFailure);
        expect(await savePending).toBe(false);
        expect(coordinator.status).toBe("error");
        expect(coordinator.lastError).toBe(lateFailure);
    });

    test("a failing urgent save during an in-flight save fires the hook without touching status", async () => {
        let resolveSave;
        const savePromise = new Promise((r) => (resolveSave = r));
        let failedHookCalls = 0;
        const { coordinator } = makeContext({
            save: () => savePromise,
            urgentSave: async () => false,
            hooks: {
                onUrgentSaveFailed: () => {
                    failedHookCalls++;
                },
            },
        });

        const savePending = coordinator.requestSave();
        await Promise.resolve();
        expect(coordinator.status).toBe("saving");

        const succeeded = await coordinator.requestUrgentSave();
        expect(succeeded).toBe(false);
        expect(failedHookCalls).toBe(1);
        expect(coordinator.status).toBe("saving");

        resolveSave(true);
        await savePending;
        expect(coordinator.status).toBe("clean");
    });

    test("invokes onUrgentSaveFailed hook when urgentSave returns false", async () => {
        let failedHookCalls = 0;
        const { coordinator } = makeContext({
            urgentSave: async () => false,
            hooks: {
                onUrgentSaveFailed: () => {
                    failedHookCalls++;
                },
            },
        });
        const result = await coordinator.requestUrgentSave();
        expect(result).toBe(false);
        expect(failedHookCalls).toBe(1);
        expect(coordinator.status).toBe("error");
    });
});

describe("FormSaveCoordinator — requestDiscard", () => {
    test("calls record.discard and returns to clean", async () => {
        let discardCalls = 0;
        const { coordinator } = makeContext({
            discard: async () => {
                discardCalls++;
            },
        });
        coordinator.status = "error";
        await coordinator.requestDiscard();
        expect(discardCalls).toBe(1);
        expect(coordinator.status).toBe("clean");
        expect(coordinator.lastError).toBe(null);
    });
});

describe("FormSaveCoordinator — transition guard", () => {
    test("_transition('ok') from 'clean' throws InvalidFormSaveTransitionError", () => {
        const { coordinator } = makeContext({ dirty: false });
        expect(coordinator.status).toBe("clean");
        let caught = null;
        try {
            coordinator._transition("ok");
        } catch (e) {
            caught = e;
        }
        expect(caught).toBeInstanceOf(InvalidFormSaveTransitionError);
        expect(caught.from).toBe("clean");
        expect(caught.event).toBe("ok");
        expect(coordinator.status).toBe("clean");
    });

    test("_transition('failed') from 'dirty' throws", () => {
        const { coordinator } = makeContext();
        coordinator.status = "dirty";
        let caught = null;
        try {
            coordinator._transition("failed");
        } catch (e) {
            caught = e;
        }
        expect(caught).toBeInstanceOf(InvalidFormSaveTransitionError);
        expect(caught.from).toBe("dirty");
        expect(caught.event).toBe("failed");
    });

    test("_transition('recoverable') from 'error' throws", () => {
        const { coordinator } = makeContext();
        coordinator.status = "error";
        let caught = null;
        try {
            coordinator._transition("recoverable");
        } catch (e) {
            caught = e;
        }
        expect(caught).toBeInstanceOf(InvalidFormSaveTransitionError);
        expect(caught.from).toBe("error");
        expect(caught.event).toBe("recoverable");
    });

    test("_transition('discard') is valid from every state", () => {
        const { coordinator } = makeContext();
        for (const from of ["clean", "dirty", "saving", "error"]) {
            coordinator.status = /** @type {any} */ (from);
            coordinator._transition("discard");
            expect(coordinator.status).toBe("clean");
        }
    });

    test("_transition('begin') is valid from every state and lands on 'saving'", () => {
        const { coordinator } = makeContext();
        for (const from of ["clean", "dirty", "saving", "error"]) {
            coordinator.status = /** @type {any} */ (from);
            coordinator._transition("begin");
            expect(coordinator.status).toBe("saving");
        }
    });

    test("save-completion outcomes (ok/recoverable/failed) are only valid from 'saving'", () => {
        const { coordinator } = makeContext();
        for (const event of ["ok", "recoverable", "failed"]) {
            for (const from of ["clean", "dirty", "error"]) {
                coordinator.status = /** @type {any} */ (from);
                let caught = null;
                try {
                    coordinator._transition(/** @type {any} */ (event));
                } catch (e) {
                    caught = e;
                }
                expect(caught).toBeInstanceOf(InvalidFormSaveTransitionError);
            }
            coordinator.status = "saving";
            coordinator._transition(/** @type {any} */ (event));
        }
    });

    test("InvalidFormSaveTransitionError has descriptive message", () => {
        const err = new InvalidFormSaveTransitionError("clean", "ok");
        expect(err.name).toBe("InvalidFormSaveTransitionError");
        expect(err.message).toBe(
            "FormSaveCoordinator: invalid transition 'ok' from state 'clean'",
        );
        expect(err.from).toBe("clean");
        expect(err.event).toBe("ok");
    });
});

describe("FormSaveCoordinator — concurrent saves", () => {
    test("a second requestSave during an in-flight save supersedes the first's terminal", async () => {
        let resolveFirst, resolveSecond;
        const firstPromise = new Promise((r) => (resolveFirst = r));
        const secondPromise = new Promise((r) => (resolveSecond = r));
        let call = 0;
        let firstSaveEnteredAt = null;
        let secondSaveEnteredAt = null;
        const { coordinator } = makeContext({
            save: () => {
                const which = ++call;
                if (which === 1) {
                    firstSaveEnteredAt = {
                        status: coordinator.status,
                        epoch: coordinator._saveEpoch,
                    };
                    return firstPromise;
                }
                secondSaveEnteredAt = {
                    status: coordinator.status,
                    epoch: coordinator._saveEpoch,
                };
                return secondPromise;
            },
        });

        const firstSave = coordinator.requestSave();
        const secondSave = coordinator.requestSave();

        resolveFirst(true);
        await firstSave;

        expect(firstSaveEnteredAt.status).toBe("saving");
        expect(secondSaveEnteredAt.status).toBe("saving");
        expect(secondSaveEnteredAt.epoch).toBe(firstSaveEnteredAt.epoch + 1);
        expect(coordinator.status).toBe("saving");

        resolveSecond(true);
        await secondSave;
        expect(coordinator.status).toBe("clean");
    });

    test("a concurrent save's failure does not corrupt the winner's outcome", async () => {
        let resolveSecond;
        const secondPromise = new Promise((r) => (resolveSecond = r));
        let call = 0;
        const fakeError = new Error("stale-failure");
        const { coordinator } = makeContext({
            save: () => (++call === 1 ? Promise.reject(fakeError) : secondPromise),
        });

        const firstSave = coordinator.requestSave({ errorMode: "silent" });
        const secondSave = coordinator.requestSave();

        await firstSave;
        expect(coordinator.status).toBe("saving");
        expect(coordinator.lastError).toBe(null);

        resolveSecond(true);
        await secondSave;
        expect(coordinator.status).toBe("clean");
        expect(coordinator.lastError).toBe(null);
    });

    test("a superseded save's dialog-mode error does not open the error dialog", async () => {
        let resolveSecond;
        const secondPromise = new Promise((r) => (resolveSecond = r));
        let triggerFirstFailure;
        const firstFailure = new Promise((r) => (triggerFirstFailure = r));
        let onSaveErrorCalls = 0;
        let call = 0;
        const staleError = Object.assign(new Error("stale-rpc-failure"), {
            data: { message: "stale-rpc-failure" },
        });
        const { coordinator } = makeContext({
            save: ({ onError } = {}) => {
                if (++call === 1) {
                    return firstFailure.then(() =>
                        onError(staleError, {
                            discard: () => {},
                            retry: () => true,
                        }),
                    );
                }
                return secondPromise;
            },
            hooks: {
                onSaveError: async () => {
                    onSaveErrorCalls++;
                    return true;
                },
            },
        });

        const firstSave = coordinator.requestSave();
        const secondSave = coordinator.requestSave();

        triggerFirstFailure();
        const firstResult = await firstSave;
        expect(onSaveErrorCalls).toBe(0);
        expect(firstResult).toBe(false);
        expect(coordinator.lastError).toBe(null);
        expect(coordinator.status).toBe("saving");

        resolveSecond(true);
        await secondSave;
        expect(coordinator.status).toBe("clean");
    });

    test("requestDiscard mid-save invalidates the in-flight save's terminal", async () => {
        let resolveSave;
        const savePromise = new Promise((r) => (resolveSave = r));
        let statusInsideSave = null;
        const { coordinator } = makeContext({
            save: () => {
                statusInsideSave = coordinator.status;
                return savePromise;
            },
        });

        const savePending = coordinator.requestSave();
        await Promise.resolve();
        await Promise.resolve();
        expect(statusInsideSave).toBe("saving");

        await coordinator.requestDiscard();
        expect(coordinator.status).toBe("clean");

        resolveSave(true);
        await savePending;
        expect(coordinator.status).toBe("clean");
    });

    test("requestSave mid-discard supersedes the discard's settlement", async () => {
        let resolveDiscard, resolveSave;
        const discardPromise = new Promise((r) => (resolveDiscard = r));
        const savePromise = new Promise((r) => (resolveSave = r));
        let discardCalls = 0;
        const { coordinator } = makeContext({
            discard: () => {
                discardCalls++;
                return discardPromise;
            },
            save: () => savePromise,
        });
        coordinator.status = "dirty";

        const discardPending = coordinator.requestDiscard();
        const savePending = coordinator.requestSave();
        await Promise.resolve();
        await Promise.resolve();
        expect(discardCalls).toBe(1);
        expect(coordinator.status).toBe("saving");

        resolveDiscard();
        await discardPending;
        expect(coordinator.status).toBe("saving");

        resolveSave(true);
        const saved = await savePending;
        expect(saved).toBe(true);
        expect(coordinator.status).toBe("clean");
    });
});

describe("FormSaveCoordinator — lastError lifecycle", () => {
    test("a discard-resolved save settles 'ok' and clears lastError", async () => {
        const handled = Object.assign(new Error("server said no"), {
            data: { message: "server said no" },
        });
        // Mirrors record_save.js: `save` RETURNS the onError result, and the
        // dialog hook resolves truthy when the user picks "Discard changes".
        // Discarding resolves the save (the record is clean again), so the
        // queued action must proceed: a retained lastError would make
        // shouldExecuteAction silently drop it.
        const { coordinator } = makeContext({
            save: (opts) => opts.onError(handled, { discard() {}, retry() {} }),
        });

        const saved = await coordinator.requestSave({ errorMode: "dialog" });

        expect(saved).toBe(true);
        expect(coordinator.status).toBe("clean");
        expect(coordinator.lastError).toBe(null);
    });

    test("an unresolved failure leaves lastError set", async () => {
        const boom = new Error("boom");
        const { coordinator } = makeContext({
            save: async () => {
                throw boom;
            },
        });

        const saved = await coordinator.requestSave({ errorMode: "dialog" });

        expect(saved).toBe(false);
        expect(coordinator.status).toBe("error");
        expect(coordinator.lastError).toBe(boom);
    });

    test("requestSave clears a previous error on entry", async () => {
        const { coordinator } = makeContext();
        coordinator.lastError = new Error("stale");
        await coordinator.requestSave();
        expect(coordinator.lastError).toBe(null);
    });
});

describe("FormSaveCoordinator — re-entrant requestUrgentSave", () => {
    test("a throw is surfaced instead of vanishing", async () => {
        const beaconError = new Error("beacon exploded");
        let urgentFailed = 0;
        const { coordinator } = makeContext({
            urgentSave: async () => {
                throw beaconError;
            },
            hooks: { onUrgentSaveFailed: () => urgentFailed++ },
        });
        coordinator.status = "saving"; // a save is already in flight

        await expect(coordinator.requestUrgentSave()).rejects.toThrow(
            "beacon exploded",
        );

        // The re-entrant call must NOT claim a terminal (it does not own the
        // epoch), but it must report: previously the caller got nothing at all
        // and FormStatusIndicator kept spinning on `isSaving`.
        expect(coordinator.lastError).toBe(beaconError);
        expect(urgentFailed).toBe(1);
    });

    test("a re-entrant failure (no throw) still notifies once", async () => {
        let urgentFailed = 0;
        const { coordinator } = makeContext({
            urgentSave: async () => false,
            hooks: { onUrgentSaveFailed: () => urgentFailed++ },
        });
        coordinator.status = "saving";

        expect(await coordinator.requestUrgentSave()).toBe(false);
        expect(urgentFailed).toBe(1);
        expect(coordinator.status).toBe("saving");
    });
});
