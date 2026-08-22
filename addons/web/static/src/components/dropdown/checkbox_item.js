// @ts-check
/** @odoo-module native */

import { DropdownItem } from "@web/components/dropdown/dropdown_item";

export class CheckboxItem extends DropdownItem {
    static template = "web.CheckboxItem";
    static props = {
        ...DropdownItem.props,
        checked: {
            type: Boolean,
            optional: false,
        },
    };
    static defaultProps = {
        ...DropdownItem.defaultProps,
        role: "menuitemcheckbox",
    };
}
