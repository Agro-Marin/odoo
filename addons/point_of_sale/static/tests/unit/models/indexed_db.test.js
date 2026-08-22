import { describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import IndexedDB from "@point_of_sale/app/models/utils/indexed_db";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

class FakeOpenRequest {
    constructor(name, version) {
        this.name = name;
        this.version = version;
        this.result = null;
        this.error = null;
    }
    succeed(db) {
        this.result = db;
        this.onsuccess?.({ target: this });
    }
    fail(name, message = name) {
        this.error = { name, message };
        this.onerror?.({ target: this });
    }
    block() {
        this.onblocked?.();
    }
}

class FakeFactory {
    constructor(dbName) {
        this.dbName = dbName;
        this.requests = [];
    }
    open(name, version) {
        const request = new FakeOpenRequest(name, version);
        if (name === this.dbName) {
            this.requests.push(request);
        }
        return request;
    }
    get last() {
        return this.requests.at(-1);
    }
}

const fakeDb = (storeNames = ["store"]) => ({
    version: 3,
    objectStoreNames: { contains: (name) => storeNames.includes(name) },
    close() {
        this.closed = true;
    },
    transaction: () => ({ abort() {} }),
});

const makeIndexedDB = ({ dialog = null } = {}) => {
    const factory = new FakeFactory("test-db");
    patchWithCleanup(window, { indexedDB: factory });
    const db = new IndexedDB("test-db", false, [["id", "store"]], null, dialog);
    factory.last.succeed(fakeDb());
    return { db, factory };
};

const fakeTransaction = () => ({
    error: null,
    aborted: false,
    requests: [],
    objectStore() {
        return {
            put: (value) => {
                const request = { value };
                this.requests.push(request);
                return request;
            },
        };
    },
    abort() {
        this.aborted = true;
    },
});

describe("indexed_db", () => {
    test("a failed reopen does not latch _isReconnecting forever", async () => {
        const { db, factory } = makeIndexedDB();
        db.dbVersion = 7;
        db.db = null;

        db._attemptReconnect();
        expect(db._isReconnecting).toBe(true);
        expect(db.dbVersion).toBe(false);

        await advanceTime(3000);
        expect(factory.requests).toHaveLength(2);
        expect(factory.last.version).toBe(undefined);

        factory.last.fail("VersionError");
        await advanceTime(6000);
        expect(factory.requests).toHaveLength(3);
    });

    test("a reopen blocked by another tab is treated as a failure", async () => {
        const { db, factory } = makeIndexedDB();
        db.db = null;
        db._attemptReconnect();
        await advanceTime(3000);
        expect(factory.requests).toHaveLength(2);

        factory.last.block();
        await advanceTime(10000);
        expect(db._isReconnecting).toBe(true);
        await advanceTime(6000);
        expect(factory.requests).toHaveLength(3);
    });

    test("reconnecting gives up with a user-visible dialog", async () => {
        const added = [];
        const { db, factory } = makeIndexedDB({ dialog: { add: () => added.push(1) } });
        db.db = null;

        db._attemptReconnect();
        for (const delay of [3000, 6000, 12000, 24000, 48000]) {
            await advanceTime(delay);
            factory.last.fail("VersionError");
        }
        expect(factory.requests).toHaveLength(6);
        expect(added).toHaveLength(1);
        expect(db._isReconnecting).toBe(false);
    });

    test("a successful reopen clears the latch and the attempt counter", async () => {
        const { db, factory } = makeIndexedDB();
        db.db = null;
        db._attemptReconnect();
        await advanceTime(3000);

        factory.last.succeed(fakeDb());
        expect(db._isReconnecting).toBe(false);
        expect(db._reconnectAttempts).toBe(0);
        expect(db.db).not.toBe(null);
    });

    test("a batch resolves on commit, not on the last request success", async () => {
        const { db } = makeIndexedDB();
        const transaction = fakeTransaction();
        patchWithCleanup(db, { getNewTransaction: () => transaction });

        const promise = db.create("store", [{ id: 1 }, { id: 2 }]);
        expect(transaction.requests).toHaveLength(2);

        for (const request of transaction.requests) {
            request.onsuccess?.();
        }
        transaction.error = { name: "QuotaExceededError" };
        transaction.onabort();

        const results = await promise;
        expect(results).toHaveLength(1);
        expect(results[0].status).toBe("rejected");
        expect(results[0].reason.name).toBe("QuotaExceededError");
    });

    test("a batch that commits is reported fulfilled", async () => {
        const { db } = makeIndexedDB();
        const transaction = fakeTransaction();
        patchWithCleanup(db, { getNewTransaction: () => transaction });

        const promise = db.create("store", [{ id: 1 }]);
        transaction.oncomplete();

        const results = await promise;
        expect(results[0].status).toBe("fulfilled");
        expect(db.activeTransactions.has(transaction)).toBe(false);
    });

    test("a failing request aborts the batch instead of half-committing it", async () => {
        const { db } = makeIndexedDB();
        const transaction = fakeTransaction();
        patchWithCleanup(db, { getNewTransaction: () => transaction });

        const promise = db.create("store", [{ id: 1 }, { id: 2 }]);
        transaction.requests[0].onsuccess?.();
        transaction.requests[1].onerror({ target: { error: { name: "DataError" } } });

        expect(transaction.aborted).toBe(true);
        transaction.onabort();

        const results = await promise;
        expect(results[0].status).toBe("rejected");
        expect(results[0].reason.name).toBe("DataError");
    });
});
