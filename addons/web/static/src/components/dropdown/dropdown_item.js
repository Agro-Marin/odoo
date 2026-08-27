// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { useDropdownCloser } from "@web/components/dropdown/dropdown_hook";

/**
 * How far up the nesting chain a selected item closes. Internal: consumers spell
 * these values as strings from a template, which is all a template can do.
 */
const ClosingMode = {
    None: "none",
    ClosestParent: "closest",
    AllParents: "all",
};

export class DropdownItem extends Component {
    static template = "web.DropdownItem";
    static props = {
        tag: {
            type: String,
            optional: true,
        },
        class: {
            type: [String, Object],
            optional: true,
        },
        onSelected: {
            type: Function,
            optional: true,
        },
        closingMode: {
            type: Object.values(ClosingMode).map((value) => ({ value })),
            optional: true,
        },
        attrs: {
            type: Object,
            optional: true,
        },
        role: {
            type: String,
            optional: true,
        },
        slots: { type: Object, optional: true },
    };
    static defaultProps = {
        closingMode: ClosingMode.AllParents,
        attrs: {},
        role: "menuitem",
    };

    /** @type {ReturnType<typeof useDropdownCloser>} */
    dropdownControl;

    setup() {
        this.dropdownControl = useDropdownCloser();
    }

    /** @param {MouseEvent} ev */
    onClick(ev) {
        if (this.props.attrs.href) {
            ev.preventDefault();
        }
        this.props.onSelected?.(ev);
        switch (this.props.closingMode) {
            case ClosingMode.ClosestParent:
                this.dropdownControl.close();
                break;
            case ClosingMode.AllParents:
                this.dropdownControl.closeAll();
                break;
        }
    }
}
