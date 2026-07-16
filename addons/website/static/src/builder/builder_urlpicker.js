/** @odoo-module native */
import { BuilderUrlPicker } from "@html_builder/core/building_blocks/builder_urlpicker";
import { Plugin } from "@html_editor/plugin";
import { useEffect } from "@odoo/owl";
import { registry } from "@web/core/registry";
import wUtils from "@website/js/utils";

export class WebsiteUrlPicker extends BuilderUrlPicker {
    setup() {
        super.setup();

        useEffect(
            (inputEl) => {
                if (!inputEl) {
                    return;
                }
                const unmountAutocompleteWithPages = wUtils.autocompleteWithPages(
                    inputEl,
                    {
                        classes: {
                            "ui-autocomplete": "o_website_ui_autocomplete",
                        },
                        body: this.env.getEditingElement().ownerDocument.body,
                        urlChosen: () => {
                            this.commit(this.inputRef.el.value);
                        },
                    },
                    this.env,
                );
                return () => unmountAutocompleteWithPages();
            },
            () => [this.inputRef.el],
        );
    }
}

class UrlPickerPlugin extends Plugin {
    static id = "urlPickerPlugin";

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_components: {
            WebsiteUrlPicker,
        },
    };
}

registry.category("website-plugins").add(UrlPickerPlugin.id, UrlPickerPlugin);
