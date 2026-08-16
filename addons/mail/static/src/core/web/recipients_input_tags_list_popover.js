/** @odoo-module native */
import { parseEmail } from "@mail/utils/common/format";
import { Component, useExternalListener, useRef, useState } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { isEmail } from "@web/core/utils/format/strings";
import { useService } from "@web/core/utils/hooks";
export class RecipientsInputTagsListPopover extends Component {
    static props = {
        tagToUpdate: { type: Object },
        onUpdateTag: { type: Function },
        close: { type: Function },
    };
    static template = "mail.RecipientsInputTagsListPopover";

    setup() {
        this.orm = useService("orm");
        this.state = useState({ value: "" });
        this.popoverRef = useRef("tagsListPopoverRef");
        useExternalListener(
            window,
            "click",
            /** @param {MouseEvent} ev */ (ev) => {
                if (!this.popoverRef.el?.contains(ev.target)) {
                    this.discardTag();
                }
            },
        );
    }

    /** @param {KeyboardEvent} ev */
    onKeydown(ev) {
        const hotkey = getActiveHotkey(ev);
        this.state.error = false;
        if (hotkey === "enter") {
            this.updateTag();
        }
        if (hotkey === "escape") {
            this.discardTag();
        }
    }

    updateTag() {
        if (!this.isValidEmail) {
            this.state.error = true;
            return;
        }
        this.props.onUpdateTag(this.state.value);
        this.props.close();
    }

    discardTag() {
        this.props.tagToUpdate.onDelete();
        this.props.close();
    }

    get isValidEmail() {
        const value = parseEmail(this.state.value);
        const name = value ? value[0] : "";
        return isEmail(name);
    }
}
