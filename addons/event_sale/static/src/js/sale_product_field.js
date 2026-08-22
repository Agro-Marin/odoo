/** @odoo-module native */
import {
    SaleOrderLineProductField,
    saleOrderLineProductField,
} from "@sale/js/sale_product_field";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

// `service_tracking` is read here, not by sale, so it is declared here. Declaring it
// twice (event_booth_sale does the same) is harmless: `addFieldDependencies` keys on the
// field name and merges rather than duplicating.
Object.assign(saleOrderLineProductField, {
    fieldDependencies: [
        ...saleOrderLineProductField.fieldDependencies,
        { name: "service_tracking", type: "selection" },
    ],
});

patch(SaleOrderLineProductField.prototype, {
    setup() {
        super.setup();
        this.action = useService("action");
    },
    get isEvent() {
        return this.props.record.data.service_tracking === "event";
    },
    get hasConfigurationButton() {
        return super.hasConfigurationButton || this.isEvent;
    },
    onEditConfiguration() {
        if (this.isEvent) {
            this._openEventConfigurator();
        } else {
            super.onEditConfiguration();
        }
    },
    async _onProductUpdate() {
        if (this.isEvent) {
            await this._openEventConfigurator();
        } else {
            await super._onProductUpdate();
        }
    },
    async _openEventConfigurator() {
        const actionContext = {
            default_product_id: this.props.record.data.product_id.id,
        };
        if (this.props.record.data.event_id) {
            actionContext.default_event_id = this.props.record.data.event_id.id;
        }
        if (this.props.record.data.event_slot_id) {
            actionContext.default_event_slot_id =
                this.props.record.data.event_slot_id[0];
        }
        if (this.props.record.data.event_ticket_id) {
            actionContext.default_event_ticket_id =
                this.props.record.data.event_ticket_id.id;
        }
        this.action.doAction("event_sale.event_configurator_action", {
            additionalContext: actionContext,
            onClose: async (closeInfo) => {
                if (
                    !closeInfo?.eventConfiguration ||
                    closeInfo.special ||
                    closeInfo.dismiss
                ) {
                    // wizard popup closed or 'Cancel' button triggered
                    if (!this.props.record.data.event_ticket_id) {
                        // remove product if event configuration was cancelled.
                        this.props.record.update({
                            [this.props.name]: undefined,
                        });
                    }
                } else {
                    const eventConfiguration = closeInfo.eventConfiguration;
                    this.props.record.update(eventConfiguration);
                }
            },
        });
    },
});
