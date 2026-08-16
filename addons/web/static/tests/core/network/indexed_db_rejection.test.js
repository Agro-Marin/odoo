// @ts-check

import { after, describe, expect, test, tick } from "@odoo/hoot";
import { IndexedDB } from "@web/core/utils/indexed_db";

describe.current.tags("headless");

const CACHE_NAME = "unit_test_idb_rejection";

/**
 * Stub ``indexedDB.open`` to throw synchronously, mimicking private-browsing /
 * storage-disabled contexts. Restored after the test.
 */
function patchOpenToThrow() {
    const original = indexedDB.open;
    indexedDB.open = () => {
        throw new DOMException(
            "The user denied access to the database",
            "SecurityError",
        );
    };
    after(() => {
        indexedDB.open = original;
    });
}

test("constructor: a synchronous indexedDB.open throw is swallowed (no unhandled rejection)", async () => {
    patchOpenToThrow();

    expect(() => new IndexedDB(CACHE_NAME, "1")).not.toThrow();

    await tick();
    await tick();
    expect(true).toBe(true);
});

test("operations after a failing open degrade to the no-db path", async () => {
    patchOpenToThrow();

    const db = new IndexedDB(CACHE_NAME, "1");
    expect(await db.read("mytable", "key")).toBe(undefined);
    expect(await db.write("mytable", "key", { a: 1 })).toBe(undefined);
});

test("a failing open flips the instance to degraded mode", async () => {
    patchOpenToThrow();

    const db = new IndexedDB(CACHE_NAME, "1");
    await db.read("mytable", "key");
    expect(db._degraded).toBe(true);
});

/**
 * Record when the invalidation transaction actually completes.
 *
 * The listener is attached at transaction creation, so it precedes the
 * `oncomplete` the code under test assigns and its flag is already set by the
 * time that handler runs. Restored after the test.
 *
 * @param {{ completed: boolean }} state
 */
function patchTransactionToRecordCompletion(state) {
    const originalTransaction = IDBDatabase.prototype.transaction;
    IDBDatabase.prototype.transaction = function (...args) {
        const transaction = originalTransaction.apply(this, args);
        transaction.addEventListener("complete", () => {
            state.completed = true;
        });
        return transaction;
    };
    after(() => {
        IDBDatabase.prototype.transaction = originalTransaction;
    });
}

test("invalidate() settles on the transaction, not on its clear() requests", async () => {
    // A request's `onsuccess` fires before the transaction commits, so
    // resolving there reported success for a transaction that could still go
    // on to abort -- the later `reject` lands on an already settled promise
    // and is lost.
    const db = new IndexedDB(`${CACHE_NAME}_settle`, "1");
    await db.write("mytable", "key", { a: 1 });

    const state = { completed: false };
    patchTransactionToRecordCompletion(state);

    let completedWhenSettled = null;
    await db.invalidate(["mytable"]).then(
        () => (completedWhenSettled = state.completed),
        () => (completedWhenSettled = state.completed),
    );

    expect(completedWhenSettled).toBe(true);
    expect(await db.read("mytable", "key")).toBe(undefined);

    after(() => db.deleteDatabase());
});

/**
 * Stub ``indexedDB.open`` so it *returns* a request that then fails
 * asynchronously — what a browser does when storage is denied or the stored
 * database is unreadable, as opposed to `open` throwing outright. Counts the
 * attempts. Restored after the test.
 *
 * @param {{ opens: number }} state
 */
function patchOpenToFailAsynchronously(state) {
    const original = indexedDB.open;
    indexedDB.open = () => {
        state.opens++;
        const request = {
            onsuccess: null,
            onerror: null,
            onupgradeneeded: null,
            onblocked: null,
            error: new DOMException("storage is unavailable", "UnknownError"),
        };
        Promise.resolve().then(() =>
            request.onerror?.({ target: request, type: "error" }),
        );
        return /** @type {any} */ (request);
    };
    after(() => {
        indexedDB.open = original;
    });
}

test("an open that fails asynchronously is not retried on every call", async () => {
    // A synchronous throw already flips `_degraded`; a request that resolves to
    // an error did not, so a permanently unusable IndexedDB was reopened once
    // per cached RPC, each attempt logging its own console error.
    const state = { opens: 0 };
    patchOpenToFailAsynchronously(state);

    const db = new IndexedDB(CACHE_NAME, "1");
    for (let i = 0; i < 5; i++) {
        expect(await db.read("mytable", `key${i}`)).toBe(undefined);
    }

    expect(db._degraded).toBe(true, {
        message: "a failed open must be remembered",
    });
    expect(state.opens).toBe(1, {
        message: `opened the database ${state.opens} times for 5 reads`,
    });
});
