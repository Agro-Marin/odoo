/** @odoo-module native */
import { useEditorOverlayContext } from "@html_editor/core/editor_overlay_context";
import { useDropdownAutoVisibility } from "@html_editor/dropdown_autovisibility_hook";
import { toolbarButtonProps } from "@html_editor/main/toolbar/toolbar";
import { Component } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { useChildRef } from "@web/core/utils/hooks";

export class FontFamilySelector extends Component {
    static template = "html_editor.FontFamilySelector";
    static props = {
        document: { optional: true },
        fontFamilyItems: Object,
        currentFontFamily: Object,
        onSelected: Function,
        ...toolbarButtonProps,
    };
    static components = { Dropdown, DropdownItem };

    setup() {
        this.overlayContext = useEditorOverlayContext();
        this.menuRef = useChildRef();
        useDropdownAutoVisibility(this.overlayContext.overlayState, this.menuRef);
    }
}
