// @ts-check
/** @odoo-module native */

/** @module @web/components/barcode/barcode_dialog */

import { Component, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
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

    /** @type {{ barcodeScannerSupported: boolean, errorMessage: string }} */
    state;

    setup() {
        this.state = useState({
            barcodeScannerSupported: isBarcodeScannerSupported(),
            errorMessage: _t("Check your browser permissions"),
        });
    }

    /**
     * @param {string} result
     */
    onResult(result) {
        this.props.onResult(result);
        this.props.close();
    }

    /**
     * @param {Error} error
     */
    onError(error) {
        this.state.barcodeScannerSupported = false;
        this.state.errorMessage = error.message;
    }
}

/**
 * @returns {Promise<string|null>}
 */
export async function scanBarcode(env, facingMode = "environment") {
    return new Promise((resolve, reject) => {
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
                onClose: () => settle(resolve, null),
            },
        );
    });
}

export const BarcodeScanner = { scanBarcode };
