// @ts-check

import { after, describe, expect, runAllTimers, test, tick } from "@odoo/hoot";
import { on } from "@odoo/hoot-dom";
import { mockFetch } from "@odoo/hoot-mock";
import {
    ConnectionAbortedError,
    ConnectionLostError,
    InvalidResponseError,
    rpc,
    rpcBus,
    RPCError,
    ServerOverloadError,
} from "@web/core/network/rpc";
import { RPCCache } from "@web/core/network/rpc_cache";

const onRpcRequest = (listener) => after(on(rpcBus, "RPC:REQUEST", listener));
const onRpcResponse = (listener) => after(on(rpcBus, "RPC:RESPONSE", listener));

describe.current.tags("headless");

test("can perform a simple rpc", async () => {
    mockFetch((_, { body }) => {
        const bodyObject = JSON.parse(body);
        expect(bodyObject.jsonrpc).toBe("2.0");
        expect(bodyObject.method).toBe("call");
        expect(bodyObject.id).toBeOfType("integer");
        return { result: { action_id: 123 } };
    });

    expect(await rpc("/test/")).toEqual({ action_id: 123 });
});

test("trigger an error when response has 'error' key", async () => {
    mockFetch(() => ({
        error: {
            message: "message",
            code: 12,
            data: {
                debug: "data_debug",
                message: "data_message",
            },
        },
    }));

    const error = new RPCError("message");
    await expect(rpc("/test/")).rejects.toThrow(error);
});

test("rpc with simple routes", async () => {
    mockFetch((route, { body }) => ({
        result: { route, params: JSON.parse(body).params },
    }));

    expect(await rpc("/my/route")).toEqual({ route: "/my/route", params: {} });
    expect(await rpc("/my/route", { hey: "there", model: "test" })).toEqual({
        route: "/my/route",
        params: { hey: "there", model: "test" },
    });
});

test("check trigger RPC:REQUEST and RPC:RESPONSE for a simple rpc", async () => {
    mockFetch(() => ({ result: {} }));

    const rpcIdsRequest = [];
    const rpcIdsResponse = [];

    onRpcRequest(({ detail }) => {
        rpcIdsRequest.push(detail.data.id);
        const silent = detail.settings.silent ? "(silent)" : "";
        expect.step(`RPC:REQUEST${silent}`);
    });
    onRpcResponse(({ detail }) => {
        rpcIdsResponse.push(detail.data.id);
        const silent = detail.settings.silent ? "(silent)" : "";
        const success = "result" in detail ? "(ok)" : "";
        const fail = "error" in detail ? "(ko)" : "";
        expect.step(`RPC:RESPONSE${silent}${success}${fail}`);
    });

    await rpc("/test/");
    expect(rpcIdsRequest.toString()).toBe(rpcIdsResponse.toString());
    expect.verifySteps(["RPC:REQUEST", "RPC:RESPONSE(ok)"]);

    await rpc("/test/", {}, { silent: true });
    expect(rpcIdsRequest.toString()).toBe(rpcIdsResponse.toString());
    expect.verifySteps(["RPC:REQUEST(silent)", "RPC:RESPONSE(silent)(ok)"]);
});

test("check trigger RPC:REQUEST and RPC:RESPONSE for a rpc with an error", async () => {
    mockFetch(() => ({
        error: {
            message: "message",
            code: 12,
            data: {
                debug: "data_debug",
                message: "data_message",
            },
        },
    }));

    const rpcIdsRequest = [];
    const rpcIdsResponse = [];

    onRpcRequest(({ detail }) => {
        rpcIdsRequest.push(detail.data.id);
        const silent = detail.settings.silent ? "(silent)" : "";
        expect.step(`RPC:REQUEST${silent}`);
    });
    onRpcResponse(({ detail }) => {
        rpcIdsResponse.push(detail.data.id);
        const silent = detail.settings.silent ? "(silent)" : "";
        const success = "result" in detail ? "(ok)" : "";
        const fail = "error" in detail ? "(ko)" : "";
        expect.step(`RPC:RESPONSE${silent}${success}${fail}`);
    });

    const error = new RPCError("message");
    await expect(rpc("/test/")).rejects.toThrow(error);
    expect.verifySteps(["RPC:REQUEST", "RPC:RESPONSE(ko)"]);
});

