// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { SupersededError } from "@web/core/utils/concurrency";
import { ActionDispatch } from "@web/webclient/actions/action_dispatch";

/**
 * BRANCH COVERAGE for {@link ActionDispatch}, with NO OWL MOUNT.
 *
 * This is the payoff of extracting the transaction out of
 * ``ControllerComponent``'s lifecycle hooks: every commit / fail / discard
 * branch used to require mounting a real component and provoking a real error
 * to reach, which is why several of them had no direct coverage at all — only
 * the end-to-end consequences were asserted, from ``target.test.js`` and
 * friends. Driving the object directly reaches them in milliseconds.
 *
 * ``action_dispatch.test.js`` is the companion suite: same object, exercised
 * through a real mount, asserting only the observable surface. Keep both — this
 * one pins the branches, that one pins that the branches are wired to OWL
 * correctly.
 *
 * The fake manager is the sanctioned ``am`` seam (see "THE SIBLING CONTRACT"
 * in ``action_service.js``). ActionDispatch reaches exactly:
 *   controllerStack · dialog · nextDialog · env · pushState · restore ·
 *   _nextId · _pendingDispatch
 */

describe.current.tags("desktop");

/** @param {Object} [overrides] */
function makeFakeAm(overrides = {}) {
    const calls = { restore: [], pushState: 0, busEvents: [], title: [] };
    let id = 0;
    const am = {
        controllerStack: [],
        dialog: null,
        nextDialog: null,
        env: {
            bus: new EventBus(),
            services: {
                title: { setParts: (parts) => calls.title.push(parts) },
            },
        },
        pushState: () => calls.pushState++,
        restore: (jsId) => {
            calls.restore.push(jsId);
            return "restore-result";
        },
        _nextId: () => ++id,
        ...overrides,
    };
    am.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UPDATE, (ev) =>
        calls.busEvents.push({ type: "UPDATE", detail: ev.detail }),
    );
    am.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UI_UPDATED, (ev) =>
        calls.busEvents.push({ type: "UI_UPDATED", detail: ev.detail }),
    );
    am.__calls = calls;
    return am;
}

/**
 * @param {Object} am
 * @param {Object} [params] overrides for controller/action/nextStack
 */
function makeDispatch(am, params = {}) {
    const controller = {
        jsId: "controller_1",
        isMounted: false,
        displayName: "Some Action",
        ...params.controller,
    };
    const action = {
        type: "ir.actions.act_window",
        _originalAction: '{"id":7}',
        ...params.action,
    };
    const dispatch = new ActionDispatch(am, {
        controller,
        action,
        nextStack: params.nextStack ?? [controller],
        restoreStackOnError: params.restoreStackOnError,
    });
    dispatch.promise.catch(() => {});
    return dispatch;
}

const EXPORTERS = { getGlobalState: () => ({ g: 1 }), getLocalState: () => ({ l: 1 }) };

test("commit (inline) rebinds the stack, flags the controller, resolves", async () => {
    const am = makeFakeAm();
    const dispatch = makeDispatch(am);
    let resolved = false;
    dispatch.promise.then(() => (resolved = true));

    dispatch.commit(EXPORTERS);
    await Promise.resolve();

    expect(am.controllerStack).toBe(dispatch.nextStack);
    expect(dispatch.controller.isMounted).toBe(true);
    expect(am.__calls.pushState).toBe(1);
    expect(resolved).toBe(true);
});

test("commit (inline) wires the component's state exporters onto the controller", async () => {
    const am = makeFakeAm();
    const dispatch = makeDispatch(am);
    dispatch.commit(EXPORTERS);
    expect(dispatch.controller.getGlobalState()).toEqual({ g: 1 });
    expect(dispatch.controller.getLocalState()).toEqual({ l: 1 });
});

test("commit (inline) records the action and lang in the restore cache", async () => {
    const am = makeFakeAm();
    const dispatch = makeDispatch(am);
    dispatch.commit(EXPORTERS);
    expect(browser.sessionStorage.getItem("current_action")).toBe('{"id":7}');
    expect(browser.sessionStorage.getItem("current_lang")).not.toBe(null);
    expect(am.__calls.title).toEqual([{ action: "Some Action" }]);
});

