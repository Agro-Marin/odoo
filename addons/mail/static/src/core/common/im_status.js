/** @odoo-module native */
import { Component } from "@odoo/owl";

export class ImStatus extends Component {
    static props = ["persona?", "className?", "style?", "member?", "slots?", "size?"];
    static template = "mail.ImStatus";
    static defaultProps = { className: "", style: "", size: "lg" };
    // The template's <Typing/> node is only reachable when a member is typing,
    // which requires the discuss typing layer; that layer contributes the
    // component (see @mail/discuss/typing/common/im_status_patch).
    static components = {};

    get persona() {
        return this.props.persona ?? this.props.member?.persona;
    }
}
