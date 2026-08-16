/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
export const composerService = {
    dependencies: ["mail.store", "legacy_multi_tab"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {Partial<import("services").Services>} services
     */
    start(env, { legacy_multi_tab }) {
        const readHtmlEnabled = () =>
            legacy_multi_tab.getSharedValue("mail.html_composer.enabled", false) ===
            true;
        const state = reactive({
            htmlEnabled: readHtmlEnabled(),
            setHtmlComposer() {
                if (state.htmlEnabled) {
                    return;
                }
                state.htmlEnabled = true;
                legacy_multi_tab.setSharedValue("mail.html_composer.enabled", true);
            },
            setTextComposer() {
                if (!state.htmlEnabled) {
                    return;
                }
                state.htmlEnabled = false;
                legacy_multi_tab.setSharedValue("mail.html_composer.enabled", false);
            },
        });

        legacy_multi_tab.bus.addEventListener(
            "shared_value_updated",
            /** @param {CustomEvent<{key: string}>} ev */ ({ detail }) => {
                if (detail.key === "mail.html_composer.enabled") {
                    state.htmlEnabled = readHtmlEnabled();
                }
            },
        );

        return state;
    },
};

registry.category("services").add("mail.composer", composerService);
