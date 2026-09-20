/** @odoo-module native */
import { messageActionsRegistry } from "@mail/core/common/message_actions";
import { patch } from "@web/core/utils/patch";

import { AccountReportMessage } from "./message.js";

const deleteAction = messageActionsRegistry.get("delete");

patch(deleteAction, {
    onSelected({ owner }) {
        const res = super.onSelected(...arguments);
        if (!(owner instanceof AccountReportMessage)) {
            return res;
        }
        res.then((value) => {
            if (!value || !owner.props.reportController) {
                return;
            }
            owner.props.reportController.removeAnnotation(owner.message.id);
        });
        return res;
    },
});
