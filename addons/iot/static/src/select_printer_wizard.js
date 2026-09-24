/** @odoo-module native */
import { onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { useEventBus, useService } from "@web/core/utils/hooks";
import {
    provideViewButtonContext,
    useViewButtonContext,
} from "@web/core/view_button_context_hooks";
import { FormController, formView } from "@web/views/form";

export class SelectPrinterFormController extends FormController {
    setup() {
        super.setup();
        this.viewButtonContext = useViewButtonContext();
        this.bus = useEventBus();
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.onClickViewButton = this.viewButtonContext.onClickViewButton;

        onWillUnmount(() => {
            // If the user closes the popup without selecting a printer we still send a message back
            this.bus.trigger("printer-selected", {
                reportId: this.props.context.report_id,
                deviceSettings: null,
            });
        });
        provideViewButtonContext({
            onClickViewButton: this.onClickViewButtonIoT.bind(this),
        });
    }

    async onClickViewButtonIoT(params) {
        const deviceSettings = {
            selectedDevices: this.model.root.evalContextWithVirtualIds.device_ids,
            skipDialog: this.model.root.evalContextWithVirtualIds.do_not_ask_again,
        };
        if (deviceSettings.selectedDevices.length > 0) {
            this.bus.trigger("printer-selected", {
                reportId: this.props.context.report_id,
                deviceSettings,
            });
            this.onClickViewButton(params);
        } else {
            this.notification.add(_t("Select at least one printer"), {
                title: _t("No printer selected"),
                type: "danger",
            });
        }
    }
}

export const selectPrinterForm = {
    ...formView,
    Controller: SelectPrinterFormController,
};

registry.category("views").add("select_printers_wizard", selectPrinterForm);
