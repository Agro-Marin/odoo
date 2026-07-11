// @ts-check
/** @odoo-module native */

/** @module @web/services/pwa/install_prompt - Dialog showing Safari-specific PWA installation instructions (iOS and macOS) */

import { Component } from "@odoo/owl";
import { isIOS } from "@web/core/browser/feature_detection";
import { Dialog } from "@web/ui/dialog/dialog";

/**
 * @typedef {Object} InstallPromptProps
 * @property {() => void} close - close the dialog
 */

export class InstallPrompt extends Component {
    static props = {
        close: true,
    };
    static components = {
        Dialog,
    };
    static template = "web.InstallPrompt";

    /** @returns {boolean} whether the device is running iOS (mobile Safari) */
    get isMobileSafari() {
        return isIOS();
    }

    /**
     * Close the dialog. The dismissal callback is wired as a dialog option
     * by the pwa service, so it fires on every removal path (ESC included).
     */
    onClose() {
        this.props.close();
    }
}
