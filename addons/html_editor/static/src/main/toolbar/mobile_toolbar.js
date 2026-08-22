/** @odoo-module native */
import { Component, onMounted, useExternalListener, useRef } from "@odoo/owl";

import { Toolbar } from "./toolbar.js";

export class ToolbarMobile extends Component {
    static template = "html_editor.MobileToolbar";
    static props = {
        editable: { validate: (el) => el.nodeType === Node.ELEMENT_NODE },
        class: { type: String, optional: true },
        state: Object,
        getSelection: Function,
        focusEditable: Function,
    };
    static components = {
        Toolbar,
    };

    setup() {
        this.toolbar = useRef("toolbarWrapper");
        try {
            const innerWindow = this.props.editable.ownerDocument.defaultView;
            const frameElement = innerWindow.frameElement;
            this.targetWindow = frameElement?.ownerDocument.defaultView ?? window;
        } catch {
            this.targetWindow = window;
        }
        useExternalListener(
            this.targetWindow.visualViewport,
            "resize",
            this.fixToolbarPosition,
        );
        useExternalListener(
            this.targetWindow.visualViewport,
            "scroll",
            this.fixToolbarPosition,
        );

        onMounted(() => this.fixToolbarPosition());
    }

    fixToolbarPosition() {
        const visualViewport = this.targetWindow.visualViewport;
        const keyboardHeight = Math.max(
            0,
            this.targetWindow.innerHeight -
                (visualViewport.height + visualViewport.offsetTop),
        );

        this.toolbar.el.style.bottom = `${keyboardHeight}px`;
    }
}
