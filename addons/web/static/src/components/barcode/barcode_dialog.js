// @ts-check
/** @odoo-module native */

/** @module @web/components/barcode/barcode_dialog - Dialog wrapper for the barcode video scanner with error state handling */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dialog } from "@web/ui/dialog/dialog";

import {
    BarcodeVideoScanner,
    isBarcodeScannerSupported,
} from "./barcode_video_scanner.js";

export class BarcodeDialog extends Component {
    static template = "web.BarcodeDialog";
    static components = {
        BarcodeVideoScanner,
        Dialog,
    };
    static props = ["facingMode", "close", "onResult", "onError"];

    setup() {
        this.state = useState({
            barcodeScannerSupported: isBarcodeScannerSupported(),
            errorMessage: _t("Check your browser permissions"),
        });
    }

    /**
     * Detection success handler
     *
     * @param {string} result found code
     */
    onResult(result) {
        this.props.close();
        this.props.onResult(result);
    }

    /**
     * Detection error handler
     *
     * @param {Error} error
     */
    onError(error) {
        this.state.barcodeScannerSupported = false;
        this.state.errorMessage = error.message;
    }
}

/**
 * Opens the BarcodeScanning dialog and begins code detection using the device's camera.
 *
 * @returns {Promise<string>} resolves when a {qr,bar}code has been detected
 */
export async function scanBarcode(env, facingMode = "environment") {
    let res;
    let rej;
    const promise = new Promise((resolve, reject) => {
        res = resolve;
        rej = reject;
    });
    env.services.dialog.add(BarcodeDialog, {
        facingMode,
        onResult: (result) => res(result),
        onError: (error) => rej(error),
    });
    return promise;
}

// Named-object export so tests can patch `scanBarcode` via patchWithCleanup.
// `import * as BarcodeScanner` returns an ESM module-namespace whose
// properties are non-configurable (per spec) and reject defineProperty —
// the previous test pattern. A plain object's properties are configurable,
// so `import { BarcodeScanner }; patchWithCleanup(BarcodeScanner, {...})`
// works. The standalone `scanBarcode` function export above stays for the
// 3 consumer addons that already do `import { scanBarcode } from ...`.
export const BarcodeScanner = { scanBarcode };
