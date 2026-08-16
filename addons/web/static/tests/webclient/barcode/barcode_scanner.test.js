// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame, click, press, waitFor } from "@odoo/hoot-dom";
import { advanceTime, Deferred } from "@odoo/hoot-mock";
import {
    contains,
    makeMockEnv,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { scanBarcode } from "@web/components/barcode/barcode_dialog";
import { BarcodeVideoScanner } from "@web/components/barcode/barcode_video_scanner";
import { browser } from "@web/core/browser/browser";
import { WebClient } from "@web/webclient/webclient";

import * as ZXing from "zxing-library";

test("Barcode scanner crop overlay", async () => {
    const env = await makeMockEnv();
    await mountWithCleanup(WebClient, { env });

    const firstBarcodeValue = "Odoo";
    const secondBarcodeValue = "OCDTEST";

    let barcodeToGenerate = firstBarcodeValue;
    let videoReady = new Deferred();

    async function mockUserMedia() {
        const canvas = document.createElement("canvas");
        const ctx = /** @type {CanvasRenderingContext2D} */ (canvas.getContext("2d"));
        const stream = canvas.captureStream();

        const multiFormatWriter = new ZXing.MultiFormatWriter();
        const bitMatrix = multiFormatWriter.encode(
            barcodeToGenerate,
            ZXing.BarcodeFormat.QR_CODE,
            250,
            250,
            null,
        );
        canvas.width = bitMatrix.width;
        canvas.height = bitMatrix.height;
        ctx.strokeStyle = "black";
        ctx.fillStyle = "white";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        for (let x = 0; x < bitMatrix.width; x++) {
            for (let y = 0; y < bitMatrix.height; y++) {
                if (bitMatrix.get(x, y)) {
                    ctx.beginPath();
                    ctx.rect(x, y, 1, 1);
                    ctx.stroke();
                }
            }
        }
        return stream;
    }
    patchWithCleanup(browser.navigator, {
        mediaDevices: /** @type {any} */ ({
            getUserMedia: mockUserMedia,
        }),
    });

    patchWithCleanup(BarcodeVideoScanner.prototype, {
        async isVideoReady() {
            const result = await super.isVideoReady(...arguments);
            videoReady.resolve();
            return result;
        },
        onResize(overlayInfo) {
            expect.step(overlayInfo);
            return super.onResize(...arguments);
        },
    });

    const firstBarcodeFound = scanBarcode(env);
    await videoReady;
    await animationFrame();
    await contains(".o_crop_icon").dragAndDrop(".o_crop_container", {
        relative: true,
        position: {
            x: 0,
            y: 0,
        },
    });

    const firstValueScanned = await firstBarcodeFound;
    expect(firstValueScanned).toBe(firstBarcodeValue, {
        message: `The detected barcode (${firstValueScanned}) should be the same as generated (${firstBarcodeValue})`,
    });

    barcodeToGenerate = secondBarcodeValue;
    videoReady = new Deferred();

    const secondBarcodeFound = scanBarcode(env);
    await videoReady;
    await animationFrame();
    const secondValueScanned = await secondBarcodeFound;
    expect(secondValueScanned).toBe(secondBarcodeValue, {
        message: `The detected barcode (${secondValueScanned}) should be the same as generated (${secondBarcodeValue})`,
    });

    expect.verifySteps([
        { x: 25, y: 100, width: 200, height: 50 },
        { x: 0, y: 0, width: 250, height: 250 },
        { x: 0, y: 0, width: 250, height: 250 },
    ]);
});

test("BarcodeVideoScanner onReady props", async () => {
    async function mockUserMedia() {
        const canvas = document.createElement("canvas");
        const ctx = /** @type {CanvasRenderingContext2D} */ (canvas.getContext("2d"));
        const stream = canvas.captureStream();
        canvas.width = 250;
        canvas.height = 250;
        ctx.strokeStyle = "black";
        ctx.fillStyle = "white";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        return stream;
    }
    patchWithCleanup(browser.navigator, {
        mediaDevices: /** @type {any} */ ({
            getUserMedia: mockUserMedia,
        }),
    });
    const resolvedOnReadyPromise = new Promise((resolve) => {
        mountWithCleanup(BarcodeVideoScanner, {
            props: {
                facingMode: "environment",
                onReady: () => resolve(true),
                onResult: () => {},
                onError: () => {},
            },
        });
    });
    expect(await resolvedOnReadyPromise).toBe(true);
});

test("Closing barcode scanner before camera loads should not throw an error", async () => {
    const env = await makeMockEnv();
    await mountWithCleanup(WebClient, { env });
    const cameraReady = new Deferred();

    patchWithCleanup(browser.navigator, {
        mediaDevices: /** @type {any} */ ({
            async getUserMedia() {
                await cameraReady;
                const canvas = document.createElement("canvas");
                return canvas.captureStream();
            },
        }),
    });

    scanBarcode(env);

    await waitFor(".o-barcode-modal");
    expect(".o-barcode-modal").toHaveCount(1);

    await press("escape");

    await animationFrame();
    expect(".o-barcode-modal").toHaveCount(0);

    cameraReady.resolve();

    await animationFrame();
    expect(".o_error_dialog").toHaveCount(0);
});

test("Closing the barcode dialog manually resolves the scan promise with null", async () => {
    const env = await makeMockEnv();
    await mountWithCleanup(WebClient, { env });

    patchWithCleanup(browser.navigator, {
        mediaDevices: /** @type {any} */ ({
            async getUserMedia() {
                const canvas = document.createElement("canvas");
                return canvas.captureStream();
            },
        }),
    });

    const escScan = scanBarcode(env);

    // Opening the scanner dialog goes through getUserMedia, so wait for the
    // dialog rather than for a fixed number of frames.
    await waitFor(".o-barcode-modal");
    expect(".o-barcode-modal").toHaveCount(1);

    await press("escape");

    await animationFrame();
    expect(".o-barcode-modal").toHaveCount(0);
    expect(await escScan).toBe(null);

    const closeButtonScan = scanBarcode(env);

    await waitFor(".o-barcode-modal");
    expect(".o-barcode-modal").toHaveCount(1);

    await click(".o-barcode-modal .modal-header button[aria-label='Close']");

    await animationFrame();
    expect(".o-barcode-modal").toHaveCount(0);
    expect(await closeButtonScan).toBe(null);
});

test("Closing barcode scanner while video is loading should not cause errors", async () => {
    const env = await makeMockEnv();
    await mountWithCleanup(WebClient, { env });

    patchWithCleanup(browser.navigator, {
        mediaDevices: /** @type {any} */ ({
            async getUserMedia() {
                const canvas = document.createElement("canvas");
                return canvas.captureStream();
            },
        }),
    });

    scanBarcode(env);

    await waitFor(".o-barcode-modal");
    expect(".o-barcode-modal").toHaveCount(1);

    await press("escape");

    await animationFrame();
    expect(".o-barcode-modal").toHaveCount(0);

    await animationFrame();
    expect(".o_error_dialog").toHaveCount(0);
});

/**
 * A camera that produces a real (blank) stream, so the component's readiness
 * poll settles the way it does against a device.
 */
function mockBlankCamera() {
    patchWithCleanup(browser.navigator, {
        mediaDevices: /** @type {any} */ ({
            getUserMedia() {
                const canvas = document.createElement("canvas");
                canvas.width = 250;
                canvas.height = 250;
                const ctx = /** @type {CanvasRenderingContext2D} */ (
                    canvas.getContext("2d")
                );
                ctx.fillStyle = "white";
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                return canvas.captureStream();
            },
        }),
    });
}

/**
 * @param {() => any} onDetect what `detect()` does on each call
 */
function mockDetector(onDetect) {
    class ScriptedDetector {
        static async getSupportedFormats() {
            return ["qr_code"];
        }
        async detect() {
            return onDetect();
        }
    }
    patchWithCleanup(window, { BarcodeDetector: ScriptedDetector });
}

async function mountScanner(/** @type {any} */ props) {
    const ready = new Deferred();
    await mountWithCleanup(BarcodeVideoScanner, {
        props: {
            facingMode: "environment",
            onReady: () => ready.resolve(),
            onResult: () => {},
            onError: () => {},
            ...props,
        },
    });
    await ready;
    return ready;
}

test("the scan loop gives up after five consecutive detector failures", async () => {
    mockBlankCamera();
    let attempts = 0;
    mockDetector(() => {
        attempts++;
        throw new Error("detector unavailable");
    });

    /** @type {any[]} */
    const errors = [];
    await mountScanner({ onError: (/** @type {any} */ e) => errors.push(e) });

    // Five failures in a row is the threshold: the fifth reports and stops.
    for (let i = 0; i < 8; i++) {
        await advanceTime(100);
    }
    expect(errors.length).toBe(1);
    expect(attempts).toBe(5);

    // The loop is over, so nothing keeps trying behind the reported error.
    const settled = attempts;
    await advanceTime(500);
    expect(attempts).toBe(settled);
});

test("a successful read clears the failure count", async () => {
    mockBlankCamera();
    let attempts = 0;
    mockDetector(() => {
        attempts++;
        // fail, fail, fail, fail, succeed, then fail four more
        if (attempts === 5) {
            return [];
        }
        throw new Error("transient");
    });

    /** @type {any[]} */
    const errors = [];
    await mountScanner({ onError: (/** @type {any} */ e) => errors.push(e) });

    for (let i = 0; i < 9; i++) {
        await advanceTime(100);
    }
    // Nine attempts, but never five bad ones in a row.
    expect(attempts).toBe(9);
    expect(errors).toEqual([]);
});
