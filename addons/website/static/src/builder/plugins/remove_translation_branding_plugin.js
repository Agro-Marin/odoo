/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";

const log = makeLogger("website.builder.translation.remove_translation_branding");

export class RemoveTranslationBrandingPlugin extends Plugin {
    static id = "removeTranslationBrandingPlugin";

    setup() {
        log.lifecycle("setup", () => ({
            brandingSpans: this.editable.querySelectorAll(
                "span[data-oe-model][data-oe-translation-source-sha]",
            ).length,
        }));
        const endUnwrap = log.perf("unwrap translation branding spans");
        this.editable
            .querySelectorAll("span[data-oe-model][data-oe-translation-source-sha]")
            .forEach((brandingElement) => {
                brandingElement.replaceWith(...brandingElement.childNodes);
            });
        endUnwrap();
    }
}

registry
    .category("website-plugins")
    .add(RemoveTranslationBrandingPlugin.id, RemoveTranslationBrandingPlugin);
