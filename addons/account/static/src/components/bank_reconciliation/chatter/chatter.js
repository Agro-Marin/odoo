/** @odoo-module native */
import { WebChatter } from "@mail/chatter/web/web_chatter";

export class BankRecChatter extends WebChatter {
    static props = [...WebChatter.props, "statementLine?"];

    async reloadParentView() {
        await this.props.statementLine?.load();
    }
}
