/** @odoo-module native */
import { registry } from "@web/core/registry";
import {
    provideViewButtonContext,
    useViewButtonContext,
} from "@web/core/view_button_context_hooks";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many";

export class PortalUserX2ManyField extends X2ManyField {
    setup() {
        super.setup();
        this.viewButtonContext = useViewButtonContext();
        const onClickViewButton = this.viewButtonContext.onClickViewButton;
        let pending = false;
        provideViewButtonContext({
            async onClickViewButton(click) {
                if (click.clickParams.name === "action_refresh_modal" || pending) {
                    return;
                }
                pending = true;
                try {
                    return await onClickViewButton(click);
                } finally {
                    pending = false;
                }
            },
        });
    }
}

export const portalUserX2ManyField = {
    ...x2ManyField,
    component: PortalUserX2ManyField,
};

registry.category("fields").add("portal_wizard_user_one2many", portalUserX2ManyField);
