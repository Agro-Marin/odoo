/** @odoo-module native */
import { Message } from "@mail/core/common/message";
import { formatDate } from "@web/core/l10n/dates";
import { patch } from "@web/core/utils/patch";

import { DateTime } from "luxon";
patch(Message.prototype, {
    formatAccountReportsAnnotationDate(date) {
        return formatDate(DateTime.fromISO(date));
    },
});
