/** @odoo-module native */
import { Component, useRef } from "@odoo/owl";

export class PdfGroupName extends Component {
    static props = {
        groupId: String,
        name: String,
        edit: Boolean,
        onToggleEdit: {
            type: Function,
            optional: true,
        },
        onGroupNameClicked: {
            type: Function,
            optional: true,
        },
        onEditName: {
            type: Function,
            optional: true,
        },
    };
    static template = "documents.component.PdfGroupName";

    setup() {
        this.nameInputRef = useRef("nameInput");
    }

    /**
     * @public
     */
    onBlur() {
        this.props.onEditName(this.props.groupId, this.nameInputRef.el.value);
        this.props.onToggleEdit(this.props.groupId, false);
    }
    /**
     * @public
     */
    onClickGroupName() {
        this.props.onGroupNameClicked(this.props.groupId);
    }
    /**
     * @public
     * @param {MouseEvent} ev
     */
    onKeyDown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.stopPropagation();
        this.props.onEditName(this.props.groupId, this.nameInputRef.el.value);
        this.props.onToggleEdit(this.props.groupId, false);
    }
}
