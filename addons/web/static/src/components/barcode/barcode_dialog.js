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
     * Notifies before closing: closing fires the dialog service's `onClose`
     * hook, which `scanBarcode()` uses to resolve `null` on manual close —
     * the actual result must win that one-shot settle race.
     *
     * @param {string} result found code
     */
    onResult(result) {
        this.props.onResult(result);
        this.props.close();
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
 * @returns {Promise<string|null>} resolves with the detected {qr,bar}code, or
 *  `null` when the user closes the dialog without scanning (X button / ESC)
 */
export async function scanBarcode(env, facingMode = "environment") {
    return new Promise((resolve, reject) => {
        // One-shot guard: result, error and close must not double-settle.
        let settled = false;
        const settle = (settler, value) => {
            if (settled) {
                return;
            }
            settled = true;
            settler(value);
        };
        env.services.dialog.add(
            BarcodeDialog,
            {
                facingMode,
                onResult: (result) => settle(resolve, result),
                onError: (error) => settle(reject, error),
            },
            {
                // Manual close (X / ESC) is the normal cancel path: resolve
                // `null` so awaiting consumers unblock instead of leaking a
                // forever-pending promise.
                onClose: () => settle(resolve, null),
            },
        );
    });
}

// Named-object export so tests can patch `scanBarcode` via patchWithCleanup.
// `import * as BarcodeScanner` returns an ESM module-namespace whose
// properties are non-configurable (per spec) and reject defineProperty —
// the previous test pattern. A plain object's properties are configurable,
// so `import { BarcodeScanner }; patchWithCleanup(BarcodeScanner, {...})`
// works. The standalone `scanBarcode` function export above stays for the
// 3 consumer addons that already do `import { scanBarcode } from ...`.
export const BarcodeScanner = { scanBarcode };
