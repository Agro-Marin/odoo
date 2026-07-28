// @ts-check
/** @odoo-module native */

/** @module @web/public/public_component_interaction - Interaction that mounts OWL components declared via owl-component HTML elements */

import { registry } from "@web/core/registry";

import { Interaction } from "./interaction.js";

registry
    .category("public_components")
    .addValidation((entry) => typeof entry === "function");

export class PublicComponentInteraction extends Interaction {
    static selector = "owl-component[name]";

    setup() {
        const rawProps = this.el.getAttribute("props") || "{}";
        let props;
        try {
            props = JSON.parse(rawProps);
        } catch (error) {
            throw new Error(
                `Invalid props on <owl-component name="${this.el.getAttribute("name")}">: ${rawProps}`,
                { cause: error },
            );
        }
        // the placeholder markup an owl-component wraps may itself carry
        // interactions; dropping the nodes without stopping them would leave
        // those running on elements no longer in the document
        this.removeChildren(this.el, false);
        this.mountComponent(
            this.el,
            /** @type {import("@odoo/owl").ComponentConstructor} */ (this.Component),
            props,
        );
    }

    get Component() {
        // the selector matches on [name], so the attribute is there; `name=""`
        // still reaches the registry check below and fails it by its name
        const name = this.el.getAttribute("name") ?? "";
        const components = registry.category("public_components");
        if (!components.contains(name)) {
            // the registry's own message names neither the element nor the
            // registry, which is all a template author has to go on
            throw new Error(
                `No public component registered as "${name}" (declared by an <owl-component name="${name}"> element)`,
            );
        }
        return components.get(name);
    }
}

registry
    .category("public.interactions")
    .add("public_components", PublicComponentInteraction);
