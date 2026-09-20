/** @odoo-module native */
import { Thread } from "@mail/core/common/thread";

import { AccountReportMessage } from "./message.js";

export class AccountReportThread extends Thread {
    static template = "account.Thread";
    static props = [...Thread.props, "reportController?"];
    static components = { ...Thread.components, Message: AccountReportMessage };
}
