// @ts-check
/** @odoo-module native */

import { Component, onMounted, useState } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { browser } from "@web/core/browser/browser";
import { isDisplayStandalone } from "@web/core/browser/feature_detection";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
export class InstallScopedApp extends Component {
    static props = {};
    static template = "web.InstallScopedApp";
    static components = { Dropdown };
    /** @type {{ manifest: Record<string, any>; showInstallUI: boolean }} */
    state;

    setup() {
        this.pwa = useService(/** @type {any} */ ("pwa"));
        this.state = useState({
            manifest: /** @type {Record<string, any>} */ ({}),
            showInstallUI: false,
        });
        this.isDisplayStandalone = isDisplayStandalone();
        this.isInstallationPossible = browser.BeforeInstallPromptEvent !== undefined;
        onMounted(async () => {
            this.state.manifest = await this.pwa.getManifest();
            this.state.showInstallUI = true;
        });
    }
    /**
     * @param {Event} ev
     */
    onChangeName(ev) {
        const value = /** @type {any} */ (ev.target).value;
        if (value !== this.state.manifest.name) {
            const url = new URL(document.location.href);
            url.searchParams.set("app_name", encodeURIComponent(value));
            browser.location.replace(url);
        }
    }
    onInstall() {
        this.state.showInstallUI = false;
        this.pwa.show({
            onDone: (/** @type {{ outcome: string }} */ res) => {
                if (res.outcome === "accepted") {
                    browser.location.replace(this.state.manifest.start_url);
                } else {
                    this.state.showInstallUI = true;
                }
            },
        });
    }
}

registry
    .category("public_components")
    .add("web.install_scoped_app", /** @type {any} */ (InstallScopedApp));
