// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { Deferred } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BarcodeVideoScanner } from "@web/components/barcode/barcode_video_scanner";
import { browser } from "@web/core/browser/browser";

/**
 * A camera whose frames are four times the preview: the preview below is
 * boxed at 100x100 while the track reports 400x400.
 *
 * @param {number} size
 */
function mockCamera(size) {
    patchWithCleanup(browser.navigator, {
        mediaDevices: /** @type {any} */ ({
            getUserMedia() {
                const canvas = document.createElement("canvas");
                canvas.width = size;
                canvas.height = size;
                const ctx = /** @type {CanvasRenderingContext2D} */ (
                    canvas.getContext("2d")
                );
                ctx.fillStyle = "white";
                ctx.fillRect(0, 0, size, size);
                return canvas.captureStream();
            },
        }),
    });
}

/**
 * @param {any[]} cropAreas
 */
function mockSourceCroppingDetector(cropAreas) {
    class CroppingDetector {
        static cropsAtSource = true;
        static async getSupportedFormats() {
            return ["qr_code"];
        }
        /** @param {any} area */
        setCropArea(area) {
            cropAreas.push(area);
        }
        async detect() {
            return [];
        }
    }
    patchWithCleanup(browser, { BarcodeDetector: CroppingDetector });
}

test("the crop area follows the preview's size, in source pixels", async () => {
    mockCamera(400);
    /** @type {any[]} */
    const cropAreas = [];
    mockSourceCroppingDetector(cropAreas);
    const ready = new Deferred();

    class Host extends Component {
        static props = {};
        static components = { BarcodeVideoScanner };
        static template = xml`
            <div t-attf-style="width: {{ state.size }}px; height: {{ state.size }}px;">
                <BarcodeVideoScanner facingMode="'environment'"
                    onReady="() => this.ready.resolve()"
                    onResult="() => {}" onError="() => {}"/>
            </div>`;
        setup() {
            this.ready = ready;
            this.state = useState({ size: 100 });
        }
    }
    const host = await mountWithCleanup(Host);
    await ready;
    await animationFrame();

    // The overlay publishes its area in preview pixels; the detector crops the
    // source, four times wider than the 100px preview.
    expect(cropAreas.length).toBe(1);
    expect(cropAreas[0].width).toBe(320);
    expect(cropAreas[0].height).toBe(80);

    // Twice the preview is half the ratio: the source is unchanged, so the
    // same overlay geometry must now map onto it through 2, not 4.
    host.state.size = 200;
    await animationFrame();
    await animationFrame();
    expect(cropAreas.length).toBe(2);
    expect(cropAreas[1].width).toBe(40);
    expect(cropAreas[1].height).toBe(160);
});