test("check connection aborted", async () => {
    mockFetch(() => new Promise(() => {}));
    onRpcRequest(() => expect.step("RPC:REQUEST"));
    onRpcResponse(() => expect.step("RPC:RESPONSE"));

    const connection = rpc();
    connection.abort();
    const error = new ConnectionAbortedError();
    await expect(connection).rejects.toThrow(error);
    expect.verifySteps(["RPC:REQUEST", "RPC:RESPONSE"]);
});

test("abort during body streaming stays silent, no InvalidResponseError", async () => {
    // Regression: abort() can land after the response headers pass the guards
    // but while the body is still streaming. Cancelling the body makes
    // response.json() reject; the rpc must treat that as caller intent (the
    // abort already decided the promise's fate) rather than fabricating an
    // InvalidResponseError — which would reject a silently-aborted promise and
    // pop a false "Session Expired" dialog on a healthy session.
    // Headers pass every guard (200 + application/json), but the body read is
    // held open via a json() we resolve/reject by hand — modeling a body that
    // is still streaming when abort() lands.
    let rejectJson;
    const response = new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
    });
    response.json = () => new Promise((_resolve, reject) => (rejectJson = reject));
    mockFetch(() => response);
    onRpcResponse(() => expect.step("RPC:RESPONSE"));

    const connection = rpc("/test/");
    connection.then(
        () => expect.step("resolved"),
        () => expect.step("rejected"),
    );
    // Let fetch resolve so execution parks on `await response.json()`.
    await tick();
    await tick();
    // Silent abort: the outer promise must stay pending, exactly one
    // RPC:RESPONSE (the abort's) must be emitted.
    connection.abort(false);
    // Now fail the still-pending body read with the abort in flight.
    rejectJson(new DOMException("The user aborted a request.", "AbortError"));
    await tick();
    await tick();

    // Only the abort's RPC:RESPONSE — no second (InvalidResponseError) event and
    // no rejection of the caller-orphaned promise.
    expect.verifySteps(["RPC:RESPONSE"]);
});

test("trigger a ServerOverloadError when response carries a non-JSON content-type", async () => {
    // Server returned an HTML error page (typical werkzeug PoolError /
    // OperationalError traceback).  Caught by content-type sniff BEFORE
    // attempting JSON parse — the more specific ``ServerOverloadError``
    // is thrown so retry logic can apply a longer backoff floor.
    mockFetch(
        () =>
            new Response("<html>pool full</html>", {
                status: 500,
                headers: { "Content-Type": "text/html" },
            }),
    );

    await expect(rpc("/test/")).rejects.toThrow(ServerOverloadError);
});

test("ServerOverloadError is also a ConnectionLostError (backward compatibility)", async () => {
    // Existing callers catching ``instanceof ConnectionLostError`` must
    // continue to match the subclass — this contract is load-bearing for
    // every component that currently shows the connection-lost UX.
    mockFetch(
        () =>
            new Response("<html/>", {
                status: 500,
                headers: { "Content-Type": "text/html; charset=utf-8" },
            }),
    );

    await expect(rpc("/test/")).rejects.toThrow(ConnectionLostError);
});

test("trigger a ConnectionLostError when response says JSON but body is unparseable", async () => {
    // Content-Type advertises JSON, but the body is truncated / malformed.
    // No evidence of server-side error page; treat as transient connectivity
    // failure with the default backoff (no overload floor).
    mockFetch(
        () =>
            new Response("<h...", {
                status: 500,
                headers: { "Content-Type": "application/json" },
            }),
    );

    await expect(rpc("/test/")).rejects.toThrow(ConnectionLostError);
});

