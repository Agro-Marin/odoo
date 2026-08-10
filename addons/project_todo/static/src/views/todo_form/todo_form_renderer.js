/** @odoo-module native */
import { useRef } from "@odoo/owl";
import { FormRendererWithHtmlExpander } from "@resource/views/form_with_html_expander/form_renderer_with_html_expander";
import { useBus } from "@web/core/utils/hooks";

export class TodoFormRenderer extends FormRendererWithHtmlExpander {
    setup() {
        super.setup();
        // Same t-ref the base renderer resolves; useRef only reads the node.
        this.compiledViewRoot = useRef("compiled_view_root");
        // With the chatter closed the description takes the whole sheet; with
        // it open, only an xxl viewport has the room to spare.
        this.sizeToExpandHTMLField = 1;
        useBus(this.env.bus, "TODO:TOGGLE_CHATTER", (ev) =>
            this.onChatterToggled(ev.detail.displayChatter),
        );
    }

    onChatterToggled(displayChatter) {
        this.sizeToExpandHTMLField = displayChatter ? 6 : 1;
        // The base effect only ever *sets* minHeight, so a stale inline value
        // would survive the chatter opening and keep the description at its
        // full-width height. Drop it and let the effect recompute; the
        // controller re-arms `reloadHtmlFieldHeight`, which is what re-runs it.
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
