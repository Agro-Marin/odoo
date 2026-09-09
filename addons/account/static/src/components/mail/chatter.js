/** @odoo-module native */
import { WebChatter } from "@mail/chatter/web/web_chatter";
import { AccountReportComposer } from "./composer.js";
import { AccountReportThread } from "./thread.js";

export class AccountReportChatter extends WebChatter {
    static template = "account.Chatter";
    static props = [...WebChatter.props, "reportController?", "date_to", "list?"];
    static components = {
        ...WebChatter.components,
        Composer: AccountReportComposer,
        Thread: AccountReportThread,
    };
}
