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
