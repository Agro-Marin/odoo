// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

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
        const C = /** @type {import("@odoo/owl").ComponentConstructor} */ (
            this.Component
        );
        this.removeChildren(this.el, false);
        this.mountComponent(this.el, C, props);
    }

    get Component() {
        const name = this.el.getAttribute("name") ?? "";
        const components = registry.category("public_components");
        if (!components.contains(name)) {
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
