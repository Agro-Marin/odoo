/** @odoo-module native */
import { Component } from "@odoo/owl";
import { isBarcodeScannerSupported, scanBarcode } from "@web/components/barcode";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";

/**
 * Run a camera scan and report a genuine failure, but not a cancellation.
 *
 * `scanBarcode` rejects only when scanning actually failed: closing the dialog
 * resolves with null (see `onClose` in web's `barcode_dialog`). Treating every
 * falsy result as a failure told a user who had deliberately shut the scanner
 * to "Please, Scan again!" -- on an attendance kiosk or an event desk, backing
 * out is a normal action, not an error.
 *
 * @param {() => Promise<string|null>} scan opens the scanner and resolves with
 *      the barcode, or null if the dialog was closed without one
 * @param {object} notification the notification service
 * @returns {Promise<string|null>} the barcode, or null if there was none
 */
export async function scanBarcodeOrWarn(scan, notification) {
    let barcode;
    try {
        barcode = await scan();
    } catch (error) {
        notification.add(error?.message || _t("Please, Scan again!"), {
            type: "warning",
        });
        return null;
    }
    if (!barcode) {
        // The dialog was closed without a scan. That is the user's decision.
        return null;
    }
    navigator.vibrate?.(100);
    return barcode;
}

export class BarcodeScanner extends Component {
    static template = "barcodes.BarcodeScanner";
    static props = {
        onBarcodeScanned: { type: Function },
    };

    setup() {
        this.notification = useService("notification");
        this.isBarcodeScannerSupported = isBarcodeScannerSupported();
        // Kept as an instance property: `hr_attendance`'s kiosk subclass swaps
        // it, and its `facingMode` override is read through it at call time.
        this.scanBarcode = () => scanBarcode(this.env, this.facingMode);
    }

    get facingMode() {
        return "environment";
    }

    async openMobileScanner() {
        const barcode = await scanBarcodeOrWarn(this.scanBarcode, this.notification);
        if (barcode) {
            this.props.onBarcodeScanned(barcode);
        }
    }
}
