// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";

/**
 * A promise carrying the `abort` that `rpc()` attaches to the one it returns.
 * @returns {Promise<any> & {
 *     abort: (rejectError?: boolean) => void,
 *     aborts: boolean[],
 *     resolve: (value?: any) => void,
 *     reject: (reason?: any) => void,
 * }}
 */
function abortablePromise() {
    const def = /** @type {any} */ (new Deferred());
    def.aborts = [];
    def.abort = (/** @type {boolean} */ rejectError = true) => {
        def.aborts.push(rejectError);
    };
    return def;
}

test("supersede aborts the promise it drops", async () => {
    const keepLast = new KeepLast();
    const first = abortablePromise();
    const second = abortablePromise();

    keepLast.add(first);
    expect(first.aborts).toEqual([]);

    keepLast.add(second);
    // Rejecting form: unwinds the async frames behind the dropped request
    // instead of leaving them pending. See the comment in `KeepLast.add`.
    expect(first.aborts).toEqual([true]);
    expect(second.aborts).toEqual([]);

    first.resolve(1);
    second.resolve(2);
    await animationFrame();
});

test("cancel() aborts the entry in flight", async () => {
    const keepLast = new KeepLast();
    const only = abortablePromise();

    keepLast.add(only);
    keepLast.cancel();

    expect(only.aborts).toEqual([true]);
    only.resolve(1);
    await animationFrame();
});

test("an explicit abort handler wins over the promise's own", async () => {
    const keepLast = new KeepLast();
    const controller = new AbortController();
    const composite = abortablePromise();

    keepLast.add(composite, { abort: () => controller.abort() });
    keepLast.add(Promise.resolve("newer"));

    expect(controller.signal.aborted).toBe(true);
    // The explicit handler replaces the default; the promise's own is not run.
    expect(composite.aborts).toEqual([]);

    composite.resolve(1);
    await animationFrame();
});

test("the winner is never aborted, before or after it settles", async () => {
    const keepLast = new KeepLast();
    const winner = abortablePromise();

    const result = keepLast.add(winner);
    winner.resolve("value");
    expect(await result).toBe("value");

    // A later cancel() must not reach back into work that already finished.
    keepLast.cancel();
    expect(winner.aborts).toEqual([]);
});

test("a throwing abort handler does not wedge the supersede", async () => {
    const keepLast = new KeepLast({ rejectSuperseded: true });
    const first = new Deferred();

    const superseded = keepLast.add(first, {
        abort: () => {
            throw new Error("disposer blew up");
        },
    });

    keepLast.add(Promise.resolve("newer"));

    await expect(superseded).rejects.toThrow(SupersededError);
});

test("abort composes with rejectSuperseded", async () => {
    const keepLast = new KeepLast({ rejectSuperseded: true });
    const first = abortablePromise();

    const superseded = keepLast.add(first);
    keepLast.add(abortablePromise());

    expect(first.aborts).toEqual([true]);
    await expect(superseded).rejects.toThrow(SupersededError);
});

test("a promise without abort() supersedes exactly as before", async () => {
    const keepLast = new KeepLast();
    const first = new Deferred();
    const second = new Deferred();

    let firstSettled = false;
    keepLast.add(first).then(
        () => (firstSettled = true),
        () => (firstSettled = true),
    );
    const winner = keepLast.add(second);

    first.resolve("dropped");
    second.resolve("kept");

    expect(await winner).toBe("kept");
    await animationFrame();
    expect(firstSettled).toBe(false);
});
