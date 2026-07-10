// @ts-check

import { after, describe, expect, test, tick } from "@odoo/hoot";
import { IndexedDB } from "@web/core/utils/indexed_db";

// Lives here (not tests/core/utils/indexed_db.test.js) to pin the
// unhandled-rejection hardening the RPC disk cache depends on; Hoot fails a
// test on any unhandled rejection, so a clean completion is the assertion.

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
    // The constructor fires `mutex.exec(...)` without awaiting it; pre-fix the
    // discarded promise surfaced as an unhandled rejection. The `.catch(() =>
    // {})` on the constructor call now swallows it.
    patchOpenToThrow();

    // Must not throw synchronously and must not leave an unhandled rejection.
    expect(() => new IndexedDB(CACHE_NAME, 1)).not.toThrow();

    // Flush microtasks/macrotasks so any dangling rejection surfaces before the test ends.
    await tick();
    await tick();
    expect(true).toBe(true);
});

test("operations after a failing open reject rather than hang", async () => {
    // Each public operation opens its own connection and must surface the
    // failure as a rejected promise, not hang — the reject-arm counterpart of
    // the ``.then(resolve, reject)`` fix.
    patchOpenToThrow();

    const db = new IndexedDB(CACHE_NAME, 1);
    await expect(db.read("mytable", "key")).rejects.toThrow();
});
