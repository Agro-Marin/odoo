// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { user } from "@web/core/user";
import { SupersededError } from "@web/core/utils/concurrency";
import { actionStorage } from "@web/webclient/actions/action_storage";
import { loadState } from "@web/webclient/actions/load_state";

/**
 * BRANCH COVERAGE for ``load_state.js``, with NO OWL MOUNT.
 *
 * ``load_state.test.js`` is the end-to-end suite: 77 tests, every one of them
 * mounting a WebClient and driving a real URL. It is the right shape for what
 * it asserts (that a given URL produces a given screen), but it makes the
 * module's own decisions expensive to reach — the supersession guard, the
 * degradation path when breadcrumb reconstruction fails, and the
 * MissingActionError unwinding each need a specific server failure staged
 * behind a full boot.
 *
 * ``load_state`` reaches six manager members — ``router``,
 * ``_loadStateGeneration``, ``_controllersFromState``, ``_getActionParams``,
 * ``doAction`` and ``env`` — so a literal covers it. The module-level
 * collaborators it uses directly (``actionStorage``, ``user``) are real: both
 * are cheap and asserting against the actual sessionStorage keys is the point
 * of two of these tests.
 *
 * @param {Object} [overrides]
 */
function makeFakeAm(overrides = {}) {
    /** @type {Record<string, any[]>} */
    const calls = { doAction: [], controllersFromState: [], busEvents: [] };
    const am = {
        router: { current: { action: 7, actionStack: [{ action: 7 }] } },
        _loadStateGeneration: 0,
        env: { bus: new EventBus() },
        _controllersFromState: async (state) => {
            calls.controllersFromState.push(state);
            return [{ jsId: "ancestor" }];
        },
        _getActionParams: () => ({ actionRequest: 7, options: {} }),
        doAction: async (actionRequest, options) => {
            calls.doAction.push({ actionRequest, options });
        },
        ...overrides,
    };
    am.env.bus.addEventListener(AppEvent.WEBCLIENT_LOAD_DEFAULT_APP, () =>
        calls.busEvents.push("LOAD_DEFAULT_APP"),
    );
    am.__calls = calls;
    return am;
}

/** An error shaped like the server's MissingActionError. */
function missingActionError() {
    const error = new Error("missing action");
    /** @type {any} */ (error).exceptionName =
        "odoo.addons.web.controllers.action.MissingActionError";
    return error;
}

describe.current.tags("desktop");

test("an omitted state defaults to the router's current state", async () => {
    const am = makeFakeAm();
    await loadState(am);
    expect(am.__calls.controllersFromState[0]).toBe(am.router.current);
});

test("an explicit state is used verbatim", async () => {
    const am = makeFakeAm();
    const state = { action: 99, actionStack: [{ action: 99 }] };
    await loadState(am, state);
    expect(am.__calls.controllersFromState[0]).toBe(state);
});

test("every entry bumps the navigation-intent counter", async () => {
    const am = makeFakeAm();
    await loadState(am);
    await loadState(am);
    expect(am._loadStateGeneration).toBe(2);
});

test("a stored lang different from the user's drops the restore cache", async () => {
    const am = makeFakeAm();
    actionStorage.setCurrentAction('{"id":1}');
    actionStorage.setLang("zz_ZZ");
    await loadState(am);
    expect(browser.sessionStorage.getItem("current_action")).toBe(null);
    expect(browser.sessionStorage.getItem("current_lang")).toBe(null);
});

test("a matching stored lang keeps the restore cache", async () => {
    const am = makeFakeAm();
    actionStorage.setCurrentAction('{"id":1}');
    actionStorage.setLang(user.lang);
    await loadState(am);
    expect(browser.sessionStorage.getItem("current_action")).toBe('{"id":1}');
});

