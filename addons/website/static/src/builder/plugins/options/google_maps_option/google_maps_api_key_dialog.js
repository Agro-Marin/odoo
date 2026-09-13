/** @odoo-module native */
import { Component, useRef, useState } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { _t } from "@web/core/translation";
import { useChildRef, useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";

const log = makeLogger("website.builder.option.google_maps_api_key_dialog");

/**
 * @typedef {import('./google_map_option_plugin.js').ApiKeyValidation} ApiKeyValidation
 */

export class GoogleMapsApiKeyDialog extends Component {
    static template = "website.GoogleMapsApiKeyDialog";
    static components = { Dialog };
    static props = {
        originalApiKey: String,
        onSave: Function,
        close: Function,
    };

    setup() {
        useLifecycleLog(log);
        this.modalRef = useChildRef();
        /** @type {{ apiKey?: string, apiKeyValidation: ApiKeyValidation }} */
        this.state = useState({
            apiKey: this.props.originalApiKey,
            apiKeyValidation: { isValid: false },
        });
        this.apiKeyInput = useRef("apiKeyInput");
        this.googleMapsService = useService("google_maps");
    }

    async onClickSave() {
        if (this.state.apiKey) {
            /** @type {NodeList} */
            const buttons = this.modalRef.el.querySelectorAll("button");
            buttons.forEach((button) => button.setAttribute("disabled", true));
            const endValidate = log.perf("GoogleMapsApiKeyDialog validate key");
            /** @type {ApiKeyValidation} */
            const apiKeyValidation = await this.googleMapsService.validateGMapsApiKey(
                this.state.apiKey,
            );
            endValidate(() => ({
                isValid: apiKeyValidation.isValid,
                message: apiKeyValidation.message,
            }));
            this.state.apiKeyValidation = apiKeyValidation;
            if (apiKeyValidation.isValid) {
                const endSave = log.perf("GoogleMapsApiKeyDialog save key");
                await this.props.onSave(this.state.apiKey);
                endSave();
                this.props.close();
            }
            buttons.forEach((button) => button.removeAttribute("disabled"));
        } else {
            log.logic("GoogleMapsApiKeyDialog save refused: empty key");
            this.state.apiKeyValidation = {
                isValid: false,
                message: _t("Enter an API Key"),
            };
        }
    }
}
