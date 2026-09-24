/** @odoo-module native */
import { useEditorOverlayContext } from "@html_editor/core/editor_overlay_context";
import { useDropdownAutoVisibility } from "@html_editor/dropdown_autovisibility_hook";
import { closestElement } from "@html_editor/utils/dom_traversal";
import { Component } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown";
import { useChildRef } from "@web/core/utils/hooks";

import { toolbarButtonProps } from "../toolbar/toolbar.js";

export class ListSelector extends Component {
    static template = "html_editor.ListSelector";
    static props = {
        ...toolbarButtonProps,
        getButtons: Function,
        getListMode: Function,
        key: Object,
    };
    static components = { Dropdown };

    setup() {
        this.overlayContext = useEditorOverlayContext();
        this.menuRef = useChildRef();
        useDropdownAutoVisibility(this.overlayContext.overlayState, this.menuRef);
    }
    getActiveMode() {
        const { editableSelection: selection } = this.props.getSelection();
        const closestLI = closestElement(selection.anchorNode, "LI");
        return closestLI && this.props.getListMode(closestLI.parentNode);
    }
}
