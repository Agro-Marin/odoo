/** @odoo-module native */

import {
    BarcodeScanner,
    scanBarcodeOrWarn,
} from "@barcodes/components/barcode_scanner";
import { expect, test } from "@odoo/hoot";
import { waitFor } from "@odoo/hoot-dom";
import { Component, xml } from "@odoo/owl";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";

test.tags("desktop");
test("Display notification for media device permission on barcode scanning", async () => {
    navigator.mediaDevices.getUserMedia = function () {
        return Promise.reject(new DOMException("", "NotAllowedError"));
    };

    class BarcodeScan extends Component {
        static template = xml`
            <div>
                <BarcodeScanner onBarcodeScanned="(ev) => this.onBarcodeScanned(ev)"/>
            </div>
        `;
        static components = { BarcodeScanner };
        static props = ["*"];
    }

    await mountWithCleanup(BarcodeScan);
    await contains("a.o_mobile_barcode").click();
    await waitFor(".modal-body:contains(camera)");
    expect(".modal-body").toHaveText(
        "Unable to access camera\nCould not start scanning. Odoo needs your authorization first.",
    );
});

test.tags("desktop");
test("closing the scanner is not reported back as a failure", async () => {
    // `scanBarcode` resolves with null when the dialog is closed and rejects
    // only on a real failure, so the two must not share a branch: backing out
    // of an attendance kiosk or an event desk is a normal action.
    const notified = [];
    const notification = {
        add: (message, options) => notified.push([message, options.type]),
    };

    expect(await scanBarcodeOrWarn(async () => null, notification)).toBe(null);
    expect(notified).toEqual([]);

    expect(await scanBarcodeOrWarn(async () => "12345670", notification)).toBe(
        "12345670",
    );
    expect(notified).toEqual([]);

    const failed = await scanBarcodeOrWarn(async () => {
        throw new Error("camera is on fire");
    }, notification);
    expect(failed).toBe(null);
    expect(notified).toEqual([["camera is on fire", "warning"]]);
});

test.tags("desktop");
test("a failure with no message still tells the user something", async () => {
    const notified = [];
    const notification = {
        add: (message, options) => notified.push([message, options.type]),
    };
    await scanBarcodeOrWarn(async () => {
        throw "not an Error";
    }, notification);
    expect(notified).toEqual([["Please, Scan again!", "warning"]]);
});
