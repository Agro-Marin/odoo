/** @odoo-module native */
import { Component } from "@odoo/owl";
import { registry, useRegistry } from "@web/core/registry";
import { useForwardRefToParent } from "@web/core/utils/hooks";
import { MainComponentsContainer } from "@web/ui/main_components_container";

export class LocalOverlayContainer extends MainComponentsContainer {
    static template = "html_editor.LocalOverlayContainer";
    static props = {
        localOverlay: { type: Function, optional: true },
        identifier: { type: String, optional: true },
    };
    static defaultProps = {
        identifier: "overlay_components",
    };

    setup() {
        const overlayComponents = registry.category(this.props.identifier);
        if (!overlayComponents.validationSchema) {
            overlayComponents.addValidation({
                Component: { validate: (c) => c.prototype instanceof Component },
                props: { type: Object, optional: true },
            });
        }
        this.Components = useRegistry(overlayComponents);
        useForwardRefToParent("localOverlay");
    }
}
