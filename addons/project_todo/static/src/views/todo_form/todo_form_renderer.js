/** @odoo-module native */
import { useRef } from "@odoo/owl";
import { FormRendererWithHtmlExpander } from "@web/views/form_with_html_expander/form_renderer_with_html_expander";
import { useBus } from "@web/core/utils/hooks";

export class TodoFormRenderer extends FormRendererWithHtmlExpander {
    setup() {
        super.setup();
        this.compiledViewRoot = useRef("compiled_view_root");
        this.sizeToExpandHTMLField = 1;
        useBus(this.env.bus, "TODO:TOGGLE_CHATTER", (ev) =>
            this.onChatterToggled(ev.detail.displayChatter),
        );
    }

    onChatterToggled(displayChatter) {
        this.sizeToExpandHTMLField = displayChatter ? 6 : 1;
        const htmlField = this.compiledViewRoot.el?.querySelector(
            this.htmlFieldQuerySelector,
        );
        const elementToResize = htmlField?.querySelector(".note-editable") || htmlField;
        if (elementToResize) {
            elementToResize.style.minHeight = "";
        }
    }

    _canExpandHTMLField(size) {
        return size >= this.sizeToExpandHTMLField;
    }
}
