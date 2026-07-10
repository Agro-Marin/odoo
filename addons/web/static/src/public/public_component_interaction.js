// @ts-check
/** @odoo-module native */

/** @module @web/public/public_component_interaction - Interaction that mounts OWL components declared via owl-component HTML elements */

import { registry } from "@web/core/registry";

import { Interaction } from "./interaction.js";

// `public_components` holds OWL Component classes mountable inside frontend
// `<owl-component name="…">` elements; lookup happens in `get Component()` below.
registry
    .category("public_components")
    .addValidation((entry) => typeof entry === "function");

export class PublicComponentInteraction extends Interaction {
    static selector = "owl-component[name]";

    setup() {
        const props = JSON.parse(this.el.getAttribute("props") || "{}");
        // Clear leftover html from a previous page edit whose owl-components
        // weren't properly cleaned up on save.
        this.el.replaceChildren();
        this.mountComponent(
            this.el,
            /** @type {import("@odoo/owl").ComponentConstructor} */ (this.Component),
            props,
        );
    }

    get Component() {
        const name = this.el.getAttribute("name");
        return registry.category("public_components").get(name);
    }
}

registry
    .category("public.interactions")
    .add("public_components", PublicComponentInteraction);
