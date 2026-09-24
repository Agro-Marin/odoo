/** @odoo-module native */
import { Thread } from "@mail/core/common/thread";
import { useMailContext } from "@mail/utils/common/mail_context";

import { AccountReportMessage } from "./message.js";

export class AccountReportThread extends Thread {
    static template = "account.Thread";
    static props = [...Thread.props, "reportController?"];
    static components = { ...Thread.components, Message: AccountReportMessage };

    setup() {
        super.setup();
        this.mailContext = useMailContext();
    }
}
