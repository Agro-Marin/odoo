/** @odoo-module native */
import { luxon } from "@web/core/l10n/luxon";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Interaction } from "@web/public/interaction";

export class PurchaseDatetimePicker extends Interaction {
    static selector = ".o-purchase-datetimepicker";

    setup() {
        this.notification = this.services.notification;
    }

    start() {
        const initialValue = this.el.dataset.value;
        const picker = this.services.datetime_picker.create({
            target: this.el,
            onChange: (newDate) => this.waitFor(this.updateDate(newDate)),
            pickerProps: {
                type: "date",
                // The line may legitimately have no expected arrival date, in
                // which case the server emits no `data-value` at all. `fromISO`
                // of undefined is an *invalid* DateTime, which the picker would
                // accept and then render as garbage; pass nothing instead.
                value: initialValue ? luxon.DateTime.fromISO(initialValue) : undefined,
            },
        });
        picker.enable();
        // dispose() (not just the enable() cleanup): the service keeps every
        // created picker in a page-lifetime registry, so each interaction
        // restart would otherwise leak a registration retaining this.el and
        // leave an open popover behind.
        this.registerCleanup(() => picker.dispose());
    }

    /**
     * Persist one line's expected arrival date.
     *
     * The access token goes in the **payload**, not the query string: the
     * JSON-RPC dispatcher merges the JSON body with the URL path converters and
     * never reads the query string, so a `?access_token=` is dropped on the
     * floor and the update is rejected for exactly the token-bearing visitor
     * this page is built for.
     *
     * @param {import("@web/core/l10n/luxon").DateTime} newDate
     */
    async updateDate(newDate) {
        const { accessToken, orderId, lineId } = this.el.dataset;
        let result;
        try {
            result = await rpc(`/my/purchase/${orderId}/update`, {
                access_token: accessToken,
                [lineId]: newDate.toISODate(),
            });
        } catch {
            this.notification.add(
                _t("The date could not be saved. Please try again."),
                { type: "danger" },
            );
            return;
        }
        // The route reports its own outcome; a rejected update is not an
        // exception, so success has to be read rather than assumed.
        if (!result?.success) {
            this.notification.add(result?.error || _t("The date could not be saved."), {
                type: "danger",
            });
        }
    }
}

registry
    .category("public.interactions")
    .add("purchase.purchase_datetime_picker", PurchaseDatetimePicker);
