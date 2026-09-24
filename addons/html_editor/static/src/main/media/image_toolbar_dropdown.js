/** @odoo-module native */
import { useEditorOverlayContext } from "@html_editor/core/editor_overlay_context";
import { useDropdownAutoVisibility } from "@html_editor/dropdown_autovisibility_hook";
import { toolbarButtonProps } from "@html_editor/main/toolbar/toolbar";
import { Component, useState } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { useChildRef } from "@web/core/utils/hooks";

export class ImageToolbarDropdown extends Component {
    static components = { Dropdown, DropdownItem };
    static props = {
        ...toolbarButtonProps,
        name: String,
        icon: { type: String, optional: true },
        onSelected: Function,
        items: Array,
        getDisplay: { type: Function, optional: true },
    };
    static template = "html_editor.ImageToolbarDropdown";

    setup() {
        this.overlayContext = useEditorOverlayContext();
        this.items = this.props.items;
        if (this.props.getDisplay) {
            this.state = useState(this.props.getDisplay());
        }
        this.menuRef = useChildRef();
        useDropdownAutoVisibility(this.overlayContext.overlayState, this.menuRef);
    }

    onSelected(item) {
        this.props.onSelected(item);
    }
}
