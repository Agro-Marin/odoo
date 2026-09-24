// @ts-check
/** @odoo-module native */
import { useMailContext } from "@mail/utils/common/mail_context";
import { Component } from "@odoo/owl";

export class ImStatus extends Component {
    static props = ["persona?", "className?", "style?", "member?", "slots?", "size?"];
    static template = "mail.ImStatus";
    static defaultProps = { className: "", style: "", size: "lg" };
    static components = {};

    setup() {
        super.setup();
        this.mailContext = useMailContext();
    }

    get persona() {
        return this.props.persona ?? this.props.member?.persona;
    }
}
