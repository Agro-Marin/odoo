// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    getService,
    makeMockEnv,
    mockService,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { FileUploadEvent } from "@web/core/events";
import { fileUploadService } from "@web/core/file_upload/file_upload_service";

describe.current.tags("headless");

const ROUTE = "/web/binary/upload_attachment";

/**
 * Fake XHR whose `load` event the test fires by hand.
 *
 * Defaults reproduce what a live Odoo server actually returns for this route
 * (verified with a browser XHR against a running server): a SUCCESSFUL upload
 * is `200 text/html` carrying a JSON string, because it is a `type="http"`
 * route returning `json_dumps(...)`. The content-type is therefore NOT a usable
 * signal — an expired session answers `200 text/html` too. Only `responseURL`
 * distinguishes them.
 *
 * @param {{ status?: number, responseText?: string, responseURL?: string }} response
 * @returns {{ fire: (type: string) => void }}
 */
function mockXhr({ status = 200, responseText = "", responseURL = ROUTE }) {
    /** @type {Record<string, Function>} */
    const listeners = {};
    const xhr = {
        upload: { addEventListener() {} },
        addEventListener(/** @type {string} */ type, /** @type {Function} */ cb) {
            listeners[type] = cb;
        },
        open() {},
        send() {},
        getResponseHeader: () => "text/html; charset=utf-8",
        responseURL,
        status,
        responseText,
    };
    patchWithCleanup(fileUploadService, { createXhr: () => xhr });
    return { fire: (type) => listeners[type]?.() };
}

/**
 * @param {{ status?: number, responseText?: string, responseURL?: string }} response
 * @returns {Promise<string[]>} the bus events emitted for the upload
 */
async function uploadAndSettle(response) {
    mockService("notification", { add: () => {} });
    const { fire } = mockXhr(response);
    await makeMockEnv();
    const fileUpload = getService("file_upload");
    /** @type {string[]} */
    const events = [];
    fileUpload.bus.addEventListener(FileUploadEvent.LOADED, () =>
        events.push("LOADED"),
    );
    fileUpload.bus.addEventListener(FileUploadEvent.ERROR, () => events.push("ERROR"));
    await fileUpload.upload(ROUTE, [
        new File(["x"], "doc.txt", { type: "text/plain" }),
    ]);
    fire("load");
    return events;
}

test("a successful upload completes (200 text/html carrying JSON)", async () => {
    expect(
        await uploadAndSettle({
            responseText: JSON.stringify([{ filename: "doc.txt", id: 1, size: 1 }]),
        }),
    ).toEqual(["LOADED"]);
});

test("an expired session (redirected to the login page) fails the upload", async () => {
    // The login page is 200 text/html, same as a success. It parses into a
    // Document, satisfies `instanceof Object`, has no `.error`, and used to be
    // reported LOADED — the user's file silently discarded with a success
    // indication. The redirect is what gives it away.
    expect(
        await uploadAndSettle({
            responseText: "<!DOCTYPE html><html><body>Log in</body></html>",
            responseURL: `/web/login?redirect=${encodeURIComponent(ROUTE)}`,
        }),
    ).toEqual(["ERROR"]);
});

test("a same-route response is never treated as a redirect", async () => {
    // Guards against over-reach: an absolute responseURL for the very route we
    // posted to (what the browser actually reports) must not fail the upload.
    expect(
        await uploadAndSettle({
            responseText: JSON.stringify([{ id: 1 }]),
            responseURL: `http://127.0.0.1:8069${ROUTE}`,
        }),
    ).toEqual(["LOADED"]);
});

test("an empty responseURL does not fail the upload", async () => {
    // Not every XHR implementation exposes it; absence must stay non-fatal.
    expect(
        await uploadAndSettle({
            responseText: JSON.stringify([{ id: 1 }]),
            responseURL: "",
        }),
    ).toEqual(["LOADED"]);
});

test("a JSON-RPC error payload fails the upload", async () => {
    expect(
        await uploadAndSettle({
            responseText: JSON.stringify({
                error: { data: { name: "AccessError", message: "nope" } },
            }),
        }),
    ).toEqual(["ERROR"]);
});
