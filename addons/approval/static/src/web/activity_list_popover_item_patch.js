/** @odoo-module native */
import { Approval } from "@approval/web/approval";

import { ActivityListPopoverItem } from "@mail/core/web/activity_list_popover_item";

import { patch } from "@web/core/utils/patch";

Object.assign(ActivityListPopoverItem.components, { Approval });

patch(ActivityListPopoverItem.prototype, {
    get hasEditButton() {
        if (this.props.activity.approver_id) {
            return false;
        }
        return super.hasEditButton;
    },
    get hasMarkDoneButton() {
        if (this.props.activity.approver_id) {
            return false;
        }
        return super.hasMarkDoneButton;
    },
});
