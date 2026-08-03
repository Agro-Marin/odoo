// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/settings_confirmation_dialog */

import { _t } from "@web/core/translation";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";

export class SettingsConfirmationDialog
    extends /** @type {any} */ (ConfirmationDialog)
{
    static template = "web.SettingsConfirmationDialog";
    static defaultProps = {
        title: _t("Unsaved changes"),
    };
    static props = {
        .../** @type {any} */ (ConfirmationDialog).props,
        stayHere: { type: Function, optional: true },
    };

    _stayHere() {
        if (this.props.stayHere) {
            this.props.stayHere();
        }
        this.props.close();
    }
}
