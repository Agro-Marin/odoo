import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { BlurManager } from "@mail/discuss/call/common/blur_manager";
import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

describe.current.tags("desktop");
defineMailModels();

/**
 * The real segmentation model is a CDN library that is not loaded in tests.
 * BlurManager only ever calls these three methods on it.
 */
function mockSelfieSegmentation() {
    class MockSelfieSegmentation {
        close() {}
        onResults() {}
        send() {
            return Promise.resolve();
        }
        setOptions() {}
    }
    patchWithCleanup(window, { SelfieSegmentation: MockSelfieSegmentation });
}

/** Observe tick worker construction without actually spawning one. */
function mockWorker() {
    const built = [];
    class MockWorker {
        constructor(url) {
            built.push(url);
        }
        postMessage() {}
        terminate() {}
    }
    patchWithCleanup(window, { Worker: MockWorker });
    return built;
}

/**
 * @param {boolean} available whether the browser exposes requestVideoFrameCallback
 */
function patchVideoFrameCallback(available) {
    const proto = HTMLVideoElement.prototype;
    const original = Object.getOwnPropertyDescriptor(proto, "requestVideoFrameCallback");
    if (available) {
        Object.defineProperty(proto, "requestVideoFrameCallback", {
            configurable: true,
            value() {},
            writable: true,
        });
    } else {
        delete proto.requestVideoFrameCallback;
    }
    return () => {
        if (original) {
            Object.defineProperty(proto, "requestVideoFrameCallback", original);
        } else {
            delete proto.requestVideoFrameCallback;
        }
    };
}

test("no tick worker is spawned when requestVideoFrameCallback is available", async () => {
    mockSelfieSegmentation();
    const built = mockWorker();
    const restore = patchVideoFrameCallback(true);
    let manager;
    try {
        manager = new BlurManager(new MediaStream());
        // close() rejects this promise; nothing consumes it in this test.
        manager.stream.catch(() => {});
        expect(built).toEqual([]);
        expect(manager.worker).toBe(null);
    } finally {
        manager?.close();
        restore();
    }
});

test("the tick worker is still spawned when requestVideoFrameCallback is missing", async () => {
    mockSelfieSegmentation();
    const built = mockWorker();
    const restore = patchVideoFrameCallback(false);
    let manager;
    try {
        manager = new BlurManager(new MediaStream());
        manager.stream.catch(() => {});
        expect(built).toEqual(["/mail/static/src/discuss/call/common/tick_worker.js"]);
        expect(manager.worker).not.toBe(null);
    } finally {
        manager?.close();
        restore();
    }
});
