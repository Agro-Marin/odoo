/** @odoo-module native */
import { onWillUpdateProps, toRaw, useEffect, useRef, useState } from "@odoo/owl";
import { TagsList } from "@web/components/tags_list";
import { usePopover } from "@web/ui/popover";

import { RecipientsInputTagsListPopover } from "./recipients_input_tags_list_popover.js";

export class RecipientsInputTagsList extends TagsList {
    static template = "web.RecipientsInputTagsList";
    static props = {
        ...TagsList.props,
        updateRecipient: { type: Function, optional: true },
    };
    static defaultProps = { ...TagsList.defaultProps, updateRecipient: () => {} };
    setup() {
        this.popover = usePopover(RecipientsInputTagsListPopover, {
            closeOnClickAway: false,
            position: "bottom-middle",
        });
        this.tagToUpdateRef = useRef("tagToUpdate");
        this.state = useState({
            tagToUpdate: this.getFirstTagToUpdate(this.props.tags),
        });
        onWillUpdateProps(
            /** @param {{tags: Array<{id: string, resId?: number, text: string, email?: string, canEdit: boolean}>}} nextProps */ (
                nextProps,
            ) => {
                const tagToUpdate = this.getFirstTagToUpdate(nextProps.tags);
                if (!this.tagEquals(tagToUpdate, this.state.tagToUpdate)) {
                    this.state.tagToUpdate = tagToUpdate;
                }
            },
        );
        useEffect(
            () => {
                if (this.state.tagToUpdate && this.tagToUpdateRef.el) {
                    this.updateTag();
                } else if (this.popover.isOpen) {
                    this.popover.close();
                }
            },
            () => [this.state.tagToUpdate, this.tagToUpdateRef.el],
        );
    }

    /**
     * @param {Array<{id: string, resId?: number, text: string, email?: string, canEdit: boolean}>} tags
     * @returns {{id: string, resId?: number, text: string, email?: string, canEdit: boolean}|undefined}
     */
    getFirstTagToUpdate(tags) {
        for (const tag of tags) {
            if (!tag.email) {
                return tag;
            }
        }
    }

    /**
     * @param {{id: string, resId?: number, text: string, email?: string, canEdit: boolean}} tag1
     * @param {{id: string, resId?: number, text: string, email?: string, canEdit: boolean}} tag2
     * @returns {boolean}
     */
    tagEquals(tag1, tag2) {
        if (toRaw(tag1) === toRaw(tag2)) {
            return true;
        }
        return (
            Boolean(tag1 && tag2) &&
            tag1.resId === tag2.resId &&
            tag1.text === tag2.text &&
            tag1.email === tag2.email
        );
    }

    updateTag() {
        this.popover.open(this.tagToUpdateRef.el, {
            tagToUpdate: this.state.tagToUpdate,
            /** @param {string} newEmail */
            onUpdateTag: (newEmail) =>
                this.props.updateRecipient(newEmail, this.state.tagToUpdate.resId),
        });
    }
}
