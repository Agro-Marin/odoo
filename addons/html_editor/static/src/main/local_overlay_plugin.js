/** @odoo-module native */
import { Plugin } from "../plugin.js";

/**
 * @typedef { Object } LocalOverlayShared
 * @property { LocalOverlayPlugin['makeLocalOverlay'] } makeLocalOverlay
 */

export class LocalOverlayPlugin extends Plugin {
    static id = "localOverlay";
    static shared = ["makeLocalOverlay"];

    setup() {
        this.localOverlayContainer = this.config.localOverlayContainers?.ref.el;
        this.localOverlays = new Set();
    }

    /**
     * @param {string} containerId
     */
    makeLocalOverlay(containerId) {
        const container = this.document.createElement("div");
        container.className = `oe-local-overlay`;
        container.setAttribute("data-oe-local-overlay-id", containerId);
        if (this.localOverlayContainer) {
            this.localOverlayContainer.append(container);
            this.localOverlays.add(container);
        }
        return container;
    }

    destroy() {
        if (this.localOverlays) {
            for (const container of this.localOverlays) {
                container.remove();
            }
            this.localOverlays.clear();
        }
        super.destroy();
    }
}