test("commit emits UI_UPDATED only after the stack is committed", async () => {
    const am = makeFakeAm();
    const dispatch = makeDispatch(am);
    let stackAtEvent = null;
    am.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UI_UPDATED, () => {
        stackAtEvent = am.controllerStack;
    });
    dispatch.commit(EXPORTERS);
    expect(stackAtEvent).toBe(dispatch.nextStack);
});

test("commit clears the manager's pending dispatch before UI_UPDATED listeners run", async () => {
    // A dispatch riding a foreign stack (loadState) marks itself pending so
    // `_effectiveStack` answers with the still-displayed base stack while it
    // is in flight. Once `commit()` publishes `nextStack`, keeping it pending
    // would make every `UI-UPDATED` listener that reads `currentController`
    // see the controller this dispatch just replaced (web_studio's `inStudio`
    // flag missed the studio action landing this way).
    const am = makeFakeAm();
    const dispatch = makeDispatch(am);
    am._pendingDispatch = dispatch;
    let pendingAtEvent = "unset";
    am.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UI_UPDATED, () => {
        pendingAtEvent = am._pendingDispatch;
    });

    dispatch.commit(EXPORTERS);

    expect(pendingAtEvent).toBe(null);
    expect(am._pendingDispatch).toBe(null);
});

test("commit leaves another dispatch's pending marker alone", async () => {
    const am = makeFakeAm();
    const other = makeDispatch(am, { controller: { jsId: "other" } });
    am._pendingDispatch = other;

    makeDispatch(am).commit(EXPORTERS);

    expect(am._pendingDispatch).toBe(other);
});

test("commit (target=new) promotes the pending dialog and never touches the stack", async () => {
    const am = makeFakeAm();
    let removedPrevious = 0;
    am.dialog = { remove: () => removedPrevious++, onClose: undefined };
    const pending = { remove: () => {}, onClose: () => {} };
    am.nextDialog = pending;
    const stackBefore = am.controllerStack;
    const dispatch = makeDispatch(am, { action: { target: "new" } });

    dispatch.commit(EXPORTERS);

    expect(removedPrevious).toBe(1);
    expect(am.dialog).toBe(pending);
    expect(am.nextDialog).toBe(null);
    expect(am.controllerStack).toBe(stackBefore);
    expect(am.__calls.pushState).toBe(0);
});

test("commit (target=new) tolerates there being no previously committed dialog", async () => {
    const am = makeFakeAm();
    const pending = { remove: () => {} };
    am.nextDialog = pending;
    const dispatch = makeDispatch(am, { action: { target: "new" } });
    dispatch.commit(EXPORTERS);
    expect(am.dialog).toBe(pending);
});

test("discard rejects with SupersededError when destroyed before mount", async () => {
    const am = makeFakeAm();
    const dispatch = makeDispatch(am);
    dispatch.discard({ componentStatus: "destroyed" });
    await expect(dispatch.promise).rejects.toThrow(SupersededError);
});

test("discard is a no-op once the controller has mounted", async () => {
    const am = makeFakeAm();
    const dispatch = makeDispatch(am, { controller: { isMounted: true } });
    let settled = false;
    dispatch.promise.then(
        () => (settled = true),
        () => (settled = true),
    );
    dispatch.discard({ componentStatus: "destroyed" });
    await Promise.resolve();
    expect(settled).toBe(false);
});

test("discard is a no-op while the component itself is still mounted", async () => {
    const am = makeFakeAm();
    const dispatch = makeDispatch(am);
    let settled = false;
    dispatch.promise.then(
        () => (settled = true),
        () => (settled = true),
    );
    dispatch.discard({ componentStatus: "mounted" });
    await Promise.resolve();
    expect(settled).toBe(false);
});

