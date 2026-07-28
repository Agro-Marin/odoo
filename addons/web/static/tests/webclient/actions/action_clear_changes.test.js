// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import { EventBus } from "@odoo/owl";
import { AppEvent } from "@web/core/events";
import { clearUncommittedChanges } from "@web/webclient/actions/action_clear_changes";

/**
 * Mount-free tests for ``action_clear_changes.js``.
 *
 * This is the veto that stands between the user and losing their edits: every
 * mounted controller gets a chance to refuse an action transition. It takes the
 * env rather than the manager, so a bare EventBus is the whole fixture — yet
 * its semantics were only ever asserted through form-view save dialogs.
 *
 * Subscribers push callbacks into a shared array rather than returning values,
 * which is unusual enough to be worth pinning directly.
 */

/**
 * An env whose bus lets tests register controller-style subscribers.
 *
 * ``any``: ``clearUncommittedChanges`` declares a full ``OdooEnv``, but it
 * touches exactly one member. A partial stand-in is the point of the seam, so
 * widen here rather than casting at nine call sites.
 *
 * @returns {any}
 */
function makeEnv() {
    return { bus: new EventBus() };
}

/**
 * Subscribe like ``ControllerComponent`` does: push a callback onto the array
 * carried by the event.
 * @param {{bus: EventBus}} env
 * @param {Function} callback
 */
function subscribe(env, callback) {
    env.bus.addEventListener(AppEvent.CLEAR_UNCOMMITTED_CHANGES, (ev) => {
        ev.detail.push(callback);
    });
}

describe.current.tags("desktop");

test("with no controller listening, the transition is allowed", async () => {
    expect(await clearUncommittedChanges(makeEnv())).toBe(true);
});

test("a single consenting controller allows the transition", async () => {
    const env = makeEnv();
    subscribe(env, () => true);
    expect(await clearUncommittedChanges(env)).toBe(true);
});

test("a callback returning nothing is treated as consent", async () => {
    const env = makeEnv();
    subscribe(env, () => {});
    expect(await clearUncommittedChanges(env)).toBe(true);
});

test("one explicit false vetoes the transition", async () => {
    const env = makeEnv();
    subscribe(env, () => true);
    subscribe(env, () => false);
    subscribe(env, () => true);
    expect(await clearUncommittedChanges(env)).toBe(false);
});

test("every subscriber is asked, even after one has refused", async () => {
    const env = makeEnv();
    const asked = [];
    subscribe(env, () => {
        asked.push("a");
        return false;
    });
    subscribe(env, () => {
        asked.push("b");
        return true;
    });

    expect(await clearUncommittedChanges(env)).toBe(false);
    expect(asked).toEqual(["a", "b"]);
});

test("asynchronous answers are awaited, not sampled", async () => {
    const env = makeEnv();
    const def = new Deferred();
    subscribe(env, () => def);
    let settled = false;

    const promise = clearUncommittedChanges(env).then((res) => {
        settled = true;
        return res;
    });
    await Promise.resolve();
    expect(settled).toBe(false);

    def.resolve(false);
    expect(await promise).toBe(false);
});

test("forceLeave is passed through to every callback", async () => {
    const env = makeEnv();
    const seen = [];
    subscribe(env, (params) => seen.push(params));
    subscribe(env, (params) => seen.push(params));

    await clearUncommittedChanges(env, { forceLeave: true });

    expect(seen).toEqual([{ forceLeave: true }, { forceLeave: true }]);
});

test("callbacks always receive an options object, even with no options", async () => {
    const env = makeEnv();
    const seen = [];
    subscribe(env, (params) => seen.push(params));

    await clearUncommittedChanges(env);

    expect(seen).toEqual([{ forceLeave: undefined }]);
});

test("a rejecting callback propagates rather than silently allowing the leave", async () => {
    const env = makeEnv();
    subscribe(env, () => Promise.reject(new Error("beforeLeave blew up")));
    await expect(clearUncommittedChanges(env)).rejects.toThrow(/beforeLeave blew up/);
});
