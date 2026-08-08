import { Logger } from "@bus/workers/bus_worker_utils";
import { after, before, describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-dom";

describe.current.tags("desktop");

before(() => indexedDB.deleteDatabase("test_db"));
after(() => indexedDB.deleteDatabase("test_db"));

test("J16: a new Logger opens no IndexedDB until the first log", async () => {
    // Own DB name + explicit close so this test never blocks the shared
    // "test_db" delete of the sibling test.
    indexedDB.deleteDatabase("j16_db");
    const logger = new Logger("j16_db");
    // Constructor is side-effect free: a Logger is created on every worker boot
    // even when logging is disabled, so it must not open IndexedDB eagerly.
    expect(logger._db).toBe(undefined);
    expect(logger._dbPromise).toBe(undefined);
    await logger.log("first");
    // The database is opened lazily on first use.
    expect(logger._db).not.toBe(undefined);
    expect(await logger.getLogs()).toEqual(["first"]);
    logger._db?.close();
    indexedDB.deleteDatabase("j16_db");
});

test("logs are saved and garbage-collected after TTL", async () => {
    indexedDB.deleteDatabase("test_db");
    const logger = new Logger("test_db");
    await logger.log("foo");
    await logger.log("bar");
    expect(await logger.getLogs()).toEqual(["foo", "bar"]);
    await advanceTime(Logger.LOG_TTL + 1000);
    expect(await logger.getLogs()).toEqual([]);
    indexedDB.deleteDatabase("test_db");
});

test("a closed database handle is forgotten and reopened on the next use", async () => {
    // `_ensureDatabaseAvailable` short-circuits on `this._db`, so a handle that
    // died out from under us (storage pressure, "clear site data", a
    // `versionchange` from another context) used to be reused forever: every
    // later `transaction()` threw InvalidStateError, silently killing bus
    // logging for the rest of the worker's life since `_logDebug` swallows the
    // rejection into a console error.
    indexedDB.deleteDatabase("reopen_db");
    const logger = new Logger("reopen_db");
    await logger.log("before");
    expect(logger._db).not.toBe(null);

    // Close it the way the browser would, then let the `close` event land.
    const stale = logger._db;
    stale.close();
    stale.onclose?.();
    expect(logger._db).toBe(null);
    expect(logger._dbPromise).toBe(null);

    // The next call transparently reopens instead of throwing forever.
    await logger.log("after");
    expect(logger._db).not.toBe(null);
    expect(await logger.getLogs()).toEqual(["before", "after"]);
    logger._db?.close();
    indexedDB.deleteDatabase("reopen_db");
});

test("a handle that dies without a close event is dropped on the failed use", async () => {
    indexedDB.deleteDatabase("drop_db");
    const logger = new Logger("drop_db");
    await logger.log("first");
    // Close without notifying: `log` hits a synchronous InvalidStateError.
    logger._db.close();
    await expect(logger.log("second")).rejects.toThrow();
    // It must not keep the dead handle: the next call reopens and succeeds.
    expect(logger._db).toBe(null);
    await logger.log("third");
    expect(await logger.getLogs()).toEqual(["first", "third"]);
    logger._db?.close();
    indexedDB.deleteDatabase("drop_db");
});