test("no content-type header falls back to ConnectionLostError (preserves prior behavior)", async () => {
    // ``Response(string)`` defaults to ``text/plain;charset=UTF-8`` per the
    // Fetch spec — but here we explicitly strip the header to simulate a
    // truly bare response.  The sniff guards on ``contentType && !isJson``
    // so the absence of a header preserves the pre-T2.3 behavior.
    mockFetch(() => {
        const r = new Response("<h...", { status: 500 });
        r.headers.delete("content-type");
        return r;
    });

    await expect(rpc("/test/")).rejects.toThrow(ConnectionLostError);
});

test("non-JSON response with a non-5xx status is an InvalidResponseError", async () => {
    // fetch follows redirects: a session-expired POST redirected to the
    // HTML login page arrives here as a 200 text/html response. That is
    // deterministic — not a server overload — and must not be retried.
    mockFetch(
        () =>
            new Response("<html>login page</html>", {
                status: 200,
                headers: { "Content-Type": "text/html" },
            }),
    );

    await expect(rpc("/test/")).rejects.toThrow(InvalidResponseError);
});

test("InvalidResponseError is also a ConnectionLostError (backward compatibility)", async () => {
    mockFetch(
        () =>
            new Response("<html>not found</html>", {
                status: 404,
                headers: { "Content-Type": "text/html" },
            }),
    );

    await expect(rpc("/test/")).rejects.toThrow(ConnectionLostError);
});

