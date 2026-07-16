// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    getService,
    makeMockEnv,
    makeServerError,
    models,
    onRpc,
} from "@web/../tests/web_test_helpers";
import { rpcBus } from "@web/core/network/rpc";
import {
    ERROR_INACCESSIBLE_OR_MISSING,
    NAME_CACHE_LIMIT,
} from "@web/services/name_service";

class Dev extends models.Model {
    _name = "dev";
    _rec_name = "display_name";
    _records = [
        { id: 1, display_name: "Julien" },
        { id: 2, display_name: "Pierre" },
        { id: 3, display_name: "Paul", active: false },
    ];

    active = fields.Boolean({ default: true });
}

class PO extends models.Model {
    _name = "po";
    _rec_name = "display_name";
    _records = [{ id: 1, display_name: "Damien" }];
}

defineModels([Dev, PO]);

describe.current.tags("headless");

test("single loadDisplayNames", async () => {
    await makeMockEnv();
    const displayNames = await getService("name").loadDisplayNames("dev", [1, 2, 3]);
    expect(displayNames).toEqual({ 1: "Julien", 2: "Pierre", 3: "Paul" });
});

test("loadDisplayNames maps every id when resIds contain duplicates", async () => {
    await makeMockEnv();
    // The leading duplicate used to corrupt the result (record 1 took record 2's
    // name and record 2 vanished) because the return zipped names against the
    // non-deduped resIds. Every id must resolve to its own name.
    const displayNames = await getService("name").loadDisplayNames("dev", [1, 1, 2]);
    expect(displayNames).toEqual({ 1: "Julien", 2: "Pierre" });
});

test("loadDisplayNames is done in silent mode", async () => {
    await makeMockEnv();

    const onRPCRequest = ({ detail }) => {
        const silent = detail.settings.silent ? "(silent)" : "";
        expect.step(`RPC:REQUEST${silent}`);
    };
    rpcBus.addEventListener("RPC:REQUEST", onRPCRequest);
    after(() => rpcBus.removeEventListener("RPC:REQUEST", onRPCRequest));

    await getService("name").loadDisplayNames("dev", [1]);
    expect.verifySteps(["RPC:REQUEST(silent)"]);
});

test("single loadDisplayNames following addDisplayNames", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });

    getService("name").addDisplayNames("dev", { 1: "JUM", 2: "PIPU" });
    const displayNames = await getService("name").loadDisplayNames("dev", [1, 2]);
    expect(displayNames).toEqual({ 1: "JUM", 2: "PIPU" });
    expect.verifySteps([]);
});

test("single loadDisplayNames following addDisplayNames (2)", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });

    getService("name").addDisplayNames("dev", { 1: "JUM" });
    const displayNames = await getService("name").loadDisplayNames("dev", [1, 2]);
    expect(displayNames).toEqual({ 1: "JUM", 2: "Pierre" });
    expect.verifySteps(["dev:web_search_read:2"]);
});

test("addDisplayNames refreshes an already-resolved name", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });

    const nameService = getService("name");
    const displayNames = await nameService.loadDisplayNames("dev", [1]);
    expect(displayNames).toEqual({ 1: "Julien" });
    expect.verifySteps(["dev:web_search_read:1"]);

    // A fresh name pushed over a settled cache entry (e.g. record renamed
    // since first resolution, re-fetched by an autocomplete's name_search)
    // must replace the stale value, without a new RPC.
    nameService.addDisplayNames("dev", { 1: "Julien (renamed)" });
    const refreshed = await nameService.loadDisplayNames("dev", [1]);
    expect(refreshed).toEqual({ 1: "Julien (renamed)" });
    expect.verifySteps([]);
});

test("addDisplayNames settles in-flight loadDisplayNames callers", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });

    const nameService = getService("name");
    // Caller joins the microtask batch, then the name is added before the
    // batch RPC settles: the caller must get the added name.
    const loadPromise = nameService.loadDisplayNames("dev", [1]);
    nameService.addDisplayNames("dev", { 1: "JUM" });
    expect(await loadPromise).toEqual({ 1: "JUM" });
    // The already-opened batch still fired (its result is a no-op on the
    // settled entry), but the added name stays authoritative.
    expect.verifySteps(["dev:web_search_read:1"]);
    expect(await nameService.loadDisplayNames("dev", [1])).toEqual({ 1: "JUM" });
});

test("loadDisplayNames in batch", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });

    const loadPromise1 = getService("name").loadDisplayNames("dev", [1]);
    expect.verifySteps([]);
    const loadPromise2 = getService("name").loadDisplayNames("dev", [2]);
    expect.verifySteps([]);

    const [displayNames1, displayNames2] = await Promise.all([
        loadPromise1,
        loadPromise2,
    ]);
    expect(displayNames1).toEqual({ 1: "Julien" });
    expect(displayNames2).toEqual({ 2: "Pierre" });
    expect.verifySteps(["dev:web_search_read:1,2"]);
});

test("loadDisplayNames on different models", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });

    const loadPromise1 = getService("name").loadDisplayNames("dev", [1]);
    expect.verifySteps([]);
    const loadPromise2 = getService("name").loadDisplayNames("po", [1]);
    expect.verifySteps([]);

    const [displayNames1, displayNames2] = await Promise.all([
        loadPromise1,
        loadPromise2,
    ]);
    expect(displayNames1).toEqual({ 1: "Julien" });
    expect(displayNames2).toEqual({ 1: "Damien" });

    expect.verifySteps(["dev:web_search_read:1", "po:web_search_read:1"]);
});