test("fail on an already-mounted controller leaves the dispatch promise alone", async () => {
    expect.errors(1);
    const am = makeFakeAm();
    const dispatch = makeDispatch(am, { controller: { isMounted: true } });
    dispatch.fail(new Error("late failure"), { componentStatus: "mounted" });
    expect(am.__calls.busEvents).toEqual([]);
    expect(am.__calls.restore).toEqual([]);
    await expect.waitForErrors([/late failure/]);
});

test("fail during a child's onMounted swaps in BlankComponent and supersedes", async () => {
    expect.errors(1);
    const am = makeFakeAm();
    const dispatch = makeDispatch(am);
    dispatch.fail(new Error("child failed"), { componentStatus: "mounted" });

    await expect(dispatch.promise).rejects.toThrow(SupersededError);
    const [event] = am.__calls.busEvents;
    expect(event.type).toBe("UPDATE");
    expect(event.detail.Component.name).toBe("BlankComponent");
    expect(event.detail.componentProps.withControlPanel).toBe(true);
    await expect.waitForErrors([/child failed/]);
});

test("fail (target=new) tears the pending dialog down via its own remove", async () => {
    const am = makeFakeAm();
    const dispatch = makeDispatch(am, { action: { target: "new" } });
    let removed = 0;
    dispatch.removeDialogRef.current = () => removed++;

    dispatch.fail(new Error("dialog failed"), { componentStatus: "destroyed" });

    expect(removed).toBe(1);
    expect(am.__calls.restore).toEqual([]);
    await expect(dispatch.promise).rejects.toThrow(/dialog failed/);
});

test("fail (target=new) is safe when no dialog was ever registered", async () => {
    const am = makeFakeAm();
    const dispatch = makeDispatch(am, { action: { target: "new" } });
    dispatch.fail(new Error("early"), { componentStatus: "destroyed" });
    await expect(dispatch.promise).rejects.toThrow(/early/);
});

test("fail on a committed controller falls back to the previous crumb", async () => {
    const am = makeFakeAm();
    const first = { jsId: "controller_0", isMounted: true };
    const failing = { jsId: "controller_1", isMounted: false };
    am.controllerStack = [first, failing];
    const dispatch = makeDispatch(am, { controller: failing });

    dispatch.fail(new Error("boom"), { componentStatus: "destroyed" });

    expect(am.__calls.restore).toEqual(["controller_0"]);
    await expect(dispatch.promise).rejects.toThrow(/boom/);
});

test("fail on the ONLY committed controller does not restore anything", async () => {
    const am = makeFakeAm();
    const only = { jsId: "controller_1", isMounted: false };
    am.controllerStack = [only];
    const dispatch = makeDispatch(am, { controller: only });

    dispatch.fail(new Error("boom"), { componentStatus: "destroyed" });

    expect(am.__calls.restore).toEqual([]);
    expect(am.__calls.busEvents).toEqual([]);
    await expect(dispatch.promise).rejects.toThrow(/boom/);
});

test("a breadcrumb restore that fails reverts to the displayed stack", async () => {
    const am = makeFakeAm();
    const displayedTip = { jsId: "displayed", isMounted: true };
    const displayed = [{ jsId: "root", isMounted: false }, displayedTip];
    am.controllerStack = [{ jsId: "root", isMounted: false }];
    const dispatch = makeDispatch(am, {
        controller: { jsId: "never_committed", isMounted: false },
        restoreStackOnError: displayed,
    });

    dispatch.fail(new Error("boom"), { componentStatus: "destroyed" });

    expect(am.controllerStack).toBe(displayed);
    expect(am.__calls.restore).toEqual(["displayed"]);
    await expect(dispatch.promise).rejects.toThrow(/boom/);
});

test("the revert is skipped when the displayed tip is not mounted", async () => {
    const am = makeFakeAm();
    const displayed = [{ jsId: "displayed", isMounted: false }];
    const live = [{ jsId: "live", isMounted: true }];
    am.controllerStack = live;
    const dispatch = makeDispatch(am, {
        controller: { jsId: "never_committed", isMounted: false },
        restoreStackOnError: displayed,
    });

    dispatch.fail(new Error("boom"), { componentStatus: "destroyed" });

    expect(am.controllerStack).toBe(live);
    expect(am.__calls.restore).toEqual(["live"]);
    await expect(dispatch.promise).rejects.toThrow(/boom/);
});

