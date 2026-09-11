// @ts-check
/** @odoo-module native */
import { Component, onWillStart } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
export class RecipientsPopover extends Component {
    static template = "mail.RecipientsPopover";
    static props = {
        id: { type: Number, required: true },
        close: { type: Function, required: true },
        viewProfileBtnOverride: { type: Function },
    };

    setup() {
        this.orm = useService("orm");
        onWillStart(async () => {
            [this.partner] = await this.orm.webRead("res.partner", [this.props.id], {
                specification: this.fieldSpecification,
            });
        });
    }

    get name() {
        return this.partner.name || this.partner.display_name || _t("Unnamed");
    }

    get phone() {
        return this.partner.phone_ids?.[0]?.number;
    }

    get email() {
        return this.partner.email_normalized || this.partner.email;
    }

    get fieldSpecification() {
        return {
            name: {},
            email_normalized: {},
            email: {},
            phone_ids: { fields: { number: {} }, limit: 1 },
            display_name: {},
        };
    }

    onClickViewProfile() {
        this.props.close();
        this.props.viewProfileBtnOverride();
    }
}
