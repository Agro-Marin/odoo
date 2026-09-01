/** @odoo-module native */
import { useDropdownAutoVisibility } from "@html_editor/dropdown_autovisibility_hook";
import { toolbarButtonProps } from "@html_editor/main/toolbar/toolbar";
import { Component, useState } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { useChildRef } from "@web/core/utils/hooks";

export class ImageAlignSelector extends Component {
    static components = { Dropdown, DropdownItem };
    static props = {
        ...toolbarButtonProps,
        items: Array,
        getDisplay: Function,
        focusEditable: Function,
        onSelected: Function,
    };
    static template = "html_editor.ImageAlignSelector";

    setup() {
        this.items = this.props.items;
        this.state = useState(this.props.getDisplay());
        this.menuRef = useChildRef();
        useDropdownAutoVisibility(this.env.overlayState, this.menuRef);
    }

    onSelected(item) {
        this.props.onSelected(item);
        this.props.focusEditable();
    }
}
