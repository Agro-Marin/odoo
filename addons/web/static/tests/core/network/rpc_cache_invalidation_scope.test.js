// @ts-check

import { Deferred, describe, expect, test, tick } from "@odoo/hoot";
import { mockIndexedDBForTests } from "@web/../tests/_framework/mock_indexed_db.hoot";
import { RPCCache } from "@web/core/network/rpc_cache";

mockIndexedDBForTests();

describe.current.tags("headless");

const SECRET = "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b";
const S_PENDING = Symbol("pending");

/**
 * @param {Promise<any>} promise
 */
function promiseState(promise) {
    return Promise.race([promise, Promise.resolve(S_PENDING)]).then(
        (value) =>
            value === S_PENDING
                ? { status: "pending" }
                : { status: "fulfilled", value },
        (reason) => ({ status: "rejected", reason }),
    );
}

/**
 * ``invalidate`` scopes both halves of its job by table: it clears ram and disk
 * for the named tables, and drops the pending requests whose key starts with
 * one of them. ``invalidateByModel`` scoped only the first half, so a request
 * on a table nobody asked about was still marked invalidated -- and an
 * invalidated request skips the cleanup in ``onRejected``, which is what left
 * the ram cache holding a rejected promise.
 */
describe("invalidateByModel scopes pending requests by table too", () => {
    /**
     * An `update: "always"` read joins a request that is still pending and
     * issues its own when there is none, so "is this still a pending request"
     * is observable as "did the fallback run a second time".
     *
     * @param {string[]} invalidatedTables
     */
    async function secondFallbackRan(invalidatedTables) {
        const cache = new RPCCache("mock", 1, SECRET);
        const inFlight = new Deferred();
        const first = cache.read("table_a", "k", () => inFlight, {
            model: "res.partner",
        });
        cache.invalidateByModel(invalidatedTables, "res.partner");
        let ran = false;
        const second = cache.read(
            "table_a",
            "k",
            () => {
                ran = true;
                return Promise.resolve({ ok: 2 });
            },
            { model: "res.partner", update: "always" },
        );
        inFlight.resolve({ ok: 1 });
        await first;
        await second;
        return ran;
    }

    test("a request on an untouched table stays pending", async () => {
        expect(await secondFallbackRan(["table_b"])).toBe(false);
    });

    test("a request on a named table is dropped", async () => {
        expect(await secondFallbackRan(["table_a"])).toBe(true);
    });

    test("a request for another model is untouched", async () => {
        const cache = new RPCCache("mock", 1, SECRET);
        const inFlight = new Deferred();
        const read = cache.read("table_a", "k", () => inFlight, { model: "res.users" });

        cache.invalidateByModel(["table_a"], "res.partner");

        inFlight.resolve({ ok: 1 });
        expect(await read).toEqual({ ok: 1 });
    });
});

describe("a failed read never leaves a rejected promise in the cache", () => {
    test("the ram entry is dropped even when the request was invalidated", async () => {
        const cache = new RPCCache("mock", 1, SECRET);
        const inFlight = new Deferred();
        const read = cache.read("table_a", "k", () => inFlight, {
            model: "res.partner",
        });

        // drop the request from `pendingRequests` while it is still in flight
        cache.invalidateByModel(["table_b"], "res.partner");
        inFlight.reject(new Error("boom"));
        await expect(read).rejects.toThrow(/boom/);
        await tick();

        // a later read must issue a fresh request and settle, not join a
        // rejected cache entry and hang on it
        const second = cache.read("table_a", "k", () => Promise.resolve({ ok: 1 }), {
            model: "res.partner",
            update: "always",
        });
        await tick();
        await tick();
        expect((await promiseState(second)).status).toBe("fulfilled");
        expect(await second).toEqual({ ok: 1 });
    });

    test("an update:always read over a rejected ram entry still settles", async () => {
        // `invalidateByModel` no longer produces this state, but the ram cache
        // holds promises and nothing stops one from rejecting, so the read has
        // to cope. Seeded directly rather than through the bug it used to have.
        const cache = new RPCCache("mock", 1, SECRET);
        const poisoned = Promise.reject(new Error("stale"));
        poisoned.catch(() => {});
        cache.ramCache.write("t", "k", poisoned, "m");

        const read = cache.read("t", "k", () => Promise.resolve({ ok: 1 }), {
            model: "m",
            update: "always",
        });
        await tick();
        await tick();
        // it used to hang: `onRejected`/`onFulfilled` both wait on a gate that
        // only the fulfilled path opened
        expect((await promiseState(read)).status).toBe("fulfilled");
        expect(await read).toEqual({ ok: 1 });
    });

    test("an update:always read over a rejected ram entry reports its own failure", async () => {
        const cache = new RPCCache("mock", 1, SECRET);
        const poisoned = Promise.reject(new Error("stale"));
        poisoned.catch(() => {});
        cache.ramCache.write("t", "k", poisoned, "m");

        /** @type {any} */
        let reason = null;
        let settled = false;
        // handled synchronously: an escaping rejection is an unhandled one
        cache
            .read("t", "k", () => Promise.reject(new Error("fresh")), {
                model: "m",
                update: "always",
            })
            .then(
                () => (settled = true),
                (error) => {
                    settled = true;
                    reason = error;
                },
            );
        await tick();
        await tick();
        // it used to hang: `onRejected` waits on a gate only the fulfilled path
        // opened, so this read never settled at all
        expect(settled).toBe(true);
        expect(String(reason)).toMatch(/fresh/);
    });
});
