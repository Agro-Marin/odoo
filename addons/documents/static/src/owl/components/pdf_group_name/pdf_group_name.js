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
        // used to get the value of the input when renaming.
        this.nameInputRef = useRef("nameInput");
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    /**
     * @public
     */
    onBlur() {
        this.props.onEditName(this.props.groupId, this.nameInputRef.el.value);
        // Also leave edit mode on blur, otherwise clicking away commits the name
        // but leaves the input open (the only other exit was the now-restored
        // Enter handler).
        this.props.onToggleEdit(this.props.groupId, false);
    }
    /**
     * Clicking the name is a selection gesture as much as a rename gesture, so
     * it gets its own handler. `onToggleEdit` is called on leaving edit mode
     * too (blur, Enter), so carrying the selection toggle there would re-select the
     * group the click had just deselected.
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
        // `ev.key`, not `ev.code`: the latter is the physical key, so the numpad
        // Enter ("NumpadEnter") never committed the rename.
        if (ev.key !== "Enter") {
            return;
        }
        ev.stopPropagation();
        this.props.onEditName(this.props.groupId, this.nameInputRef.el.value);
        this.props.onToggleEdit(this.props.groupId, false);
    }
}
