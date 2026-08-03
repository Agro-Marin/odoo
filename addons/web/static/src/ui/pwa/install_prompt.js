// @ts-check
/** @odoo-module native */

/** @module @web/ui/pwa/install_prompt */

import { Component } from "@odoo/owl";
import { isIOS } from "@web/core/browser/feature_detection";
import { Dialog } from "@web/ui/dialog/dialog";

/**
 * @typedef {Object} InstallPromptProps
 * @property {() => void} close
 */

export class InstallPrompt extends Component {
    static props = {
        close: true,
    };
    static components = {
        Dialog,
    };
    static template = "web.InstallPrompt";

    /** @returns {boolean} */
    get isMobileSafari() {
        return isIOS();
    }

    onClose() {
        this.props.close();
    }
}
