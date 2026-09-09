// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { Deferred } from "@odoo/hoot-mock";
import { Component, useState, xml } from "@odoo/owl";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { BarcodeVideoScanner } from "@web/components/barcode/barcode_video_scanner";
import { browser } from "@web/core/browser/browser";

/** @param {number} size */
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

/** @param {any[]} cropAreas */
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
        /** @returns {Promise<never[]>} */
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
        /** @type {{size: number}} */
        state;
        setup() {
            this.ready = ready;
            this.state = useState({ size: 100 });
        }
    }
    const host = await mountWithCleanup(Host);
    await ready;
    await animationFrame();

    expect(cropAreas.length).toBe(1);
    expect(cropAreas[0].width).toBe(320);
    expect(cropAreas[0].height).toBe(80);

    host.state.size = 200;
    await animationFrame();
    await animationFrame();
    expect(cropAreas.length).toBe(2);
    expect(cropAreas[1].width).toBe(40);
    expect(cropAreas[1].height).toBe(160);
});
