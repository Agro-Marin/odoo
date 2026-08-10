/** @odoo-module native */
import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
export const composerService = {
    dependencies: ["mail.store", "legacy_multi_tab"],
    /**
     * Enable Html composer with: odoo.__WOWL_DEBUG__.root.env.services["mail.composer"].setHtmlComposer()
     * @param {import("@web/env").OdooEnv} env
     * @param {Partial<import("services").Services>} services
     */
    start(env, { legacy_multi_tab }) {
        /**
         * Single reader for the shared key, used both at startup and on the
         * cross-tab update, so the two can never disagree about one value.
         *
         * `=== true` rather than a truthiness test: the key holds a boolean
         * preference, and `getSharedValue` returns the RAW string when the
         * stored value does not parse (@see legacy_multi_tab_service's
         * `getItemFromStorage`). Coercing that to `true` would let a garbage
         * value silently switch the composer to HTML; an unparseable value
         * means "no valid preference", which is the default, i.e. false.
         */
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

        legacy_multi_tab.bus.addEventListener("shared_value_updated", ({ detail }) => {
            if (detail.key === "mail.html_composer.enabled") {
                // NOT `JSON.parse(detail.newValue)`: `newValue` is the raw
                // storage string, `null` when the key is removed, and a bare
                // parse throws inside this listener on anything non-JSON. The
                // storage event fires after the write is committed, so reading
                // the key back is both safe and consistent with startup.
                state.htmlEnabled = readHtmlEnabled();
            }
        });

        return state;
    },
};

registry.category("services").add("mail.composer", composerService);
