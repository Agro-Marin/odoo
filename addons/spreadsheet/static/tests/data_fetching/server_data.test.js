import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import {
    BatchEndpoint,
    Request,
    ServerData,
} from "@spreadsheet/data_sources/server_data";
import { LoadingDataError } from "@spreadsheet/o_spreadsheet/errors";
import { Deferred } from "@web/core/utils/concurrency";

import { defineSpreadsheetActions, defineSpreadsheetModels } from "../helpers/data.js";

describe.current.tags("headless");

defineSpreadsheetModels();
defineSpreadsheetActions();

test("simple synchronous get", async () => {
    const orm = {
        call: async (model, method, args) => {
            expect.step(`${model}/${method}`);
            return args[0];
        },
    };
    const serverData = new ServerData(orm, {
        whenDataStartLoading: () => expect.step("data-fetching-notification"),
    });
    expect(() => serverData.get("partner", "get_something", [5])).toThrow(
        LoadingDataError,
        {
            message: "it should throw when it's not loaded",
        },
    );
    expect.verifySteps(["partner/get_something", "data-fetching-notification"]);
    await animationFrame();
    expect(serverData.get("partner", "get_something", [5])).toBe(5);
    expect.verifySteps([]);
});

test("synchronous get which returns an error", async () => {
    const orm = {
        call: async (model, method, args) => {
            expect.step(`${model}/${method}`);
            throw new Error("error while fetching data");
        },
    };
    const serverData = new ServerData(orm, {
        whenDataStartLoading: () => expect.step("data-fetching-notification"),
    });
    expect(() => serverData.get("partner", "get_something", [5])).toThrow(
        LoadingDataError,
        {
            message: "it should throw when it's not loaded",
        },
    );
    expect.verifySteps(["partner/get_something", "data-fetching-notification"]);
    await animationFrame();
    expect(() => serverData.get("partner", "get_something", [5])).toThrow(Error);
    expect.verifySteps([]);
});

test("batch get with a single item", async () => {
    const deferred = new Deferred();
    const orm = {
        call: async (model, method, args) => {
            await deferred;
            expect.step(`${model}/${method}`);
            return args[0];
        },
    };
    const serverData = new ServerData(orm, {
        whenDataStartLoading: () => expect.step("data-fetching-notification"),
    });
    expect(() => serverData.batch.get("partner", "get_something_in_batch", 5)).toThrow(
        LoadingDataError,
        { message: "it should throw when it's not loaded" },
    );
    await animationFrame(); // wait for the next tick for the batch to be called
    expect.verifySteps(["data-fetching-notification"]);
    deferred.resolve();
    await animationFrame();
    expect.verifySteps(["partner/get_something_in_batch"]);
    expect(serverData.batch.get("partner", "get_something_in_batch", 5)).toBe(5);
    expect.verifySteps([]);
});

test("batch get with multiple items", async () => {
    const orm = {
        call: async (model, method, args) => {
            expect.step(`${model}/${method}`);
            return args[0];
        },
    };
    const serverData = new ServerData(orm, {
        whenDataStartLoading: () => expect.step("data-fetching-notification"),
    });
    expect(() => serverData.batch.get("partner", "get_something_in_batch", 5)).toThrow(
        LoadingDataError,
        { message: "it should throw when it's not loaded" },
    );
    expect(() => serverData.batch.get("partner", "get_something_in_batch", 6)).toThrow(
        LoadingDataError,
        { message: "it should throw when it's not loaded" },
    );
    await animationFrame();
    expect.verifySteps([
        "partner/get_something_in_batch",
        "data-fetching-notification",
    ]);
    expect(serverData.batch.get("partner", "get_something_in_batch", 5)).toBe(5);
    expect(serverData.batch.get("partner", "get_something_in_batch", 6)).toBe(6);
    expect.verifySteps([]);
});

