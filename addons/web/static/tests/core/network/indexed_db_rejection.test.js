// @ts-check

import { after, describe, expect, test, tick } from "@odoo/hoot";
import { IndexedDB } from "@web/core/utils/indexed_db";

// These tests live under tests/core/network/ (alongside rpc.test.js) rather
// than the broader tests/core/utils/indexed_db.test.js suite: they pin the
// unhandled-rejection hardening on the IndexedDB failure paths that the RPC
// disk cache depends on.  Hoot fails a test on ANY unhandled promise
// rejection, so "the constructor / a failing open does not raise an unhandled
// rejection" is asserted simply by the test completing cleanly.

describe.current.tags("headless");

const CACHE_NAME = "unit_test_idb_rejection";

/**
 * Replace ``indexedDB.open`` with a stub that throws synchronously, mimicking
 * private-browsing / storage-disabled contexts where ``indexedDB.open`` raises
 * instead of returning a request.  Restored after the test.
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
    // The constructor kicks off ``mutex.exec(() => this._checkVersion(...))``
    // without awaiting it.  In private mode ``indexedDB.open`` throws
    // synchronously inside ``_execute``, rejecting that promise.  Pre-fix the
    // discarded promise surfaced as an unhandled rejection; the ``.catch(() =>
    // {})`` on the constructor call swallows it.
    patchOpenToThrow();

    // Must not throw synchronously and must not leave an unhandled rejection.
    expect(() => new IndexedDB(CACHE_NAME, 1)).not.toThrow();

    // Flush microtasks/macrotasks so any dangling rejection would surface
    // (and fail the test) before it ends.
    await tick();
    await tick();
    expect(true).toBe(true);
});

test("operations after a failing open reject rather than hang", async () => {
    // With ``indexedDB.open`` throwing, each public operation opens its own
    // connection and must surface the failure to its caller (a settled,
    // rejected promise) instead of pending forever — the reject-arm counterpart
    // of the ``.then(resolve, reject)`` fix.
    patchOpenToThrow();

    const db = new IndexedDB(CACHE_NAME, 1);
    await expect(db.read("mytable", "key")).rejects.toThrow();
});
