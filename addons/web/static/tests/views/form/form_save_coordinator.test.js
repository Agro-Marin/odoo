// @ts-check

/**
 * Pure unit tests for FormSaveCoordinator.
 *
 * Tests the state machine and dispatch logic that centralizes the form
 * controller's 9 save-related entry points.  Uses plain mock objects
 * (delegation pattern, mirrors record_save.test.js) — no component mount.
 *
 * Coverage:
 *   - Initial status is ``clean``.
 *   - ``requestSave`` clean+checkDirty short-circuits without invoking
 *     ``record.save``.
 *   - ``requestSave`` dirty path transitions ``clean → saving → clean``
 *     when the save succeeds, or ``→ error`` when it fails.
 *   - ``errorMode`` flag selects between dialog UX, re-throw, and silent
 *     swallowing.
 *   - ``saveOverride`` (used by ``props.saveRecord`` delegation) is
 *     invoked instead of ``record.save`` when supplied.
 *   - ``requestUrgentSave`` uses the urgent (sendBeacon) path on the
 *     record and surfaces the ``onUrgentSaveFailed`` hook when sendBeacon
 *     fails.
 *   - ``requestDiscard`` calls ``record.discard`` and returns to clean.
 *   - Multi-company recovery is invoked transparently before the dialog UX.
 *   - ``onWillSave`` returning false aborts the save before the RPC fires.
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
        onWillSave: async () => undefined,
        onSaved: async () => undefined,
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
        // in-flight value.  Reading ``coordinator.status`` synchronously
        // after kicking off ``requestSave()`` is race-y because
        // ``requestSave`` has an ``await onWillSave?()`` step before the
        // ``status = "saving"`` assignment — by the time the test code
        // runs synchronously, only the prefix-up-to-first-await has
        // executed and status is still ``"clean"``.
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
        // false from record.save means validation failed pre-RPC; coordinator
        // returns to clean (or stays dirty) — NOT error, since no exception
        // was raised.  Settled on "dirty" so the form can show invalid-fields
        // UX without flagging a hard error.
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
        const fakeError = new Error("rpc-failed");
        const { coordinator } = makeContext({
            save: async ({ onError } = {}) => {
                onErrorPassedToSave = onError;
                if (!onError) throw fakeError;
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
        // lastError is recorded even when the dialog UX resolved it,
        // so callers like shouldExecuteAction can block menu actions
        // on any save error regardless of dialog resolution.
        expect(coordinator.lastError).toBe(fakeError);
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
                if (!onError) throw accessError;
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
// onWillSave gate
// ---------------------------------------------------------------------------

describe("FormSaveCoordinator — onWillSave gate", () => {
    test("aborts when onWillSave returns false (no record.save call)", async () => {
        let saveCalls = 0;
        const { coordinator } = makeContext({
            save: async () => {
                saveCalls++;
                return true;
            },
            hooks: {
                onWillSave: async () => false,
            },
        });
        const result = await coordinator.requestSave();
        expect(result).toBe(false);
        expect(saveCalls).toBe(0);
        // No RPC fired → coordinator stays in pre-save state.
        expect(coordinator.status).toBe("dirty");
    });

    test("proceeds when onWillSave returns undefined (default)", async () => {
        let saveCalls = 0;
        const { coordinator } = makeContext({
            save: async () => {
                saveCalls++;
                return true;
            },
            hooks: {
                onWillSave: async () => undefined,
            },
        });
        await coordinator.requestSave();
        expect(saveCalls).toBe(1);
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
        // Scenario: form view's ``beforeLeave`` calls ``requestSave`` while
        // a user-initiated save is still in flight (e.g. clicking Save then
        // immediately clicking a breadcrumb).  Without epoch invalidation,
        // the first save's terminal ``_transition("ok")`` would fire AFTER
        // the second save has settled the state back to "clean", throwing
        // ``InvalidFormSaveTransitionError`` from inside an async catch
        // that propagates as an unhandled rejection in the test.
        let resolveFirst, resolveSecond;
        const firstPromise = new Promise((r) => (resolveFirst = r));
        const secondPromise = new Promise((r) => (resolveSecond = r));
        let call = 0;
        let firstSaveEnteredAt = null;
        let secondSaveEnteredAt = null;
        let coordinator;
        // ``save`` is the ONLY post-begin observation point that doesn't
        // race the awaits in requestSave.  Capture (status, epoch) the
        // moment each call lands inside save() — at that point ``begin``
        // has fired.
        ({ coordinator } = makeContext({
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
        }));

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
        // Symmetric to the previous test: the FIRST save throws, but the
        // SECOND save (which has overtaken the epoch) eventually succeeds.
        // The first's ``_transition("failed")`` must be suppressed —
        // otherwise it would land on ``error`` and the successor save's
        // ``begin`` would be ``error → saving`` (allowed) → ``ok`` →
        // ``clean``, but the user-visible "lastError" would carry the
        // stale failure across an otherwise-successful save.
        let resolveSecond;
        const secondPromise = new Promise((r) => (resolveSecond = r));
        let call = 0;
        const fakeError = new Error("stale-failure");
        const { coordinator } = makeContext({
            save: () =>
                ++call === 1 ? Promise.reject(fakeError) : secondPromise,
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
        // The form controller may discard a dirty form mid-save (e.g. a
        // multi-company recovery dialog chose "discard").  ``requestDiscard``
        // bumps the epoch so the in-flight save's ``ok`` becomes a no-op
        // instead of clobbering the post-discard ``clean`` status.
        let resolveSave;
        const savePromise = new Promise((r) => (resolveSave = r));
        let statusInsideSave = null;
        let coordinator;
        ({ coordinator } = makeContext({
            save: () => {
                statusInsideSave = coordinator.status;
                return savePromise;
            },
        }));

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

    test("a veto while a save is in flight does not reject the in-flight save", async () => {
        // Scenario: a save is in flight when a second ``requestSave`` runs and
        // its ``onWillSave`` vetoes (external validation rejected the newer
        // edits).  The veto moves ``saving → dirty``; without epoch
        // invalidation the in-flight save's terminal ``_finishTransition("ok")``
        // would then attempt an illegal ``dirty → ok`` and reject a *successful*
        // save (re-throwing from its own catch as an unhandled rejection).
        let resolveFirst;
        const firstPromise = new Promise((r) => (resolveFirst = r));
        let willSaveCall = 0;
        const { coordinator } = makeContext({
            save: () => firstPromise,
            hooks: {
                onWillSave: async () => (++willSaveCall === 1 ? undefined : false),
            },
        });

        const firstSave = coordinator.requestSave();
        // Pump microtasks so the first save has entered save() (begin fired).
        await Promise.resolve();
        await Promise.resolve();
        expect(coordinator.isSaving).toBe(true);

        // Second save vetoes while the first is still in flight.
        const vetoed = await coordinator.requestSave();
        expect(vetoed).toBe(false);
        expect(coordinator.status).toBe("dirty");

        // The in-flight save now succeeds — it must resolve cleanly (returning
        // its saved value), not reject.
        resolveFirst(true);
        const firstResult = await firstSave;
        expect(firstResult).toBe(true);
        // The veto's ``dirty`` status stands: there are newer, un-saved edits.
        expect(coordinator.status).toBe("dirty");
    });
});