test("a batch the server could not answer at all fails as a whole", async () => {
    // The client no longer retries request by request: a batch that fails
    // outright is a server or development error, and every request in it gets
    // the same explanatory message instead of N further round trips.
    const orm = {
        call: async (model, method, args) => {
            expect.step(`${model}/${method}`);
            if (args[0].includes(5)) {
                throw new Error("error while fetching data");
            }
            return args[0];
        },
    };
    const serverData = new ServerData(orm, {
        whenDataStartLoading: () => expect.step("data-fetching-notification"),
    });
    for (const id of [4, 5, 6]) {
        expect(() => serverData.batch.get("partner", "get_something_in_batch", id)).toThrow(
            LoadingDataError,
            { message: "it should throw when it's not loaded" },
        );
    }
    await animationFrame();
    expect.verifySteps([
        // a single call for the batch, and no retry one by one
        "partner/get_something_in_batch",
        "data-fetching-notification",
    ]);
    for (const id of [4, 5, 6]) {
        expect(() => serverData.batch.get("partner", "get_something_in_batch", id)).toThrow(
            Error,
        );
    }
    expect.verifySteps([]);
});

test("a request the server marks as failed does not sink its batch", async () => {
    // The server isolates a per-request UserError and answers the batch with
    // an `__error__` entry in its place, so the healthy requests keep their
    // values and the whole thing still costs one call.
    const orm = {
        call: async (model, method, args) => {
            expect.step(`${model}/${method}`);
            return args[0].map((id) =>
                id === 5 ? { __error__: "no such thing" } : id,
            );
        },
    };
    const serverData = new ServerData(orm, {
        whenDataStartLoading: () => expect.step("data-fetching-notification"),
    });
    for (const id of [4, 5, 6]) {
        expect(() => serverData.batch.get("partner", "get_something_in_batch", id)).toThrow(
            LoadingDataError,
        );
    }
    await animationFrame();
    expect.verifySteps([
        "partner/get_something_in_batch",
        "data-fetching-notification",
    ]);
    expect(serverData.batch.get("partner", "get_something_in_batch", 4)).toBe(4);
    // the failing entry surfaces as an evaluation error carrying the server's
    // own message, not as a plain Error
    let thrown;
    try {
        serverData.batch.get("partner", "get_something_in_batch", 5);
    } catch (error) {
        thrown = error;
    }
    expect(thrown?.message).toBe("no such thing");
    expect(serverData.batch.get("partner", "get_something_in_batch", 6)).toBe(6);
    expect.verifySteps([]);
});

test("concurrently get and batch get the same request", async () => {
    const orm = {
        call: async (model, method, args) => {
            expect.step(`${model}/${method}`);
            return args[0];
        },
    };
    const serverData = new ServerData(orm, {
        whenDataStartLoading: () => expect.step("data-fetching-notification"),
    });
    expect(() => serverData.batch.get("partner", "get_something", 5)).toThrow(
        LoadingDataError,
    );
    expect(() => serverData.get("partner", "get_something", [5])).toThrow(
        LoadingDataError,
    );
    await animationFrame();
    // it should have fetch the data once
    expect.verifySteps(["partner/get_something", "data-fetching-notification"]);
    expect(serverData.get("partner", "get_something", [5])).toBe(5);
    expect(serverData.batch.get("partner", "get_something", 5)).toBe(5);
    expect.verifySteps([]);
});

test("Call the correct callback after a batch result", async () => {
    const orm = {
        call: async (model, method, args) =>
            args[0].map((arg) =>
                arg === 5 ? { __error__: "invalid value 5" } : arg,
            ),
    };
    const batchEndpoint = new BatchEndpoint(orm, "partner", "get_something", {
        whenDataStartLoading: () => {},
        successCallback: () => expect.step("success-callback"),
        failureCallback: () => expect.step("failure-callback"),
    });
    const request = new Request("partner", "get_something", [4]);
    const request2 = new Request("partner", "get_something", [5]);
    batchEndpoint.call(request);
    batchEndpoint.call(request2);
    expect.verifySteps([]);
    await animationFrame();
    expect.verifySteps(["success-callback", "failure-callback"]);
});
