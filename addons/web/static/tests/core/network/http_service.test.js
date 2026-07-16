// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { mockFetch } from "@odoo/hoot-mock";
import {
    ConnectionLostError,
    InvalidResponseError,
    NetworkError,
    RequestEntityTooLargeError,
} from "@web/core/network/rpc";
import { get, post } from "@web/services/http_service";

describe.current.tags("headless");

test("method is correctly set", async () => {
    mockFetch((_, { method }) => expect.step(method));

    await get("/call_get");
    expect.verifySteps(["GET"]);

    await post("/call_post");
    expect.verifySteps(["POST"]);
});

test("check status 502", async () => {
    mockFetch(() => new Response("{}", { status: 502 }));

    // Classified as ConnectionLostError (rpc.js hierarchy) with the status
    // in the message, so callers and error handlers can branch on it.
    const promise = get("/custom_route");
    await expect(promise).rejects.toThrow(ConnectionLostError);
    await promise.catch((e) => expect(e.message).toMatch(/HTTP 502/));
});

test("check status 413", async () => {
    mockFetch(() => new Response("{}", { status: 413 }));

    await expect(get("/custom_route")).rejects.toThrow(RequestEntityTooLargeError);
});

test("a 200 HTML body (session-expired login redirect) is an InvalidResponseError", async () => {
    // fetch follows redirects, so a session-expired request lands on the
    // HTML login page with a 200. Pre-classification, response.json() died
    // on it with a raw SyntaxError (ClientErrorDialog); InvalidResponseError
    // routes it to the session-expired flow, like rpc.js.
    mockFetch(
        () =>
            new Response("<!DOCTYPE html><html><body>login</body></html>", {
                status: 200,
                headers: { "Content-Type": "text/html; charset=utf-8" },
            }),
    );

    await expect(get("/custom_route")).rejects.toThrow(InvalidResponseError);
    await expect(post("/custom_route")).rejects.toThrow(InvalidResponseError);
});

test("an explicit non-json readMethod still reads HTML bodies", async () => {
    // The HTML sniff only applies when the caller asked for JSON: fetching
    // an HTML page as text is a legitimate use.
    mockFetch(
        () =>
            new Response("<html>ok</html>", {
                status: 200,
                headers: { "Content-Type": "text/html" },
            }),
    );

    expect(await get("/custom_route", "text")).toBe("<html>ok</html>");
});

test("other non-ok statuses raise a NetworkError with status and url", async () => {
    mockFetch(() => new Response("<html>error page</html>", { status: 500 }));

    const promise = get("/custom_route");
    await expect(promise).rejects.toThrow(NetworkError);
    await promise.catch((e) => expect(e.message).toMatch(/HTTP 500/));
});

test("FormData is built by post", async () => {
    mockFetch((_, { body }) => {
        expect(body).toBeInstanceOf(FormData);
        expect(body.get("s")).toBe("1");
        expect(body.get("a")).toBe("1");
        expect(body.getAll("a")).toEqual(["1", "2", "3"]);
        // An empty array appends nothing (it used to serialize to "").
        expect(body.has("empty")).toBe(false);
    });

    await post("call_post", { s: 1, a: [1, 2, 3], empty: [] });
});

test("FormData is given to post", async () => {
    const formData = new FormData();
    mockFetch((_, { body }) => expect(body).toBe(formData));

    await post("/call_post", formData);
});
