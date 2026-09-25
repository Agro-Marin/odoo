/** @odoo-module native */
import { useBuilderContext } from "@html_builder/core/builder_context";
import { BuilderUrlPicker } from "@html_builder/core/building_blocks/builder_urlpicker";
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { registry } from "@web/core/registry";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { autocompleteWithPages } from "@website/js/utils";

const log = makeLogger("website.builder.plugin.url_picker_plugin");

export class WebsiteUrlPicker extends BuilderUrlPicker {
    setup() {
        super.setup();
        this.builderContext = useBuilderContext();
        useLifecycleLog(log);

        useLayoutEffect(
            (inputEl) => {
                if (!inputEl) {
                    return;
                }
                log.lifecycle("WebsiteUrlPicker autocomplete attached");
                const unmountAutocompleteWithPages = autocompleteWithPages(
                    inputEl,
                    {
                        classes: {
                            "ui-autocomplete": "o_website_ui_autocomplete",
                        },
                        body: this.builderContext.getEditingElement().ownerDocument
                            .body,
                        urlChosen: () => {
                            this.commit(this.inputRef.el.value);
                        },
                    },
                    this.env,
                );
                return () => {
                    log.lifecycle("WebsiteUrlPicker autocomplete detached");
                    unmountAutocompleteWithPages();
                };
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
