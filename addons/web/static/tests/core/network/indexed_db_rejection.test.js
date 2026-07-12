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

test("operations after a failing open degrade to the no-db path", async () => {
    // A synchronously-throwing open (storage denied, private browsing) must
    // degrade to the no-db fallback — read resolves undefined (cache miss),
    // write resolves as a no-op — NOT reject: localization_service.start()
    // and the RPC disk cache await these unguarded on the boot path, so a
    // rejection killed the whole webclient there.
    patchOpenToThrow();

    const db = new IndexedDB(CACHE_NAME, 1);
    expect(await db.read("mytable", "key")).toBe(undefined);
    expect(await db.write("mytable", "key", { a: 1 })).toBe(undefined);
});

test("a failing open flips the instance to degraded mode", async () => {
    // After the first sync open failure the instance short-circuits every
    // subsequent operation instead of re-attempting a throwing open (and
    // re-logging) on each call.
    patchOpenToThrow();

    const db = new IndexedDB(CACHE_NAME, 1);
    await db.read("mytable", "key");
    expect(db._degraded).toBe(true);
});
