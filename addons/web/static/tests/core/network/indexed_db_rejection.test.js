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

    expect(() => new IndexedDB(CACHE_NAME, 1)).not.toThrow();

    await tick();
    await tick();
    expect(true).toBe(true);
});

test("operations after a failing open degrade to the no-db path", async () => {
    patchOpenToThrow();

    const db = new IndexedDB(CACHE_NAME, 1);
    expect(await db.read("mytable", "key")).toBe(undefined);
    expect(await db.write("mytable", "key", { a: 1 })).toBe(undefined);
});

test("a failing open flips the instance to degraded mode", async () => {
    patchOpenToThrow();

    const db = new IndexedDB(CACHE_NAME, 1);
    await db.read("mytable", "key");
    expect(db._degraded).toBe(true);
});