test("invalid id", async () => {
    await makeMockEnv();
    try {
        await getService("name").loadDisplayNames("dev", ["a"]);
    } catch (error) {
        expect(error.message).toBe("Invalid ID: a");
    }
});

test("inaccessible or missing id", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });

    const displayNames = await getService("name").loadDisplayNames("dev", [4]);
    expect(displayNames).toEqual({ 4: ERROR_INACCESSIBLE_OR_MISSING });
    expect.verifySteps(["dev:web_search_read:4"]);
});

test("batch + inaccessible/missing", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });

    const loadPromise1 = getService("name").loadDisplayNames("dev", [1, 4]);
    expect.verifySteps([]);
    const loadPromise2 = getService("name").loadDisplayNames("dev", [2, 5]);
    expect.verifySteps([]);

    const [displayNames1, displayNames2] = await Promise.all([
        loadPromise1,
        loadPromise2,
    ]);
    expect(displayNames1).toEqual({ 1: "Julien", 4: ERROR_INACCESSIBLE_OR_MISSING });
    expect(displayNames2).toEqual({ 2: "Pierre", 5: ERROR_INACCESSIBLE_OR_MISSING });
    expect.verifySteps(["dev:web_search_read:1,4,2,5"]);
});

test("clearCache during an in-flight batch: all callers still settle", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });

    const nameService = getService("name");
    // Caller A opens the batch (pre-clear Deferreds)...
    const loadPromise1 = nameService.loadDisplayNames("dev", [1, 4]);
    // ...the cache is invalidated while the batch is still in flight...
    nameService.clearCache();
    // ...and caller B joins the same batch with post-clear Deferreds. Before
    // the fix, the flush resolved through caller A's stale cache mapping:
    // caller B's ids were missing from it (TypeError inside the .then, whose
    // .catch then rejected A) and caller B's own Deferreds never settled.
    const loadPromise2 = nameService.loadDisplayNames("dev", [2, 5]);

    const [displayNames1, displayNames2] = await Promise.all([
        loadPromise1,
        loadPromise2,
    ]);
    expect(displayNames1).toEqual({ 1: "Julien", 4: ERROR_INACCESSIBLE_OR_MISSING });
    expect(displayNames2).toEqual({ 2: "Pierre", 5: ERROR_INACCESSIBLE_OR_MISSING });
    expect.verifySteps(["dev:web_search_read:1,4,2,5"]);

    // The clear stays effective: pre-clear ids are re-fetched afterwards.
    const displayNames3 = await nameService.loadDisplayNames("dev", [1]);
    expect(displayNames3).toEqual({ 1: "Julien" });
    expect.verifySteps(["dev:web_search_read:1"]);
});

test("clearCache during an in-flight batch: RPC failure rejects all callers", async () => {
    await makeMockEnv();
    onRpc("web_search_read", () => {
        expect.step("web_search_read");
        throw makeServerError({ message: "boom" });
    });

    const nameService = getService("name");
    const loadPromise1 = nameService.loadDisplayNames("dev", [1]);
    nameService.clearCache();
    const loadPromise2 = nameService.loadDisplayNames("dev", [2]);

    // Both the pre-clear and post-clear callers get a defined rejection —
    // neither hangs on a Deferred nobody settles.
    await expect(loadPromise1).rejects.toThrow("boom");
    await expect(loadPromise2).rejects.toThrow("boom");
    expect.verifySteps(["web_search_read"]);
});

test("cache is bounded: cold entries evict past NAME_CACHE_LIMIT", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });
    const nameService = getService("name");

    // Fill the cache past the cap without any RPC (addDisplayNames populates
    // the cache directly). Ids are inserted 1..LIMIT+2, so the two coldest
    // (1 and 2) are evicted, leaving the cache at exactly NAME_CACHE_LIMIT.
    const many = {};
    for (let id = 1; id <= NAME_CACHE_LIMIT + 2; id++) {
        many[id] = `Name ${id}`;
    }
    nameService.addDisplayNames("dev", many);

    // A coldest, evicted id is no longer cached -> the lookup re-fetches.
    await nameService.loadDisplayNames("dev", [1]);
    expect.verifySteps(["dev:web_search_read:1"]);

    // A recently-added (warm) id is still cached -> no RPC.
    await nameService.loadDisplayNames("dev", [NAME_CACHE_LIMIT + 2]);
    expect.verifySteps([]);
});

test("a recent lookup keeps its entry warm across later eviction", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });
    const nameService = getService("name");

    // Fill to exactly the cap (ids 1..LIMIT); id 1 is the coldest.
    const many = {};
    for (let id = 1; id <= NAME_CACHE_LIMIT; id++) {
        many[id] = `Name ${id}`;
    }
    nameService.addDisplayNames("dev", many);

    // Touch id 1 (a cache hit, no RPC): it becomes the WARMEST entry.
    await nameService.loadDisplayNames("dev", [1]);
    expect.verifySteps([]);

    // Two fresh ids push the size over the cap twice -> the two current
    // coldest (2 and 3) evict; the just-touched id 1 survives.
    nameService.addDisplayNames("dev", {
        [NAME_CACHE_LIMIT + 1]: "extra a",
        [NAME_CACHE_LIMIT + 2]: "extra b",
    });

    // id 1 survived (was warm) -> served from cache, no RPC.
    await nameService.loadDisplayNames("dev", [1]);
    expect.verifySteps([]);

    // id 2 was evicted -> re-fetched.
    await nameService.loadDisplayNames("dev", [2]);
    expect.verifySteps(["dev:web_search_read:2"]);
});
