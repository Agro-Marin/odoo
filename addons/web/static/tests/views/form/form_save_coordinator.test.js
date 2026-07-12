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

// ---------------------------------------------------------------------------
// Mock factory
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

describe("FormSaveCoordinator — initial state", () => {
    test("status defaults to 'clean'", () => {
        const { coordinator } = makeContext({ dirty: false });
        expect(coordinator.status).toBe("clean");
        expect(coordinator.lastError).toBe(null);
        expect(coordinator.isSaving).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// requestSave — checkDirty short-circuit
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// requestSave — happy path status transitions
// ---------------------------------------------------------------------------

describe("FormSaveCoordinator — requestSave (status transitions)", () => {
    test("transitions clean → saving → clean on success", async () => {
        // Capture status from INSIDE the save mock to observe the
        // in-flight value — the only post-``begin`` observation point
        // that doesn't race the awaits in ``requestSave``.
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
        // false means validation failed pre-RPC (no exception) — coordinator
        // settles to "dirty" (not "error") so the form can show invalid-fields UX.
        expect(coordinator.status).toBe("dirty");
    });
});

// ---------------------------------------------------------------------------
// requestSave — error modes
// ---------------------------------------------------------------------------

describe("FormSaveCoordinator — errorMode", () => {
    test("errorMode='dialog' invokes hooks.onSaveError on RPC failure", async () => {
        let onSaveErrorCalls = 0;
        let capturedError = null;
        let onErrorPassedToSave = null;
        // RPC-shaped: dialog path is reserved for errors carrying a server
        // payload (``error.data``); payload-less errors rethrow before the hook.
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
                    return false; // user chose "stay here"
                },
            },
        });

        const result = await coordinator.requestSave({ errorMode: "dialog" });

        expect(typeof onErrorPassedToSave).toBe("function");
        expect(onSaveErrorCalls).toBe(1);
        expect(capturedError).toBe(fakeError);
        // false from onSaveError means "block the caller's operation" —
        // coordinator returns that value.
        expect(result).toBe(false);
        // lastError is recorded even when dialog UX resolved it, so callers
        // like shouldExecuteAction can block menu actions on any save error.
        expect(coordinator.lastError).toBe(fakeError);
    });

    test("errorMode='dialog' rethrows payload-less errors instead of opening the dialog", async () => {
        // Connection errors carry no `.data`, which FormErrorDialog requires;
        // routing them to the dialog hook would TypeError. The coordinator
        // rethrows instead so status settles to "error" and navigation blocks.
        let dialogCalls = 0;
        const connectionError = new Error("Connection lost"); // no ``.data``
        const { coordinator } = makeContext({
            save: async ({ onError } = {}) =>
                // Mirror record_save.js: the error routes through the caller-provided
                // onError callback; a throw from it propagates out of record.save().
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

        expect(dialogCalls).toBe(0); // dialog never opened
        expect(result).toBe(false);
        expect(coordinator.status).toBe("error");
        expect(coordinator.lastError).toBe(connectionError); // not masked
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

// ---------------------------------------------------------------------------
// Multi-company recovery
// ---------------------------------------------------------------------------

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
        expect(dialogCalls).toBe(0); // dialog not shown — recovery succeeded
        expect(result).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// saveOverride
// ---------------------------------------------------------------------------

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
        // ``saveOverride`` receives the record proxied through OWL's
        // reactive() (the coordinator stores ``this.model`` and reads
        // ``this.model.root``, so the proxy wraps the access).  Compare
        // identity via a unique field rather than strict ``toBe`` on the
        // raw record reference.
        expect(overrideArgs.rec.save).toBe(record.save);
        // The params object passed to saveOverride includes the custom arg
        // so caller-side props.saveRecord has access to its own context.
        expect(overrideArgs.params.custom).toBe("arg");
    });

    test("a throwing saveOverride surfaces the error instead of returning false", async () => {
        // Regression: with the default dialog errorMode (beforeLeave's mode),
        // a saveOverride throw used to be swallowed into ``return false`` —
        // blocking navigation with zero user feedback. It must propagate so the
        // failure is visible (global error handler / caller try/catch).
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
        // The failure is recorded as the coordinator's lastError for diagnostics.
        expect(coordinator.lastError).toBe(boom);
        expect(coordinator.status).toBe("error");
    });
});

describe("FormSaveCoordinator — dirty surface", () => {
    test("reflects record.dirty (uncommitted user edits) independent of status", async () => {
        const { coordinator, record } = makeContext({ dirty: true });
        // The save-lifecycle status only tracks committed outcomes, so a
        // freshly-typed-into record is still "clean" by status while genuinely
        // dirty — the ``dirty`` getter exposes that truth.
        expect(coordinator.status).toBe("clean");
        expect(coordinator.dirty).toBe(true);
        record.dirty = false;
        expect(coordinator.dirty).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// requestUrgentSave
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// requestDiscard
// ---------------------------------------------------------------------------

describe("FormSaveCoordinator — requestDiscard", () => {
    test("calls record.discard and returns to clean", async () => {
        let discardCalls = 0;
        const { coordinator } = makeContext({
            discard: async () => {
                discardCalls++;
            },
        });
        // Force a non-clean status to verify the transition resets it.
        coordinator.status = "error";
        await coordinator.requestDiscard();
        expect(discardCalls).toBe(1);
        expect(coordinator.status).toBe("clean");
        expect(coordinator.lastError).toBe(null);
    });
});

// ---------------------------------------------------------------------------
// Transition guard
// ---------------------------------------------------------------------------

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
        expect(coordinator.status).toBe("clean"); // unchanged
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
            // and valid from saving
            coordinator.status = "saving";
            coordinator._transition(/** @type {any} */ (event));
            // landing state depends on event: ok→clean, recoverable→dirty, failed→error
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

// ---------------------------------------------------------------------------
// Concurrent saves — epoch invalidation
// ---------------------------------------------------------------------------

describe("FormSaveCoordinator — concurrent saves", () => {
    test("a second requestSave during an in-flight save supersedes the first's terminal", async () => {
        // Scenario: beforeLeave calls requestSave while a user-initiated save is
        // still in flight. Without epoch invalidation, the first save's stale
        // "ok" would fire after the second has settled to "clean", throwing
        // InvalidFormSaveTransitionError as an unhandled rejection.
        let resolveFirst, resolveSecond;
        const firstPromise = new Promise((r) => (resolveFirst = r));
        const secondPromise = new Promise((r) => (resolveSecond = r));
        let call = 0;
        let firstSaveEnteredAt = null;
        let secondSaveEnteredAt = null;
        // `save` is the only post-begin observation point that doesn't race the
        // awaits in requestSave; capture (status, epoch) as soon as each call lands.
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

        // Resolve first → its ``ok`` should NOT transition (stale epoch).
        resolveFirst(true);
        await firstSave;

        // Both calls have entered save() by now — both observed "saving".
        expect(firstSaveEnteredAt.status).toBe("saving");
        expect(secondSaveEnteredAt.status).toBe("saving");
        expect(secondSaveEnteredAt.epoch).toBe(firstSaveEnteredAt.epoch + 1);
        // First's "ok" was a no-op; state still in flight under epoch 2.
        expect(coordinator.status).toBe("saving");

        // Resolve second → its ``ok`` IS the current epoch → settles to clean.
        resolveSecond(true);
        await secondSave;
        expect(coordinator.status).toBe("clean");
    });

    test("a concurrent save's failure does not corrupt the winner's outcome", async () => {
        // Symmetric to the previous test: the FIRST save throws but the SECOND
        // (which has overtaken the epoch) succeeds. The first's "failed" transition
        // must be suppressed, or lastError would carry a stale failure across an
        // otherwise-successful save.
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
        // First's failure is suppressed by epoch invalidation.
        expect(coordinator.status).toBe("saving");
        expect(coordinator.lastError).toBe(null);

        resolveSecond(true);
        await secondSave;
        expect(coordinator.status).toBe("clean");
        expect(coordinator.lastError).toBe(null); // never poisoned by stale failure
    });

    test("requestDiscard mid-save invalidates the in-flight save's terminal", async () => {
        // The form controller may discard mid-save (e.g. multi-company recovery
        // chose "discard"). requestDiscard bumps the epoch so the in-flight save's
        // "ok" becomes a no-op instead of clobbering post-discard "clean".
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
        // Pump microtasks so the save mock has had a chance to run.
        await Promise.resolve();
        await Promise.resolve();
        expect(statusInsideSave).toBe("saving");

        await coordinator.requestDiscard();
        expect(coordinator.status).toBe("clean");

        // The save now resolves — its terminal should be silently dropped.
        resolveSave(true);
        await savePending;
        expect(coordinator.status).toBe("clean"); // discard's settlement preserved
    });

    test("requestSave mid-discard supersedes the discard's settlement", async () => {
        // Mirror of the previous test: Discard is held up by the model mutex while
        // the user clicks Save. Save's "begin" claims a newer epoch, so the
        // discard's stale "discard" transition must be a no-op — applying it would
        // leave the in-flight save's terminal transition invalid from "clean".
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
        // Pump microtasks so both calls are in flight.
        await Promise.resolve();
        await Promise.resolve();
        expect(discardCalls).toBe(1);
        expect(coordinator.status).toBe("saving"); // save's begin applied

        // The discard resolves first — its stale settlement is a no-op.
        resolveDiscard();
        await discardPending;
        expect(coordinator.status).toBe("saving"); // save still owns the state

        // The save's terminal owns the current epoch and settles cleanly.
        resolveSave(true);
        const saved = await savePending;
        expect(saved).toBe(true);
        expect(coordinator.status).toBe("clean");
    });
});