test("no stored lang keeps the restore cache", async () => {
    const am = makeFakeAm();
    actionStorage.setCurrentAction('{"id":1}');
    browser.sessionStorage.removeItem("current_lang");
    await loadState(am);
    expect(browser.sessionStorage.getItem("current_action")).toBe('{"id":1}');
});

test("a failed reconstruction still loads the leaf action, without ancestry", async () => {
    const warnings = [];
    patchWithCleanup(console, { warn: (...args) => warnings.push(args[0]) });
    const am = makeFakeAm({
        _controllersFromState: async () => {
            throw new Error("breadcrumbs exploded");
        },
    });

    expect(await loadState(am)).toBe(true);

    expect(am.__calls.doAction).toHaveLength(1);
    expect(am.__calls.doAction[0].options.newStack).toEqual([]);
    expect(warnings[0]).toMatch(/without breadcrumbs/);
});

test("a newer loadState started mid-reconstruction supersedes this one", async () => {
    const am = makeFakeAm({
        _controllersFromState: async () => {
            am._loadStateGeneration++;
            return [];
        },
    });

    await expect(loadState(am)).rejects.toThrow(SupersededError);
    expect(am.__calls.doAction).toEqual([]);
});

test("the guard also fires when the reconstruction failed", async () => {
    patchWithCleanup(console, { warn: () => {} });
    const am = makeFakeAm({
        _controllersFromState: async () => {
            am._loadStateGeneration++;
            throw new Error("both at once");
        },
    });
    await expect(loadState(am)).rejects.toThrow(SupersededError);
    expect(am.__calls.doAction).toEqual([]);
});

test("an unusable state resolves to undefined without dispatching", async () => {
    const am = makeFakeAm({ _getActionParams: () => null });
    expect(await loadState(am)).toBe(undefined);
    expect(am.__calls.doAction).toEqual([]);
});

test("the reconstructed stack is handed to doAction whole", async () => {
    const stack = [{ jsId: "a" }, { jsId: "b" }];
    const am = makeFakeAm({ _controllersFromState: async () => stack });
    await loadState(am);
    expect(am.__calls.doAction[0].options.newStack).toBe(stack);
});

/**
 * A url four actions deep whose leaf `getActionParams` could not resolve, so it
 * settled on the entry at index 2 and reported one popped leaf. The crumbs of
 * THAT action are the entries at index 0 and 1.
 */
const POPPED_STATE = {
    actionStack: [{ action: 1 }, { action: 2 }, { action: 3 }, { action: 4 }],
};

const POPPED_PARAMS = () => ({ actionRequest: 7, options: { poppedLeaves: 1 } });

test("poppedLeaves cuts at the entry it settled on, and is consumed", async () => {
    const stack = [
        { jsId: "a", stackIndex: 0 },
        { jsId: "b", stackIndex: 1 },
        { jsId: "c", stackIndex: 2 },
    ];
    const am = makeFakeAm({
        _controllersFromState: async () => stack,
        _getActionParams: POPPED_PARAMS,
    });

    await loadState(am, POPPED_STATE);

    const { options } = am.__calls.doAction[0];
    expect(options.newStack).toEqual([stack[0], stack[1]]);
    expect("poppedLeaves" in options).toBe(false);
});

test("a dropped ancestor cannot shift the cut", async () => {
    // `controllersFromState` removed the deleted/inaccessible records that used
    // to sit at index 0 and 1, so the rebuilt stack is SHORTER than the url's
    // actionStack. Counting survivors would keep "c" — the controller for the
    // very action about to be dispatched — as its own breadcrumb parent.
    const am = makeFakeAm({
        _controllersFromState: async () => [{ jsId: "c", stackIndex: 2 }],
        _getActionParams: POPPED_PARAMS,
    });
    await loadState(am, POPPED_STATE);
    expect(am.__calls.doAction[0].options.newStack).toEqual([]);
});

