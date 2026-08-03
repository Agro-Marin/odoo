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
import {
    ERROR_INACCESSIBLE_OR_MISSING,
    NAME_CACHE_LIMIT,
} from "@web/core/name_service";
import { rpcBus } from "@web/core/network/rpc";

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
    const loadPromise = nameService.loadDisplayNames("dev", [1]);
    nameService.addDisplayNames("dev", { 1: "JUM" });
    expect(await loadPromise).toEqual({ 1: "JUM" });
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
        // Deliberately invalid: the point of the test is the runtime guard.
        // `loadDisplayNames` takes `number[]`, and that only became checkable
        // when the service stopped typing its surface as bare `Function`.
        await getService("name").loadDisplayNames("dev", /** @type {any} */ (["a"]));
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
    const loadPromise1 = nameService.loadDisplayNames("dev", [1, 4]);
    nameService.clearCache();
    const loadPromise2 = nameService.loadDisplayNames("dev", [2, 5]);

    const [displayNames1, displayNames2] = await Promise.all([
        loadPromise1,
        loadPromise2,
    ]);
    expect(displayNames1).toEqual({ 1: "Julien", 4: ERROR_INACCESSIBLE_OR_MISSING });
    expect(displayNames2).toEqual({ 2: "Pierre", 5: ERROR_INACCESSIBLE_OR_MISSING });
    expect.verifySteps(["dev:web_search_read:1,4,2,5"]);

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

    /** @type {Record<string, string>} */
    const many = {};
    for (let id = 1; id <= NAME_CACHE_LIMIT + 2; id++) {
        many[id] = `Name ${id}`;
    }
    nameService.addDisplayNames("dev", many);

    await nameService.loadDisplayNames("dev", [1]);
    expect.verifySteps(["dev:web_search_read:1"]);

    await nameService.loadDisplayNames("dev", [NAME_CACHE_LIMIT + 2]);
    expect.verifySteps([]);
});

test("a recent lookup keeps its entry warm across later eviction", async () => {
    await makeMockEnv();
    onRpc(({ model, method, kwargs }) => {
        expect.step(`${model}:${method}:${kwargs.domain[0][2]}`);
    });
    const nameService = getService("name");

    /** @type {Record<string, string>} */
    const many = {};
    for (let id = 1; id <= NAME_CACHE_LIMIT; id++) {
        many[id] = `Name ${id}`;
    }
    nameService.addDisplayNames("dev", many);

    await nameService.loadDisplayNames("dev", [1]);
    expect.verifySteps([]);

    nameService.addDisplayNames("dev", {
        [NAME_CACHE_LIMIT + 1]: "extra a",
        [NAME_CACHE_LIMIT + 2]: "extra b",
    });

    await nameService.loadDisplayNames("dev", [1]);
    expect.verifySteps([]);

    await nameService.loadDisplayNames("dev", [2]);
    expect.verifySteps(["dev:web_search_read:2"]);
});
