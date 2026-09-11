/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";

export class RemoveTranslationBrandingPlugin extends Plugin {
    static id = "removeTranslationBrandingPlugin";

    setup() {
        this.editable
            .querySelectorAll("span[data-oe-model][data-oe-translation-source-sha]")
            .forEach((brandingElement) => {
                brandingElement.replaceWith(...brandingElement.childNodes);
            });
    }
}

registry
    .category("website-plugins")
    .add(RemoveTranslationBrandingPlugin.id, RemoveTranslationBrandingPlugin);
