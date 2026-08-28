/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
const HTML_ENABLED_KEY = "mail.html_composer.enabled";

export class ComposerService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {Partial<import("services").Services>} services
     */
    constructor(env, services) {
        this.env = env;
        this.multiTab = services.legacy_multi_tab;
        this.htmlEnabled = this.readHtmlEnabled();
    }

    setup() {
        this.multiTab.bus.addEventListener(
            "shared_value_updated",
            /** @param {CustomEvent<{key: string}>} ev */ ({ detail }) => {
                if (detail.key === HTML_ENABLED_KEY) {
                    this.htmlEnabled = this.readHtmlEnabled();
                }
            },
        );
    }

    readHtmlEnabled() {
        return this.multiTab.getSharedValue(HTML_ENABLED_KEY, false) === true;
    }

    setHtmlComposer() {
        this._setHtmlEnabled(true);
    }

    setTextComposer() {
        this._setHtmlEnabled(false);
    }

    /**
     * @param {boolean} htmlEnabled
     */
    _setHtmlEnabled(htmlEnabled) {
        if (this.htmlEnabled === htmlEnabled) {
            return;
        }
        this.htmlEnabled = htmlEnabled;
        this.multiTab.setSharedValue(HTML_ENABLED_KEY, htmlEnabled);
    }
}

export const composerService = {
    dependencies: ["mail.store", "legacy_multi_tab"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {Partial<import("services").Services>} services
     */
    start(env, services) {
        const composer = reactive(new ComposerService(env, services));
        composer.setup();
        return composer;
    },
};

registry.category("services").add("mail.composer", composerService);