test("unparseable JSON body with a non-5xx status is an InvalidResponseError", async () => {
    // A truncated/empty 200 body is deterministic garbage: only 5xx
    // unparseable bodies keep the retryable ConnectionLostError treatment.
    mockFetch(
        () =>
            new Response("", {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
    );

    await expect(rpc("/test/")).rejects.toThrow(InvalidResponseError);
});

test("Retry: InvalidResponseError is never retried", async () => {
    let fetchCount = 0;
    mockFetch(() => {
        fetchCount++;
        return new Response("<html>login page</html>", {
            status: 200,
            headers: { "Content-Type": "text/html" },
        });
    });

    const prom = rpc("/test/", {}, { retry: 3 });
    await expect(prom).rejects.toThrow(InvalidResponseError);
    // A single attempt: retrying a deterministic non-JSON response would
    // just burn retries with a backoff against an unchanging outcome.
    expect(fetchCount).toBe(1);
});

test("rpc can send additional headers", async () => {
    mockFetch((url, settings) => {
        expect(settings.headers).toEqual(
            new Headers([
                ["Content-Type", "application/json"],
                ["Hello", "World"],
            ]),
        );
        return { result: true };
    });
    await rpc("/test/", null, { headers: { Hello: "World" } });
});

test("Cache: can cache a simple rpc", async () => {
    rpc.setCache(
        new RPCCache(
            "mockRpc",
            1,
            "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
        ),
    );
    mockFetch(() => {
        expect.step("Fetch");
        return { result: { action_id: 123 } };
    });

    expect(await rpc("/test/", {}, { cache: true })).toEqual({ action_id: 123 });
    expect(await rpc("/test/", {}, { cache: true })).toEqual({ action_id: 123 });
    expect(await rpc("/test/", {}, { cache: true })).toEqual({ action_id: 123 });
    expect.verifySteps(["Fetch"]);
});

test("Dedup: concurrent identical rpcs share one fetch and one promise", async () => {
    mockFetch(() => {
        expect.step("Fetch");
        return { result: { x: 1 } };
    });

    const p1 = rpc("/test/", {}, { dedup: true });
    const p2 = rpc("/test/", {}, { dedup: true });
    const p3 = rpc("/test/", {}, { dedup: true });

    // Promise identity is the load-bearing contract: matches rpc_dedup.test.js
    // and is what callers rely on when they apply ``.abort()`` to one of the
    // returned promises (shared abort across deduped callers).
    expect(p1).toBe(p2);
    expect(p2).toBe(p3);

    const [r1, r2, r3] = await Promise.all([p1, p2, p3]);
    expect(r1).toEqual({ x: 1 });
    expect(r2).toEqual({ x: 1 });
    expect(r3).toEqual({ x: 1 });
    expect.verifySteps(["Fetch"]);
});

test("Dedup: different (url, params) do not collide", async () => {
    mockFetch((_, { body }) => {
        const id = JSON.parse(body).params.id;
        expect.step(`Fetch:${id}`);
        return { result: { id } };
    });

    const p1 = rpc("/test/", { id: 1 }, { dedup: true });
    const p2 = rpc("/test/", { id: 2 }, { dedup: true });
    expect(p1).not.toBe(p2);

    await Promise.all([p1, p2]);
    expect.verifySteps(["Fetch:1", "Fetch:2"]);
});

test("Dedup: post-settle call fires fresh (entry evicted)", async () => {
    mockFetch(() => {
        expect.step("Fetch");
        return { result: true };
    });

    await rpc("/test/", {}, { dedup: true });
    await rpc("/test/", {}, { dedup: true });
    expect.verifySteps(["Fetch", "Fetch"]);
});

test("Dedup: error path also evicts so subsequent calls retry", async () => {
    mockFetch(() => {
        expect.step("Fetch");
        return new Response("<h...", { status: 500 });
    });

    const p1 = rpc("/test/", {}, { dedup: true });
    const p2 = rpc("/test/", {}, { dedup: true });
    expect(p1).toBe(p2);

    await expect(p1).rejects.toThrow(ConnectionLostError);
    await expect(p2).rejects.toThrow(ConnectionLostError);
    expect.verifySteps(["Fetch"]);

    // After the shared rejection settles, a new call must fire fresh —
    // dedup must NOT cache failures.
    await expect(rpc("/test/", {}, { dedup: true })).rejects.toThrow(
        ConnectionLostError,
    );
    expect.verifySteps(["Fetch"]);
});

test("Dedup: silent abort evicts the inflight entry (regression)", async () => {
    // Silent abort (``promise.abort(false)``) cancels the underlying
    // fetch but intentionally leaves the outer promise pending so the
    // caller can swallow the cancellation without surfacing an error.
    //
    // Pre-fix, the dedup-eviction hook was wired exclusively through
    // ``promise.then(onSettle, onSettle)`` — since the promise never
    // settles on a silent abort, ``onSettle`` never fired and the
    // inflight Map slot leaked forever.  A subsequent identical
    // request would then be deduped onto a forever-pending,
    // already-canceled promise and the new caller would never see
    // data.
    //
    // The fix wraps ``.abort`` in the dedup branch so silent aborts
    // evict synchronously.  This test verifies the user-observable
    // contract: a fresh request after silent abort fires a new fetch.
    let fetchCount = 0;
    mockFetch(() => {
        fetchCount++;
        expect.step(`Fetch:${fetchCount}`);
        // First fetch hangs (so abort actually does something);
        // subsequent fetches resolve normally.
        if (fetchCount === 1) {
            return new Promise(() => {});
        }
        return { result: { ok: true } };
    });

    const p1 = rpc("/test/", {}, { dedup: true });
    p1.abort(false); // silent — p1 stays pending forever

    // Fresh identical request must NOT be deduped onto p1.
    const p2 = rpc("/test/", {}, { dedup: true });
    expect(p2).not.toBe(p1);
    expect(await p2).toEqual({ ok: true });
    expect.verifySteps(["Fetch:1", "Fetch:2"]);
});

test("Dedup composes with cache: cache hit skips the fetch", async () => {
    rpc.setCache(
        new RPCCache(
            "mockRpcDedup",
            1,
            "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
        ),
    );
    mockFetch(() => {
        expect.step("Fetch");
        return { result: { x: 42 } };
    });

    expect(await rpc("/test/", {}, { cache: true })).toEqual({ x: 42 });
    expect.verifySteps(["Fetch"]);

    // Concurrent dedup calls — both hit cache (no fetch).
    const p1 = rpc("/test/", {}, { cache: true, dedup: true });
    const p2 = rpc("/test/", {}, { cache: true, dedup: true });
    expect(p1).toBe(p2);
    await Promise.all([p1, p2]);
    expect.verifySteps([]);
});

test("Dedup: differing settings do not leak silent to a non-silent caller", async () => {
    // Two concurrent callers with identical (url, params) but DIFFERENT
    // ``silent`` settings must NOT share one promise — otherwise the second
    // caller inherits the first's behaviour (silent: no loading indicator, no
    // error dialog).  The settings fingerprint in the dedup key prevents the
    // join, so each caller fires its own fetch with its own settings.
    mockFetch(() => {
        expect.step("Fetch");
        return { result: true };
    });
    const requestSilentFlags = [];
    onRpcRequest(({ detail }) =>
        requestSilentFlags.push(Boolean(detail.settings.silent)),
    );

    const pSilent = rpc("/test/", {}, { dedup: true, silent: true });
    const pLoud = rpc("/test/", {}, { dedup: true });

    // Differing settings ⇒ distinct promises (no dedup join).
    expect(pSilent).not.toBe(pLoud);

    await Promise.all([pSilent, pLoud]);

    // Each caller issued its own fetch, and the non-silent caller's REQUEST
    // was NOT downgraded to silent.
    expect.verifySteps(["Fetch", "Fetch"]);
    expect(requestSilentFlags).toEqual([true, false]);
});

test("Dedup: identical settings still share one promise", async () => {
    // Guard the other direction of the fingerprint: same (url, params) AND
    // same settings must still dedup onto a single fetch.
    mockFetch(() => {
        expect.step("Fetch");
        return { result: { ok: true } };
    });

    const p1 = rpc("/test/", {}, { dedup: true, silent: true });
    const p2 = rpc("/test/", {}, { dedup: true, silent: true });
    expect(p1).toBe(p2);

    await Promise.all([p1, p2]);
    expect.verifySteps(["Fetch"]);
});

test("Cache: abort(false) on a cache-miss rpc exposes abort and does not throw", async () => {
    // The RpcPromise contract promises ``.abort()`` on EVERY rpc() return.
    // Pre-fix the cache branch returned a plain promise with no ``abort``, so
    // ``prom.abort(false)`` (record_autocomplete.js pattern) threw a
    // TypeError.  The fix forwards abort to the underlying fallback.
    rpc.setCache(
        new RPCCache(
            "mockRpcCacheAbortMiss",
            1,
            "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
        ),
    );
    // Hang so the fallback fetch is genuinely in flight when we abort.
    mockFetch(() => new Promise(() => {}));

    const prom = rpc("/test/", {}, { cache: true });
    expect(prom.abort).toBeInstanceOf(Function);
    // Let the cache miss run the fallback (creating the abortable inner rpc).
    await tick();
    expect(() => prom.abort(false)).not.toThrow();
});

test("Cache: abort on a cache hit is a safe no-op", async () => {
    // On a cache HIT the fallback never runs, so there is no in-flight fetch
    // to cancel — ``abort`` must exist (contract) and be a harmless no-op.
    rpc.setCache(
        new RPCCache(
            "mockRpcCacheAbortHit",
            1,
            "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
        ),
    );
    mockFetch(() => {
        expect.step("Fetch");
        return { result: { x: 7 } };
    });

    expect(await rpc("/test/", {}, { cache: true })).toEqual({ x: 7 });
    expect.verifySteps(["Fetch"]);

    const prom = rpc("/test/", {}, { cache: true });
    expect(prom.abort).toBeInstanceOf(Function);
    expect(() => prom.abort(false)).not.toThrow();
    // Cache hit still resolves normally after the no-op abort.
    expect(await prom).toEqual({ x: 7 });
    expect.verifySteps([]);
});

test("abort after settle does not emit a second RPC:RESPONSE", async () => {
    // Once the RPC has settled it fired exactly one RESPONSE for its data.id.
    // A late ``abort()`` must be a no-op: a second RESPONSE would double-emit
    // to id-keyed observers (loading_indicator, slow_rpc_service).
    mockFetch(() => ({ result: { ok: true } }));
    onRpcResponse(() => expect.step("RESPONSE"));

    const prom = rpc("/test/");
    expect(await prom).toEqual({ ok: true });
    expect.verifySteps(["RESPONSE"]);

    // Late aborts (both variants) must not fire anything nor throw.
    expect(() => prom.abort()).not.toThrow();
    expect(() => prom.abort(false)).not.toThrow();
    await tick();
    expect.verifySteps([]);
});

test("abort after an RPCError settle does not emit a second RPC:RESPONSE", async () => {
    // The server-error path must mark the promise settled like every other
    // terminal path, so a late abort() stays a no-op.
    mockFetch(() => ({ error: { code: 200, message: "Odoo Server Error", data: {} } }));
    onRpcResponse(() => expect.step("RESPONSE"));

    const prom = rpc("/test/");
    await expect(prom).rejects.toThrow(RPCError);
    expect.verifySteps(["RESPONSE"]);

    expect(() => prom.abort()).not.toThrow();
    expect(() => prom.abort(false)).not.toThrow();
    await tick();
    expect.verifySteps([]);
});

test("abort after a network-failure settle does not emit a second RPC:RESPONSE", async () => {
    // Same exactly-once invariant for the generic fetch-failure path.
    mockFetch(() => {
        throw new TypeError("NetworkError when attempting to fetch resource.");
    });
    onRpcResponse(() => expect.step("RESPONSE"));

    const prom = rpc("/test/");
    await expect(prom).rejects.toThrow(ConnectionLostError);
    expect.verifySteps(["RESPONSE"]);

    expect(() => prom.abort()).not.toThrow();
    expect(() => prom.abort(false)).not.toThrow();
    await tick();
    expect.verifySteps([]);
});

test("Retry: abort while an attempt is in flight rejects once", async () => {
    // Aborting mid-attempt forwards to the in-flight inner rpc, which fires
    // its single RESPONSE(ko); the outer promise rejects with the abort class.
    // No stray extra RESPONSE.
    mockFetch(() => new Promise(() => {})); // hang → attempt stays in flight
    onRpcResponse(({ detail }) =>
        expect.step("error" in detail ? "RESPONSE(ko)" : "RESPONSE(ok)"),
    );

    const prom = rpc("/test/", {}, { retry: 3 });
    prom.abort();
    await expect(prom).rejects.toThrow(ConnectionAbortedError);
    expect.verifySteps(["RESPONSE(ko)"]);
});

test("Retry: abort during backoff cancels the scheduled retry", async () => {
    // A retryable first attempt schedules a backoff timer (no attempt is in
    // flight during the wait).  Aborting must clearTimeout it so the retry
    // never fires a fresh RPC after the caller gave up.
    let fetchCount = 0;
    mockFetch(() => {
        fetchCount++;
        expect.step(`Fetch:${fetchCount}`);
        // Malformed JSON body ⇒ ConnectionLostError ⇒ retryable.
        return new Response("<h...", {
            status: 500,
            headers: { "Content-Type": "application/json" },
        });
    });

    const prom = rpc(
        "/test/",
        {},
        { retry: { retries: 5, baseMs: 100000, maxMs: 100000 } },
    );
    // Let the first attempt fail and schedule the (long) backoff timer.
    await tick();
    await tick();
    expect.verifySteps(["Fetch:1"]);

    // Abort during the backoff wait (silent: outer stays pending), then run
    // every pending timer.  A cleared timer ⇒ no second fetch.
    prom.abort(false);
    await runAllTimers();
    await tick();
    expect.verifySteps([]);
});

// Plan-C envelope versioning (Phase 3)
//
// The server-side ``@versioned_envelope`` decorator stashes a content hash on
// ``request._response_version``; the JSON-RPC dispatcher lifts it as a
// sibling of ``result`` (``parsed.version``).  rpc.js reattaches it as
// ``result.__version`` so the rpc cache's ``payloadChanged`` sees the same
// field as for in-payload ``@versioned`` returns.  These tests pin the JS
// half of that contract.

test("envelope version: list result gets __version attached when parsed.version is present", async () => {
    mockFetch(() => ({
        result: [{ id: 1 }, { id: 2 }],
        version: "abc123def456",
    }));
    const result = await rpc("/test/");
    expect(result).toEqual([{ id: 1 }, { id: 2 }]);
    expect(result.__version).toBe("abc123def456");
});

test("envelope version: dict result gets __version attached when parsed.version is present", async () => {
    mockFetch(() => ({
        result: { records: [{ id: 1 }], length: 1 },
        version: "v789",
    }));
    const result = await rpc("/test/");
    expect(result.__version).toBe("v789");
});

test("envelope version: in-payload __version wins over envelope sibling", async () => {
    // If the result already carries __version (e.g. ``@versioned`` decorator
    // on a dict return), the envelope sibling must not overwrite it.
    mockFetch(() => ({
        result: { records: [], __version: "in-payload-wins" },
        version: "envelope-loses",
    }));
    const result = await rpc("/test/");
    expect(result.__version).toBe("in-payload-wins");
});

test("envelope version: absent parsed.version leaves result unchanged", async () => {
    // Legacy server (no envelope versioning) — result must round-trip clean.
    mockFetch(() => ({ result: [{ id: 1 }] }));
    const result = await rpc("/test/");
    expect(result).toEqual([{ id: 1 }]);
    expect(result.__version).toBe(undefined);
});

test("envelope version: primitive result is not mutated (cannot attach property)", async () => {
    mockFetch(() => ({ result: 42, version: "v1" }));
    const result = await rpc("/test/");
    expect(result).toBe(42);
});

test("envelope version: null result is not mutated", async () => {
    mockFetch(() => ({ result: null, version: "v1" }));
    const result = await rpc("/test/");
    expect(result).toBe(null);
});

describe("CLEAR-CACHES bus handling", () => {
    function withStubCache() {
        const calls = { invalidate: [], invalidateByModel: [] };
        const stub = {
            invalidate: (tables) => calls.invalidate.push(tables),
            invalidateByModel: (tables, model) =>
                calls.invalidateByModel.push([tables, model]),
        };
        rpc.setCache(stub);
        after(() => rpc.setCache(undefined));
        return calls;
    }

    test("object detail WITHOUT a model invalidates the named tables (not the object)", () => {
        const calls = withStubCache();
        rpcBus.dispatchEvent(
            new CustomEvent("CLEAR-CACHES", {
                detail: { tables: ["web_read", "web_search_read"] },
            }),
        );
        // Passing the whole object to invalidate() used to feed a non-iterable
        // into bumpDiskGeneration and crash with a TypeError, silently skipping.
        expect(calls.invalidate).toEqual([["web_read", "web_search_read"]]);
        expect(calls.invalidateByModel).toEqual([]);
    });

    test("object detail WITH a model invalidates by model", () => {
        const calls = withStubCache();
        rpcBus.dispatchEvent(
            new CustomEvent("CLEAR-CACHES", {
                detail: { model: "res.partner", tables: ["web_read"] },
            }),
        );
        expect(calls.invalidateByModel).toEqual([[["web_read"], "res.partner"]]);
        expect(calls.invalidate).toEqual([]);
    });

    test("a bare table name string still invalidates that table", () => {
        const calls = withStubCache();
        rpcBus.dispatchEvent(new CustomEvent("CLEAR-CACHES", { detail: "web_read" }));
        expect(calls.invalidate).toEqual(["web_read"]);
    });
});
