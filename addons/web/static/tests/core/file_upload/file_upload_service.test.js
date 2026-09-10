// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
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
 * @param {{ status?: number, responseText?: string, responseURL?: string }} response
 * @returns {{ fire: (type: string) => void }}
 */
function mockXhr({ status = 200, responseText = "", responseURL = ROUTE }) {
    const xhr = new XMLHttpRequest();
    patchWithCleanup(xhr, {
        send() {},
        getResponseHeader: () => "text/html; charset=utf-8",
        get responseURL() {
            return responseURL;
        },
        get status() {
            return status;
        },
        get responseText() {
            return responseText;
        },
    });
    patchWithCleanup(fileUploadService, { createXhr: () => xhr });
    return { fire: (type) => xhr.dispatchEvent(new Event(type)) };
}

/**
 * @param {{ status?: number, responseText?: string, responseURL?: string }} response
 * @returns {Promise<string[]>}
 */
async function uploadAndSettle(response) {
    mockService("notification", {
        add: () => () => {},
    });
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
    expect(
        await uploadAndSettle({
            responseText: "<!DOCTYPE html><html><body>Log in</body></html>",
            responseURL: `/web/login?redirect=${encodeURIComponent(ROUTE)}`,
        }),
    ).toEqual(["ERROR"]);
});

test("a same-route response is never treated as a redirect", async () => {
    expect(
        await uploadAndSettle({
            responseText: JSON.stringify([{ id: 1 }]),
            responseURL: `http://127.0.0.1:8069${ROUTE}`,
        }),
    ).toEqual(["LOADED"]);
});

test("an empty responseURL does not fail the upload", async () => {
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

test("cancelling a cloud upload aborts the request to the cloud, not the metadata post", async () => {
    mockService("notification", { add: () => () => {} });
    /** @type {XMLHttpRequest[]} */
    const xhrs = [];
    patchWithCleanup(fileUploadService, {
        createXhr: () => {
            const xhr = new XMLHttpRequest();
            patchWithCleanup(xhr, {
                send() {},
                abort() {
                    expect.step("xhr.abort");
                    this.dispatchEvent(new Event("abort"));
                },
                getResponseHeader: () => "application/json",
                get responseURL() {
                    return ROUTE;
                },
                get status() {
                    return 200;
                },
                get responseText() {
                    return JSON.stringify({
                        upload_info: {
                            url: "https://cloud.test/put",
                            method: "PUT",
                            response_status: 200,
                        },
                    });
                },
            });
            xhrs.push(xhr);
            return xhr;
        },
    });
    await makeMockEnv();
    const fileUpload = getService("file_upload");
    fileUpload.bus.addEventListener(FileUploadEvent.ERROR, ({ detail }) =>
        expect.step(`settled:${detail.upload.state}`),
    );
    const file = new File(["x"], "doc.txt", { type: "text/plain" });
    const upload = await fileUpload.upload(ROUTE, [file], { directFile: file });
    xhrs[0].dispatchEvent(new Event("load"));
    await animationFrame();
    expect(xhrs).toHaveLength(2);
    expect(upload.xhr).toBe(xhrs[1]);

    upload.xhr.abort();
    await animationFrame();
    expect.verifySteps(["xhr.abort", "settled:abort"]);
});