test("the revert is skipped when it would make no progress", async () => {
    const am = makeFakeAm();
    const same = [{ jsId: "displayed", isMounted: true }];
    am.controllerStack = same;
    const dispatch = makeDispatch(am, {
        controller: { jsId: "never_committed", isMounted: false },
        restoreStackOnError: same,
    });

    dispatch.fail(new Error("boom"), { componentStatus: "destroyed" });

    expect(am.controllerStack).toBe(same);
    expect(am.__calls.restore).toEqual(["displayed"]);
    await expect(dispatch.promise).rejects.toThrow(/boom/);
});

test("a failure with nothing left on the stack blanks the action container", async () => {
    const am = makeFakeAm();
    am.controllerStack = [];
    const dispatch = makeDispatch(am, {
        controller: { jsId: "never_committed", isMounted: false },
    });

    dispatch.fail(new Error("boom"), { componentStatus: "destroyed" });

    expect(am.__calls.restore).toEqual([]);
    expect(am.__calls.busEvents).toEqual([{ type: "UPDATE", detail: {} }]);
    await expect(dispatch.promise).rejects.toThrow(/boom/);
});

test("a loadState dispatch (no restoreStackOnError) keeps its ancestor fallback", async () => {
    const am = makeFakeAm();
    const ancestor = { jsId: "ancestor", isMounted: true };
    am.controllerStack = [ancestor];
    const dispatch = makeDispatch(am, {
        controller: { jsId: "never_committed", isMounted: false },
        restoreStackOnError: undefined,
    });

    dispatch.fail(new Error("boom"), { componentStatus: "destroyed" });

    expect(am.controllerStack).toEqual([ancestor]);
    expect(am.__calls.restore).toEqual(["ancestor"]);
    await expect(dispatch.promise).rejects.toThrow(/boom/);
});

test("the dispatch reaches only the documented manager members", async () => {
    const reached = new Set();
    const am = new Proxy(makeFakeAm(), {
        get(target, prop) {
            if (typeof prop === "string" && !prop.startsWith("__")) {
                reached.add(prop);
            }
            return target[prop];
        },
        set(target, prop, value) {
            if (typeof prop === "string") {
                reached.add(prop);
            }
            target[prop] = value;
            return true;
        },
    });
    patchWithCleanup(console, { warn: () => {} });
    expect.errors(1);

    makeDispatch(am).commit(EXPORTERS);
    am.nextDialog = { remove: () => {} };
    makeDispatch(am, { action: { target: "new" } }).commit(EXPORTERS);

    const superseded = makeDispatch(am);
    superseded.discard({ componentStatus: "destroyed" });
    await expect(superseded.promise).rejects.toThrow(SupersededError);

    const childFailed = makeDispatch(am);
    childFailed.fail(new Error("child"), { componentStatus: "mounted" });
    await expect(childFailed.promise).rejects.toThrow(SupersededError);

    const dialogFailed = makeDispatch(am, { action: { target: "new" } });
    dialogFailed.removeDialogRef.current = () => {};
    dialogFailed.fail(new Error("d"), { componentStatus: "destroyed" });
    await expect(dialogFailed.promise).rejects.toThrow(/d/);

    const failing = makeDispatch(am, {
        controller: { jsId: "other", isMounted: false },
    });
    failing.fail(new Error("boom"), { componentStatus: "destroyed" });
    await expect(failing.promise).rejects.toThrow(/boom/);

    expect([...reached].sort()).toEqual([
        "_nextId",
        // `commit()` clears the manager's pending dispatch the moment it
        // publishes the stack, so `UI-UPDATED` listeners reading
        // `currentController` see the controller that just landed, not the
        // one it replaced.
        "_pendingDispatch",
        "controllerStack",
        "dialog",
        "env",
        "nextDialog",
        "pushState",
        "restore",
    ]);
    await expect.waitForErrors([/child/]);
});
