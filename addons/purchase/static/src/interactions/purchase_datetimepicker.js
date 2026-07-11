/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class PurchaseDatetimePicker extends Interaction {
    static selector = ".o-purchase-datetimepicker";

    start() {
        const picker = this.services.datetime_picker.create({
            target: this.el,
            onChange: (newDate) => {
                const { accessToken, orderId, lineId } = this.el.dataset;
                this.waitFor(
                    rpc(`/my/purchase/${orderId}/update?access_token=${accessToken}`, {
                        [lineId]: newDate.toISODate(),
                    }),
                );
            },
            pickerProps: {
                type: "date",
                value: luxon.DateTime.fromISO(this.el.dataset.value),
            },
        });
        picker.enable();
        // dispose() (not just the enable() cleanup): the service keeps every
        // created picker in a page-lifetime registry, so each interaction
        // restart would otherwise leak a registration retaining this.el and
        // leave an open popover behind.
        this.registerCleanup(() => picker.dispose());
    }
}

registry
    .category("public.interactions")
    .add("purchase.purchase_datetime_picker", PurchaseDatetimePicker);
