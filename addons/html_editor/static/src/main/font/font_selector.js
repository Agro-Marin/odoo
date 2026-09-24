/** @odoo-module native */
import { useEditorOverlayContext } from "@html_editor/core/editor_overlay_context";
import { useDropdownAutoVisibility } from "@html_editor/dropdown_autovisibility_hook";
import { toolbarButtonProps } from "@html_editor/main/toolbar/toolbar";
import { Component, useState } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { useChildRef } from "@web/core/utils/hooks";

export class FontSelector extends Component {
    static template = "html_editor.FontSelector";
    static props = {
        ...toolbarButtonProps,
        getItems: Function,
        getDisplay: Function,
        onSelected: Function,
    };
    static components = { Dropdown, DropdownItem };

    setup() {
        this.overlayContext = useEditorOverlayContext();
        this.items = this.props.getItems();
        this.state = useState(this.props.getDisplay());
        this.menuRef = useChildRef();
        useDropdownAutoVisibility(this.overlayContext.overlayState, this.menuRef);
    }

    onSelected(item) {
        this.props.onSelected(item);
    }
}
