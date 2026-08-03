/** @odoo-module native */

import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { ConfirmationDialog } from "@web/ui/dialog";
import { FormController, formView } from "@web/views/form";

export class CurrencyFormController extends FormController {
    async onWillSaveRecord(record) {
        if (
            record.data.display_rounding_warning &&
            record._values.rounding !== undefined &&
            record.data.rounding < record._values.rounding
        ) {
            return new Promise((resolve) => {
                this.dialogService.add(ConfirmationDialog, {
                    title: _t("Confirmation Warning"),
                    body: _t(
                        "You're about to permanently change the decimals for all prices in your database.\n" +
                            "This change cannot be undone without technical support.",
                    ),
                    confirmLabel: _t("Confirm"),
                    cancelLabel: _t("Cancel"),
                    confirm: () => resolve(true),
                    cancel: () => {
                        record.discard();
                        resolve(false);
                    },
                });
            });
        }

        return true;
    }
}

export const currencyFormView = {
    ...formView,
    Controller: CurrencyFormController,
};

registry.category("views").add("currency_form", currencyFormView);