test("a drop inside the popped tail does not take a live crumb with it", async () => {
    // The entry at index 2 is the one being dispatched AND the one the server
    // could not name — the same unreadable record explains both. Counting
    // survivors cut one crumb too many and lost "b".
    const stack = [
        { jsId: "a", stackIndex: 0 },
        { jsId: "b", stackIndex: 1 },
    ];
    const am = makeFakeAm({
        _controllersFromState: async () => stack,
        _getActionParams: POPPED_PARAMS,
    });
    await loadState(am, POPPED_STATE);
    expect(am.__calls.doAction[0].options.newStack).toEqual(stack);
});

test("poppedLeaves of 0 leaves the stack alone", async () => {
    const stack = [{ jsId: "a" }];
    const am = makeFakeAm({
        _controllersFromState: async () => stack,
        _getActionParams: () => ({ actionRequest: 7, options: { poppedLeaves: 0 } }),
    });
    await loadState(am);
    expect(am.__calls.doAction[0].options.newStack).toBe(stack);
});

test("a successful dispatch reports that a state was loaded", async () => {
    const am = makeFakeAm();
    expect(await loadState(am)).toBe(true);
});

test("a deleted leaf action pops the stack and retries the parent", async () => {
    const state = {
        action: 3,
        actionStack: [{ action: 1 }, { action: 2 }, { action: 3 }],
    };
    let attempt = 0;
    const am = makeFakeAm({
        doAction: async (actionRequest) => {
            attempt++;
            if (attempt === 1) {
                throw missingActionError();
            }
            am.__calls.doAction.push({ actionRequest, options: {} });
        },
    });

    expect(await loadState(am, state)).toBe(true);

    expect(attempt).toBe(2);
    const retried = am.__calls.controllersFromState.at(-1);
    expect(retried.actionStack).toEqual([{ action: 1 }, { action: 2 }]);
    expect(retried.action).toBe(2);
});

test("unwinding repeats until a loadable ancestor is found", async () => {
    const state = {
        action: 3,
        actionStack: [{ action: 1 }, { action: 2 }, { action: 3 }],
    };
    let attempt = 0;
    const am = makeFakeAm({
        doAction: async () => {
            attempt++;
            if (attempt < 3) {
                throw missingActionError();
            }
        },
    });

    expect(await loadState(am, state)).toBe(true);
    expect(attempt).toBe(3);
});

test("a deleted action with a single-entry stack falls back to the default app", async () => {
    const state = { action: 3, actionStack: [{ action: 3 }] };
    const am = makeFakeAm({
        doAction: async () => {
            throw missingActionError();
        },
    });

    expect(await loadState(am, state)).toBe(true);
    expect(am.__calls.busEvents).toEqual(["LOAD_DEFAULT_APP"]);
});

test("a deleted home action on a bare /odoo url falls back, it does not crash", async () => {
    const state = { action: 3 };
    const am = makeFakeAm({
        doAction: async () => {
            throw missingActionError();
        },
    });

    expect(await loadState(am, state)).toBe(true);
    expect(am.__calls.busEvents).toEqual(["LOAD_DEFAULT_APP"]);
});

test("any other dispatch error propagates untouched", async () => {
    const am = makeFakeAm({
        doAction: async () => {
            throw new Error("something else entirely");
        },
    });
    await expect(
        loadState(am, { action: 3, actionStack: [{ action: 3 }] }),
    ).rejects.toThrow(/something else entirely/);
    expect(am.__calls.busEvents).toEqual([]);
});

test("an access error on the leaf is not mistaken for a missing action", async () => {
    const error = new Error("access denied");
    /** @type {any} */ (error).exceptionName = "odoo.exceptions.AccessError";
    const am = makeFakeAm({
        doAction: async () => {
            throw error;
        },
    });
    await expect(
        loadState(am, { action: 3, actionStack: [{ action: 1 }, { action: 3 }] }),
    ).rejects.toThrow(/access denied/);
    expect(am.__calls.busEvents).toEqual([]);
});
